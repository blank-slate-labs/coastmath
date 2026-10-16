"""POST /api/plans/{plan_id}/plan-checks: the plan accuracy checklist."""

import copy
import datetime
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.clock import utcnow
from app.db import get_db
from app.ledger.balances import source_problem
from app.ledger.environments import environment_for
from app.models.financial_connection import FinancialBalanceLink, FinancialSource
from app.models.user import User
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, load_plan_data
from app.usage import count_usage
from coastmath.engine.plan_checks import evaluate_plan_checks
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import PlanData

router = APIRouter(prefix="/plans/{plan_id}/plan-checks", tags=["plan-checks"])

CheckKey = Literal[
    "accounts_entered", "expenses_entered", "social_security_self", "social_security_spouse",
    "earned_income_ends", "pre_medicare_coverage", "balances_current",
]
ReviewKey = Literal["high_real_stock_return", "low_inflation", "event_never_runs", "milestone_missed",
                    "zero_social_security", "cost_basis_assumed"]
SectionKey = Literal["plan_details", "assumptions", "milestones", "income", "expenses", "accounts", "healthcare"]


class PlanCheckRead(BaseModel):
    """One applicable completeness check."""
    key: CheckKey
    weight: int
    passes: bool


class PlanCheckItemRead(BaseModel):
    """A failing completeness check (``missing``) or an unscored ``review`` item.

    ``section`` is the plan editor section that fixes it; ``target_id`` the
    income, expense, account or milestone id when the item names one.
    """
    key: CheckKey | ReviewKey
    kind: Literal["missing", "review"]
    section: SectionKey
    title: str
    target_id: str | None = None
    person: Literal["self", "spouse"] | None = None


class PlanChecksResponse(BaseModel):
    #: Weighted share of applicable checks that pass, 0-100.
    score: int
    checks: list[PlanCheckRead]
    #: Missing items by check weight, then review items.
    items: list[PlanCheckItemRead]


def _balance_currency(plan_data: PlanData, user_id: uuid.UUID, db: Session) -> dict[str, bool]:
    """Whether each plan account with a connected balance is current, by the connection rules."""
    account_ids = []
    for key in plan_data.accounts:
        try:
            account_ids.append(uuid.UUID(str(key)))
        except ValueError:
            continue
    if not account_ids:
        return {}
    rows = (db.query(FinancialBalanceLink, FinancialSource)
            .join(FinancialSource, FinancialBalanceLink.source_id == FinancialSource.id)
            .filter(FinancialBalanceLink.user_id == user_id, FinancialBalanceLink.account_id.in_(account_ids))
            .all())
    if not rows:
        return {}
    now = utcnow()
    return {str(link.account_id): not (link.error or source_problem(source, now)
                                       or source.environment != environment_for(source.provider))
            for link, source in rows}


@router.post("", response_model=PlanChecksResponse, dependencies=[Depends(count_usage("plan_checks"))])
@limiter.limit("60/minute", key_func=session_user)
@engine_budget
def plan_checks(
    request: Request,
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> PlanChecksResponse:
    """Score the plan's completeness and list missing inputs and review items. Not saved."""
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    balance_current = _balance_currency(plan_data, current_user.id, db)
    with engine_errors("Plan checks encountered an error", "Plan checks failed for plan %s", plan_id):
        result = run_simulation(copy.deepcopy(plan_data))
        checks = evaluate_plan_checks(plan_data, result.metadata.milestone_outcomes, balance_current)
    return PlanChecksResponse(**asdict(checks))
