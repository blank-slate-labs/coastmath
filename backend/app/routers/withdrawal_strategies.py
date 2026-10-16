import datetime
import uuid
from contextlib import nullcontext
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import validation_error
from app.models.milestone import Milestone
from app.models.user import User
from app.monte_carlo_capacity import deadline, monte_carlo_slot, time_limit_error
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, get_plan_or_404, load_plan_data
from app.usage import count_usage
from coastmath.engine.monte_carlo import MonteCarloTimeLimit
from coastmath.engine.withdrawal_comparison import compare_withdrawal_strategies
from coastmath.engine.withdrawal_strategy import STRATEGY_METHODS

router = APIRouter(prefix="/plans/{plan_id}/withdrawal-strategies", tags=["withdrawal-strategies"])


class WithdrawalCompareRequest(BaseModel):
    methods: list[str] = Field(default=list(STRATEGY_METHODS), min_length=1, max_length=5)
    initial_rate: float = Field(default=0.04, gt=0, le=0.20)  # decimal
    start_milestone_id: uuid.UUID | None = None
    start_age: int | None = Field(default=None, ge=18, le=110)
    monte_carlo_trials: int = Field(default=0, ge=0, le=500)
    seed: int | None = Field(default=None, ge=0, le=2147483647)


class StrategyOutcomeRead(BaseModel):
    method: str
    label: str
    success: bool
    failure_year: int | None
    start_year: int | None
    first_year_spending: float
    total_real_spending: float
    median_real_spending: float
    min_real_spending: float
    max_real_spending: float
    real_spending_drawdown: float
    years_below_planned: int
    final_net_worth: float
    lifetime_taxes: float
    monte_carlo_success_rate: float | None
    monte_carlo_p10_final_net_worth: float | None
    spending_path: list[dict]
    notes: list[str]


class WithdrawalCompareResponse(BaseModel):
    initial_rate: float
    planned: StrategyOutcomeRead
    strategies: list[StrategyOutcomeRead]
    caveats: list[str]
    method_labels: dict[str, str]


@router.post("/compare", response_model=WithdrawalCompareResponse, dependencies=[Depends(count_usage("withdrawal_optimizer"))])
@limiter.limit("10/minute", key_func=session_user)
@engine_budget
def compare(
    request: Request,
    plan_id: uuid.UUID,
    body: WithdrawalCompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> WithdrawalCompareResponse:
    """Run the plan under each textbook withdrawal rule and report spending and success."""
    get_plan_or_404(plan_id, current_user.id, db)
    unknown = [m for m in body.methods if m not in STRATEGY_METHODS]
    if unknown:
        raise validation_error("Unknown withdrawal method", "methods", f"unknown: {unknown}")
    if body.start_milestone_id is not None and not db.query(Milestone.id).filter(
        Milestone.id == body.start_milestone_id, Milestone.plan_id == plan_id
    ).first():
        raise validation_error("Milestone not found in this plan", "start_milestone_id", "not found")
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    # Trials run in process pools, so they share the single Monte Carlo slot and
    # its two-process limit rather than starting one pool per CPU per method.
    with (engine_errors("Withdrawal strategy comparison engine encountered an error",
                        "Withdrawal strategy comparison failed for plan %s", plan_id,
                        translate={MonteCarloTimeLimit: time_limit_error("monte_carlo_trials")}),
          monte_carlo_slot() if body.monte_carlo_trials else nullcontext()):
        comparison = compare_withdrawal_strategies(
            plan_data, methods=body.methods, initial_rate=body.initial_rate,
            start_milestone_id=str(body.start_milestone_id) if body.start_milestone_id else None,
            start_age=body.start_age, mc_trials=body.monte_carlo_trials, seed=body.seed, max_workers=2,
            deadline=deadline(),
        )
    return WithdrawalCompareResponse(
        initial_rate=comparison.initial_rate,
        planned=StrategyOutcomeRead(**asdict(comparison.planned)),
        strategies=[StrategyOutcomeRead(**asdict(s)) for s in comparison.strategies],
        caveats=comparison.caveats,
        method_labels=STRATEGY_METHODS,
    )
