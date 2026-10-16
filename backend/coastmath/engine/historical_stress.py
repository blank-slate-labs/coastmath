"""Historical stress-test engine — deterministic replay of actual market history.

Given a start year (e.g. 1966, 2000, 2007), slices real S&P 500 / bond / CPI
data from ``load_historical_returns`` and feeds it through ``run_simulation``
via the ``override_returns`` mechanism.  This is NOT Monte Carlo — it produces
a single deterministic timeline showing what *would have happened* if the plan
started in that historical period.
"""

from __future__ import annotations

import copy

import pandas as pd

from coastmath.engine.historical_data import load_historical_returns
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.monte_carlo import validate_historical_returns
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import PlanData
from coastmath.schemas.simulation import SimulationResult


def _build_override_returns(
    historical_df: pd.DataFrame,
    sim_start_year: int,
    sim_end_year: int,
    hist_start_year: int,
) -> tuple[dict[int, tuple], list[int], bool]:
    """Map each simulation year to a row of historical data.

    If the plan runs longer than the remaining historical data from
    *hist_start_year*, wraps around to the earliest year in the dataset.

    Returns (override_dict, historical_years_used, wrapped).
    """
    validate_historical_returns(historical_df, require_year=True)
    min_hist = int(historical_df["year"].min())
    max_hist = int(historical_df["year"].max())
    total_hist_years = max_hist - min_hist + 1

    # Build a list indexed 0..N-1 for easy wrap-around
    sorted_df = historical_df.sort_values("year").reset_index(drop=True)
    hist_offset = hist_start_year - min_hist  # index of start year in sorted list

    override: dict[int, tuple] = {}
    years_used: list[int] = []
    wrapped = False

    plan_duration = sim_end_year - sim_start_year
    for i in range(plan_duration):
        idx = (hist_offset + i) % total_hist_years
        if hist_offset + i >= total_hist_years:
            wrapped = True
        row = sorted_df.iloc[idx]
        sim_year = sim_start_year + i
        raw_yield = row["dividend_yield"] if "dividend_yield" in sorted_df.columns else None
        override[sim_year] = (
            float(row["stock_return"]),
            float(row["bond_return"]),
            float(row["inflation"]),
            None if raw_yield is None or pd.isna(raw_yield) else float(raw_yield),
        )
        years_used.append(int(row["year"]))

    return override, years_used, wrapped


def run_historical_stress_test(
    plan_data: PlanData,
    start_year: int,
    historical_data: pd.DataFrame | None = None,
) -> dict:
    """Run a deterministic simulation using actual historical returns.

    Parameters
    ----------
    plan_data:
        The financial plan to simulate.
    start_year:
        The historical year to begin replaying returns from (e.g. 1928, 1966, 2000).
    historical_data:
        Optional pre-loaded DataFrame.  If ``None``, loads from the CSV.

    Returns
    -------
    dict with keys:
        ``simulation_result`` — the full :class:`SimulationResult`
        ``metadata`` — dict with ``historical_start_year``, ``years_used``, ``wrapped``
    """
    df = historical_data if historical_data is not None else load_historical_returns()
    validate_historical_returns(df, require_year=True)

    min_hist = int(df["year"].min())
    max_hist = int(df["year"].max())

    if start_year < min_hist or start_year > max_hist:
        raise ValueError(
            f"start_year {start_year} is outside available historical data "
            f"({min_hist}–{max_hist})"
        )

    sim_start = plan_data.start_year
    sim_end = simulation_end_year(plan_data)

    override, years_used, wrapped = _build_override_returns(
        df, sim_start, sim_end, start_year,
    )

    # Deep-copy so we don't mutate the caller's plan
    plan_copy = copy.deepcopy(plan_data)

    result: SimulationResult = run_simulation(plan_copy, override_returns=override)

    return {
        "simulation_result": result,
        "metadata": {
            "historical_start_year": start_year,
            "years_used": years_used,
            "wrapped": wrapped,
        },
    }
