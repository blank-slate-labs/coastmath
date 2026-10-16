"""POST /api/plans/{plan_id}/wellness: the financial wellness scorecard."""

import datetime
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import validation_error
from app.models.user import User
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, load_plan_data
from app.usage import count_usage
from coastmath.engine.simulator import run_simulation
from coastmath.engine.wellness import wellness_scorecard

router = APIRouter(prefix="/plans/{plan_id}/wellness", tags=["wellness"])

WellnessKey = Literal[
    "savings_rate", "emergency_fund", "debt_to_income", "savings_to_income", "withdrawal_rate",
    "guaranteed_income", "pre_tax_share", "funded_years", "fi_timing",
]


class WellnessBandsRead(BaseModel):
    """Grading thresholds. ``better="higher"``: at or above ``strong_at``
    is strong, at or above ``fair_at`` is fair, below needs attention;
    ``"lower"`` mirrors it (at or below)."""
    better: Literal["higher", "lower"]
    fair_at: float
    strong_at: float


class WellnessMetricRead(BaseModel):
    key: WellnessKey
    label: str
    #: ``percent`` and ``ratio`` are decimals (0.2 = 20%); ``year`` is a calendar year.
    value: float | None = None
    unit: Literal["percent", "months", "ratio", "multiple", "currency", "year", "age"]
    status: Literal["strong", "fair", "needs_attention", "not_applicable"]
    #: Null when not applicable.
    bands: WellnessBandsRead | None = None
    #: The projection year the value reads (currency values are that year's dollars).
    basis_year: int | None = None
    #: Web plan section whose inputs drive the metric.
    section: str | None = None


class WellnessResponse(BaseModel):
    start_year: int
    #: Always every metric, in a fixed order; not-applicable ones included.
    metrics: list[WellnessMetricRead]


@router.post("", response_model=WellnessResponse, dependencies=[Depends(count_usage("wellness"))])
@limiter.limit("60/minute", key_func=session_user)
@engine_budget
def wellness(
    request: Request,
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> WellnessResponse:
    """Grade the plan's key ratios from one deterministic projection. Not saved."""
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    with engine_errors("Wellness scorecard engine encountered an error", "Wellness scorecard failed for plan %s",
                       plan_id, translate={ValueError: lambda exc: validation_error(str(exc), "plan")}):
        result = wellness_scorecard(plan_data, run_simulation(plan_data))
    return WellnessResponse(start_year=result.start_year,
                            metrics=[WellnessMetricRead(**asdict(metric)) for metric in result.metrics])
