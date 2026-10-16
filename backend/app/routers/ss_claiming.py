"""POST /api/plans/{plan_id}/social-security/claiming: compare claiming ages."""

import datetime
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, ConfigDict, model_serializer
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import validation_error
from app.models.user import User
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, load_plan_data
from app.usage import count_usage
from coastmath.engine.ss_claiming import explore_claiming_ages

router = APIRouter(prefix="/plans/{plan_id}/social-security", tags=["social-security"])

Owner = Literal["self", "spouse"]


class ClaimingExplorerRequest(BaseModel):
    """No options yet; unknown fields are rejected."""
    model_config = ConfigDict(extra="forbid")


class ClaimingPersonRead(BaseModel):
    owner: Owner
    adjustable: bool
    #: Why the claiming age is not varied: no_benefit, multiple_benefits,
    #: already_claimed, unresolved_claim_date, missing_birth_year or
    #: no_candidate_ages. Null when adjustable.
    reason: str | None = None
    income_id: str | None = None
    birth_year: int | None = None
    birth_month: int = 1
    full_retirement_age: float | None = None
    #: Fractional age of the planned first payment month.
    current_claim_age: float | None = None
    candidate_ages: list[int] = []
    benefit_basis: Literal["amount", "pia"] | None = None
    #: The earnings test, counting this person's earnings, withholds benefits
    #: before full retirement age in the current plan or a compared run.
    #: Additive; older services omit it.
    earnings_test_withholds: bool = False


class ClaimingRunRead(BaseModel):
    claim_ages: dict[Owner, float]
    #: Own retirement benefit at claim, annual, plan-start dollars.
    first_year_benefits: dict[Owner, float]
    #: Household Social Security received each year of ``years``, nominal.
    social_security_by_year: list[float]
    lifetime_social_security: float  # nominal
    lifetime_taxes: float  # nominal
    end_net_worth: float  # nominal
    #: End net worth less income tax at ``pre_tax_discount_rate`` on pre-tax balances; the ranking basis.
    end_net_worth_after_tax: float
    success: bool
    failure_year: int | None = None
    end_net_worth_after_tax_change: float  # this run minus the current run
    lifetime_social_security_change: float


class ClaimingIncomeChanges(BaseModel):
    """``IncomeUpdate`` fields; ``annual_amount`` only for amount-basis benefits."""
    claiming_age: int
    start_milestone_id: None = None
    start_month: None = None
    annual_amount: float | None = None

    @model_serializer(mode="wrap")
    def omit_amount_for_pia(self, handler):
        data = handler(self)
        if self.annual_amount is None:
            data.pop("annual_amount", None)
        return data


class ClaimingPatchRead(BaseModel):
    owner: Owner
    claiming_age: int
    income_id: str
    #: Send as-is to PUT /api/plans/{plan_id}/incomes/{income_id}.
    changes: ClaimingIncomeChanges


class ClaimingExplorerResponse(BaseModel):
    persons: list[ClaimingPersonRead]
    years: list[int]
    #: The plan as saved; null when no person is adjustable.
    current: ClaimingRunRead | None = None
    #: Grid in ascending age order; with two people, self's age is the outer loop.
    runs: list[ClaimingRunRead]
    best_index: int | None = None
    best_end_net_worth_after_tax_change: float | None = None
    best_lifetime_social_security_change: float | None = None
    #: Heir income tax rate when set, else 0.24.
    pre_tax_discount_rate: float
    patches: list[ClaimingPatchRead]


@router.post("/claiming", response_model=ClaimingExplorerResponse,
             dependencies=[Depends(count_usage("ss_claiming_explorer"))])
@limiter.limit("10/minute", key_func=session_user)
@engine_budget
def explore_claiming(
    request: Request,
    plan_id: uuid.UUID,
    body: ClaimingExplorerRequest | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> ClaimingExplorerResponse:
    """Run the saved plan at each Social Security claiming-age combination. Nothing is saved."""
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    with engine_errors("Claiming-age comparison engine encountered an error", "Claiming explorer failed for plan %s",
                       plan_id, translate={ValueError: lambda exc: validation_error(str(exc), "plan")}):
        exploration = explore_claiming_ages(plan_data)
    return ClaimingExplorerResponse.model_validate(asdict(exploration))
