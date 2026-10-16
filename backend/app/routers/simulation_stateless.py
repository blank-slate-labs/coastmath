"""Stateless simulation endpoints — no DB access, no auth required.

The caller sends the full plan in the request body; nothing is read from
or written to the database.
"""

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.errors import validation_error
from app.rate_limit import limiter
from app.routers.engine_errors import engine_errors
from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.simulator import run_simulation
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from coastmath.schemas.simulation import (
    CompareResponse,
    HistoricalStressResult,
    SimulationResult,
    YearDelta,
)

router = APIRouter(tags=["simulation-stateless"])

# Valid historical data range, shared with the saved-plan routes in simulation.py.
HIST_MIN_YEAR = 1928
HIST_MAX_YEAR = 2024


def check_historical_start_year(year: int) -> None:
    """Refuse a historical start year outside the bundled return data."""
    if year < HIST_MIN_YEAR or year > HIST_MAX_YEAR:
        raise validation_error(
            f"historical_start_year must be between {HIST_MIN_YEAR} and {HIST_MAX_YEAR}", "historical_start_year",
            f"must be between {HIST_MIN_YEAR} and {HIST_MAX_YEAR}, got {year}",
        )


def net_worth_deltas(current: SimulationResult, baseline: SimulationResult) -> list[YearDelta]:
    """Net worth by year for both runs; a year missing from one run counts as 0 there."""
    current_by_year = {s.year: s.net_worth for s in current.yearly_snapshots}
    baseline_by_year = {s.year: s.net_worth for s in baseline.yearly_snapshots}
    return [
        YearDelta(
            year=y,
            current_net_worth=current_by_year.get(y, 0.0),
            baseline_net_worth=baseline_by_year.get(y, 0.0),
            difference=current_by_year.get(y, 0.0) - baseline_by_year.get(y, 0.0),
        )
        for y in sorted(set(current_by_year) | set(baseline_by_year))
    ]


class CompareStatelessRequest(BaseModel):
    current: PlanDataRequest
    baseline: PlanDataRequest


@router.post(
    "/simulate/stateless",
    response_model=SimulationResult | HistoricalStressResult,
)
@limiter.limit("30/minute")
def simulate_stateless(
    request: Request,
    body: PlanDataRequest,
    historical_start_year: int | None = Query(default=None),
) -> SimulationResult | HistoricalStressResult:
    plan_data = request_to_engine_data(body)

    if historical_start_year is None:
        with engine_errors("Simulation engine encountered an error",
                           "Stateless simulation failed for plan %s", body.plan_id, slot=False):
            return run_simulation(plan_data)

    check_historical_start_year(historical_start_year)

    with engine_errors("Historical stress test engine encountered an error",
                       "Stateless historical stress test failed for plan %s (start_year=%d)",
                       body.plan_id, historical_start_year, slot=False):
        raw = run_historical_stress_test(plan_data, start_year=historical_start_year)

    return HistoricalStressResult(
        simulation_result=raw["simulation_result"],
        metadata=raw["metadata"],
    )


@router.post(
    "/compare/stateless",
    response_model=CompareResponse,
)
def compare_stateless(
    body: CompareStatelessRequest,
) -> CompareResponse:
    current_data = request_to_engine_data(body.current)
    baseline_data = request_to_engine_data(body.baseline)

    with engine_errors("Simulation engine encountered an error for current plan",
                       "Stateless compare failed for current plan %s", body.current.plan_id, slot=False):
        current_result = run_simulation(current_data)

    with engine_errors("Simulation engine encountered an error for baseline plan",
                       "Stateless compare failed for baseline plan %s", body.baseline.plan_id, slot=False):
        baseline_result = run_simulation(baseline_data)

    return CompareResponse(
        current=current_result,
        baseline=baseline_result,
        delta=net_worth_deltas(current_result, baseline_result),
    )
