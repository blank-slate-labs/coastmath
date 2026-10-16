"""Public return-input rejection boundaries, including malformed history schemas.

Deterministic overrides reject malformed containers; historical replay rejects
missing or duplicated return columns and non-integer calendar years.
"""

import pandas as pd
import pytest

from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo, PlanData


def _plan():
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000020",
        filing_status="single", birth_year=1980, life_expectancy=48, start_year=2026,
        accounts={"cash": AccountInfo(100_000, "checking")},
    )


@pytest.mark.parametrize("returns", [[], {2026: 0.1}, {2026: {"stock": .1, "bond": .03, "inflation": .02}}])
def test_simulation_rejects_malformed_override_containers(returns):
    with pytest.raises(ValueError, match="return override"):
        run_simulation(_plan(), override_returns=returns)


@pytest.mark.parametrize("history", [
    pd.DataFrame({"year": [2026], "stock_return": [.1], "inflation": [.02]}),
    pd.DataFrame([[2026, .1, .2, .03, .02]],
                 columns=["year", "stock_return", "stock_return", "bond_return", "inflation"]),
])
def test_historical_replay_rejects_missing_or_ambiguous_return_columns(history):
    with pytest.raises(ValueError, match="historical return data.*columns"):
        run_historical_stress_test(_plan(), 2026, historical_data=history)


@pytest.mark.parametrize("year", [float("nan"), float("inf"), "2026", True])
def test_historical_replay_rejects_invalid_calendar_year_types(year):
    history = pd.DataFrame({"year": [year], "stock_return": [.1],
                            "bond_return": [.03], "inflation": [.02]})
    with pytest.raises(ValueError, match="historical return data years"):
        run_historical_stress_test(_plan(), 2026, historical_data=history)
