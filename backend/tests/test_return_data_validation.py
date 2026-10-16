"""Historical and override return data are validated at every public entry point.

Returns below -100%, -100% inflation, non-finite rates, invalid dividend
yields, a dividend paid alongside a total loss and malformed override rows are
rejected by the validators, Monte Carlo, historical stress and the
deterministic simulation; so are empty history and zero trials. An unknown
dividend yield, an exact total loss and a duplicate DataFrame index are
accepted.
"""

import uuid

import numpy as np
import pandas as pd
import pytest

from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.monte_carlo import (
    build_block_bootstrap_sequence,
    run_monte_carlo,
    validate_historical_returns,
)
from coastmath.engine.return_validation import validate_override_returns
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo, AssumptionData, PlanData


def _plan() -> PlanData:
    return PlanData(
        plan_id=str(uuid.uuid4()),
        birth_year=1980,
        filing_status="single",
        life_expectancy=70,
        start_year=2026,
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0),
        accounts={"cash": AccountInfo(100_000, "checking")},
    )


def _history(**overrides) -> pd.DataFrame:
    values = {
        "year": [2026, 2027],
        "stock_return": [0.07, 0.07],
        "bond_return": [0.04, 0.04],
        "inflation": [0.03, 0.03],
    }
    values.update(overrides)
    return pd.DataFrame(values)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("stock_return", -1.000001),
        ("bond_return", -1.000001),
        ("inflation", -1.0),
        ("stock_return", np.inf),
        ("bond_return", np.nan),
    ],
)
def test_return_validation_rejects_invalid_price_or_rate(column, value):
    history = _history(**{column: [value, value]})
    with pytest.raises(ValueError, match="historical return data"):
        validate_historical_returns(history)


@pytest.mark.parametrize("value", [-0.01, np.inf, "not-a-rate"])
def test_return_validation_rejects_invalid_dividend_yield(value):
    history = _history(dividend_yield=[value, value])
    with pytest.raises(ValueError, match="dividend_yield"):
        validate_historical_returns(history)


def test_return_validation_rejects_impossible_price_component():
    # A -100% total return cannot also distribute a positive dividend.
    history = _history(stock_return=[-1.0, -1.0], dividend_yield=[0.02, 0.02])
    with pytest.raises(ValueError, match="price return"):
        validate_historical_returns(history)


def test_missing_dividend_yield_is_allowed_as_unknown():
    history = _history(dividend_yield=[np.nan, np.nan])
    validate_historical_returns(history)
    result = build_block_bootstrap_sequence(history, 3)
    assert result.shape == (3, 4)


def test_return_validation_and_bootstrap_accept_duplicate_dataframe_index():
    history = _history().set_axis([2026, 2026])
    validate_historical_returns(history)
    result = build_block_bootstrap_sequence(history, 3, rng=np.random.default_rng(7))
    assert result.shape == (3, 3)


def test_public_monte_carlo_boundary_rejects_empty_history_and_zero_trials():
    with pytest.raises(ValueError, match="historical return data"):
        run_monte_carlo(_plan(), n_trials=1, historical_data=_history().iloc[0:0], max_workers=1)
    with pytest.raises(ValueError, match="n_trials"):
        run_monte_carlo(_plan(), n_trials=0, historical_data=_history(), max_workers=1)


def test_public_historical_stress_boundary_rejects_invalid_history():
    with pytest.raises(ValueError, match="historical return data"):
        run_historical_stress_test(
            _plan(), start_year=2026,
            historical_data=_history(stock_return=[-2.0, -2.0]),
        )


def test_override_validation_accepts_exact_total_loss_without_dividend():
    validate_override_returns({2026: (-1.0, 0.04, 0.03)})


@pytest.mark.parametrize(
    "row",
    [
        (0.07, 0.04),
        (np.nan, 0.04, 0.03),
        (0.07, 0.04, -1.0),
        (0.07, 0.04, 0.03, np.nan),
        ("0.07", 0.04, 0.03),
        "000",
    ],
)
def test_override_validation_rejects_malformed_or_nonfinite_rows(row):
    with pytest.raises(ValueError):
        validate_override_returns({2026: row})


def test_public_deterministic_override_boundary_rejects_invalid_return():
    with pytest.raises(ValueError, match="stock return"):
        run_simulation(_plan(), override_returns={2026: (-2.0, 0.04, 0.03)})
