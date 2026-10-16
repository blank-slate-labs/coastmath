"""Monte Carlo simulation endpoint."""

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import validation_error
from app.models.plan import Plan
from app.models.user import User
from app.monte_carlo_capacity import deadline, run_with_capacity, time_limit_error
from app.rate_limit import engine_budget, limiter, session_user
from app.routers.engine_errors import engine_errors
from app.routers.helpers import client_today, load_plan_data
from app.usage import count_usage
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.monte_carlo import (
    MonteCarloInputError,
    MonteCarloTimeLimit,
    ReturnSampling,
    replay_monte_carlo_trial,
    run_monte_carlo,
)
from coastmath.engine.types import PlanData
from coastmath.engine.withdrawal_comparison import plan_inflation_factor
from coastmath.schemas.monte_carlo import (
    MonteCarloRequest,
    MonteCarloResult,
    MonteCarloTrialDetail,
    MonteCarloTrialRequest,
    SuccessTargets,
)

router = APIRouter(prefix="/plans", tags=["monte-carlo"])


def _targets_with_saved_legacy(body: MonteCarloRequest, plan: Plan, plan_data: PlanData) -> SuccessTargets | None:
    """Fill an omitted final net worth target from the plan's saved legacy target.

    The saved target is in today's dollars; the Monte Carlo target is nominal in the
    final projection year, so it is inflated with the plan's own inflation assumption.
    An explicit value, including null, is kept as sent.
    """
    targets = body.success_targets
    omitted = ("success_targets" not in body.model_fields_set
               or (targets is not None and "terminal_net_worth_min" not in targets.model_fields_set))
    saved = (plan.estate_settings or {}).get("legacy_target")
    if not omitted or saved is None:
        return targets
    final_year = simulation_end_year(plan_data) - 1
    nominal = float(saved) * plan_inflation_factor(plan_data, plan_data.start_year, final_year)
    return (targets or SuccessTargets()).model_copy(update={"terminal_net_worth_min": nominal})


def _block_range_error(body: MonteCarloRequest) -> HTTPException:
    return validation_error(
        "block_size_min must be <= block_size_max", "block_size_min",
        f"block_size_min ({body.block_size_min}) > block_size_max ({body.block_size_max})",
    )


def sampling_input_error(exc: MonteCarloInputError) -> HTTPException:
    """Sampling settings this plan cannot run, in the shared 422 envelope."""
    return validation_error(str(exc), exc.field)


def trial_index_error(index: int, n_trials: int) -> HTTPException:
    message = f"Trial index must be from 0 to {n_trials - 1} for a run of {n_trials} trials."
    return validation_error(message, "index", f"{index} is outside 0 to {n_trials - 1}")


@router.post(
    "/{plan_id}/monte-carlo",
    response_model=MonteCarloResult,
    dependencies=[Depends(count_usage("monte_carlo"))],
)
@limiter.limit("10/minute", key_func=session_user)
@engine_budget
async def monte_carlo_simulation(
    request: Request,
    plan_id: uuid.UUID,
    body: MonteCarloRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> MonteCarloResult:
    """Run Monte Carlo simulation for a plan.

    The plan loads on the job's thread once the Monte Carlo slot is held: a
    refused request costs no database work, and loading never blocks the event loop.
    """
    def run() -> MonteCarloResult:
        plan_data = load_plan_data(plan_id, current_user, db, today=today)
        if body.block_size_min > body.block_size_max:
            raise _block_range_error(body)
        # Monte Carlo capacity admits the run, so no projection slot is taken.
        with engine_errors("Monte Carlo simulation engine encountered an error",
                           "Monte Carlo simulation failed for plan %s", plan_id,
                           slot=False, translate={MonteCarloInputError: sampling_input_error,
                                                  MonteCarloTimeLimit: time_limit_error("n_trials")}):
            # Ownership was checked by the load above; this reads the same session row.
            success_targets = _targets_with_saved_legacy(body, db.get(Plan, plan_id), plan_data)
            return run_monte_carlo(
                plan_data,
                n_trials=body.n_trials,
                block_size_range=(body.block_size_min, body.block_size_max),
                failure_mode=body.failure_mode,
                seed=body.seed,
                success_targets=success_targets,
                calibrate_to_plan=body.calibrate_to_plan,
                sampling=ReturnSampling.from_options(body),
                outcome_thresholds=body.outcome_thresholds,
                extra_metrics=body.extra_metrics,
                max_workers=2,
                deadline=deadline(),
            )

    return await run_with_capacity(run)


@router.post(
    "/{plan_id}/monte-carlo/trials/{index}",
    response_model=MonteCarloTrialDetail,
    dependencies=[Depends(count_usage("monte_carlo_trial"))],
)
@limiter.limit("60/minute", key_func=session_user)
@engine_budget
def monte_carlo_trial(
    request: Request,
    plan_id: uuid.UUID,
    body: MonteCarloTrialRequest,
    index: int = Path(ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    today: datetime.date = Depends(client_today),
) -> MonteCarloTrialDetail:
    """Replay one trial of a Monte Carlo run with its full yearly projection.

    Send the run's settings and the ``base_seed`` it returned. One trial costs
    one projection, so this shares the projection slots, not the Monte Carlo one.
    The replay matches the run only while the plan is unchanged.
    """
    plan_data = load_plan_data(plan_id, current_user, db, today=today)
    if body.block_size_min > body.block_size_max:
        raise _block_range_error(body)
    if index >= body.n_trials:
        raise trial_index_error(index, body.n_trials)

    with engine_errors("Monte Carlo simulation engine encountered an error",
                       "Monte Carlo trial replay failed for plan %s", plan_id,
                       translate={MonteCarloInputError: sampling_input_error}):
        success_targets = _targets_with_saved_legacy(body, db.get(Plan, plan_id), plan_data)
        return replay_monte_carlo_trial(
            plan_data,
            index,
            body.base_seed,
            n_trials=body.n_trials,
            block_size_range=(body.block_size_min, body.block_size_max),
            failure_mode=body.failure_mode,
            success_targets=success_targets,
            calibrate_to_plan=body.calibrate_to_plan,
            sampling=ReturnSampling.from_options(body),
            outcome_thresholds=body.outcome_thresholds,
        )
