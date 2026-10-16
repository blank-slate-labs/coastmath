"""Stateless Monte Carlo simulation endpoint.

Accepts full plan data; a valid session is required for compute admission.
"""

from fastapi import APIRouter, Depends, Path, Request
from pydantic import Field, model_validator

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.monte_carlo_capacity import deadline, run_with_capacity, time_limit_error
from app.rate_limit import limiter
from app.routers.engine_errors import engine_errors
from app.routers.monte_carlo import sampling_input_error, trial_index_error
from coastmath.engine.monte_carlo import (
    MonteCarloInputError,
    MonteCarloTimeLimit,
    ReturnSampling,
    replay_monte_carlo_trial,
    run_monte_carlo,
)
from coastmath.schemas.monte_carlo import (
    MAX_BASE_SEED,
    MAX_MONTE_CARLO_TRIALS,
    FailureMode,
    MonteCarloMethodOptions,
    MonteCarloResult,
    MonteCarloTrialDetail,
)
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data

router = APIRouter(prefix="/monte-carlo", tags=["monte-carlo-stateless"])


class MonteCarloStatelessRequest(MonteCarloMethodOptions):
    plan: PlanDataRequest
    num_simulations: int = Field(default=1000, ge=1, le=MAX_MONTE_CARLO_TRIALS)
    block_size: int = Field(default=5, ge=1, le=30)
    failure_mode: FailureMode = "liquid_assets"
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    # Shift sampled history so its compound return matches the plan's
    # assumptions; False uses raw 1928-2024 averages.
    calibrate_to_plan: bool = True


class MonteCarloStatelessTrialRequest(MonteCarloStatelessRequest):
    """The stateless run's body plus the ``base_seed`` it returned."""

    num_simulations: int = Field(ge=1, le=MAX_MONTE_CARLO_TRIALS)
    base_seed: int = Field(ge=0, le=MAX_BASE_SEED)

    @model_validator(mode="after")
    def _seed_matches_base_seed(self) -> "MonteCarloStatelessTrialRequest":
        if self.seed is not None and self.seed != self.base_seed:
            raise ValueError("seed, when sent, must equal base_seed")
        return self


@router.post(
    "/stateless",
    response_model=MonteCarloResult,
)
@limiter.limit("10/minute")
async def monte_carlo_stateless(
    request: Request,
    body: MonteCarloStatelessRequest,
    current_user: User = Depends(get_current_user),
) -> MonteCarloResult:
    """Run Monte Carlo from inline plan data without loading stored plans."""
    plan_data = request_to_engine_data(body.plan)

    # Monte Carlo capacity admits the run, so no projection slot is taken.
    with engine_errors("Monte Carlo simulation engine encountered an error",
                       "Stateless Monte Carlo simulation failed",
                       slot=False, translate={MonteCarloInputError: sampling_input_error,
                                              MonteCarloTimeLimit: time_limit_error("num_simulations")}):
        return await run_with_capacity(
            lambda: run_monte_carlo(
                plan_data,
                n_trials=body.num_simulations,
                block_size_range=(body.block_size, body.block_size),
                failure_mode=body.failure_mode,
                seed=body.seed,
                calibrate_to_plan=body.calibrate_to_plan,
                sampling=ReturnSampling.from_options(body),
                outcome_thresholds=body.outcome_thresholds,
                extra_metrics=body.extra_metrics,
                max_workers=2,
                deadline=deadline(),
            ),
        )


@router.post(
    "/stateless/trials/{index}",
    response_model=MonteCarloTrialDetail,
)
@limiter.limit("60/minute")
def monte_carlo_stateless_trial(
    request: Request,
    body: MonteCarloStatelessTrialRequest,
    index: int = Path(ge=0),
    current_user: User = Depends(get_current_user),
) -> MonteCarloTrialDetail:
    """Replay one trial of a stateless run with its full yearly projection."""
    if index >= body.num_simulations:
        raise trial_index_error(index, body.num_simulations)
    plan_data = request_to_engine_data(body.plan)

    with engine_errors("Monte Carlo simulation engine encountered an error",
                       "Stateless Monte Carlo trial replay failed",
                       translate={MonteCarloInputError: sampling_input_error}):
        return replay_monte_carlo_trial(
            plan_data,
            index,
            body.base_seed,
            n_trials=body.num_simulations,
            block_size_range=(body.block_size, body.block_size),
            failure_mode=body.failure_mode,
            calibrate_to_plan=body.calibrate_to_plan,
            sampling=ReturnSampling.from_options(body),
            outcome_thresholds=body.outcome_thresholds,
        )
