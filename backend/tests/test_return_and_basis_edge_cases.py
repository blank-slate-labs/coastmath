"""Edge cases for taxable basis, historical replay inputs and return extremes.

A sale after price growth or loss keeps the opening basis, including an unknown
basis; historical replay rejects missing, duplicate, fractional or non-numeric
years and rates, and accepts unsorted contiguous years without mutating the
input; a complete loss never creates negative wealth. Monthly savings deposits
are checked against an independent monthly recurrence; that case is a strict
xfail recording the known open limitation that they earn no within-year cash
interest. Expected values are derived by hand, not from engine output.
"""

import pandas as pd
import pytest

from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    PlanData,
    PriorityData,
    SimState,
)


def _plan(account_type="taxable_brokerage"):
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000019",
        birth_year=1980, life_expectancy=48, start_year=2026, filing_status="single",
        accounts={"account": AccountInfo(100_000, account_type, cost_basis=100_000)},
        assumptions=AssumptionData(
            inflation_rate=0, stock_growth_rate=0, stock_dividend_yield=.02,
            bond_return_rate=0, cash_yield_rate=0,
        ),
    )


def _history(years=(2026, 2027), **columns):
    data = dict(year=list(years), stock_return=[.05, .05], bond_return=[0., 0.],
                inflation=[0., 0.], dividend_yield=[0., 0.])
    data.update(columns)
    return pd.DataFrame(data)


@pytest.mark.parametrize("account_type", ["taxable_brokerage", "cryptocurrency"])
@pytest.mark.parametrize("opening_basis", [None, 0., 800.])
@pytest.mark.parametrize("price_return", [-.1, .1])
def test_growth_then_sale_preserves_opening_basis(account_type, opening_basis, price_return):
    state = SimState(2026, {"account": AccountInfo(1_000, account_type, cost_basis=opening_basis)})
    state.apply_growth(stock_growth_rate=price_return)
    sale = 1_000 * (1 + price_return) / 2
    state.withdraw_from("account", sale)
    basis = 1_000 if opening_basis is None else opening_basis
    assert state.accounts["account"].cost_basis == pytest.approx(basis / 2)
    assert state.capital_gains_this_year == pytest.approx(sale - basis / 2)


@pytest.mark.parametrize("years", [(2026, 2028), (2026, 2026), (2026.5, 2027.5)])
def test_historical_replay_rejects_missing_duplicate_or_fractional_years(years):
    with pytest.raises(ValueError, match="historical return data.*year"):
        run_historical_stress_test(_plan(), 2026, historical_data=_history(years))


@pytest.mark.parametrize("column", ["stock_return", "bond_return", "inflation", "dividend_yield"])
@pytest.mark.parametrize("value", [True, "0.05"])
def test_historical_replay_rejects_nonnumeric_rate_types(column, value):
    with pytest.raises(ValueError, match="historical return data"):
        run_historical_stress_test(_plan(), 2026, historical_data=_history(**{column: [value, value]}))


def test_historical_replay_accepts_unsorted_contiguous_years_without_mutation():
    history = _history((2027, 2026), stock_return=[.20, .10])
    original = history.copy(deep=True)
    result = run_historical_stress_test(_plan(), 2026, historical_data=history)
    assert result["metadata"]["years_used"] == [2026, 2027]
    assert [s.accounts["account"] for s in result["simulation_result"].yearly_snapshots] == pytest.approx([110_000, 132_000])
    pd.testing.assert_frame_equal(history, original)


@pytest.mark.parametrize("account_type", ["taxable_brokerage", "cryptocurrency"])
def test_complete_loss_with_unknown_yield_never_creates_negative_wealth(account_type):
    result = run_simulation(_plan(account_type), override_returns={2026: (-1., 0., 0.), 2027: (-1., 0., 0.)})
    assert [s.accounts["account"] for s in result.yearly_snapshots] == pytest.approx([0., 0.])
    assert [s.net_worth for s in result.yearly_snapshots] == pytest.approx([0., 0.])


@pytest.mark.xfail(strict=True, reason="Known open limitation: monthly savings deposits earn no within-year cash interest")
def test_monthly_savings_deposits_match_independent_monthly_recurrence():
    plan = _plan("savings")
    plan.life_expectancy = 47
    plan.accounts["account"].balance = 0
    plan.assumptions.cash_yield_rate = .05
    plan.income_streams = [IncomeData("income", "Income", 12_000, is_earned_income=False, growth_rate=0)]
    plan.priorities = [PriorityData(1, target_account_id="account", max_annual_amount=12_000)]
    plan.tax_settings = {"cash_flow_frequency": "monthly"}
    snap = run_simulation(plan).yearly_snapshots[0]
    balance = 0.
    monthly_factor = 1.05 ** (1 / 12)
    for _ in range(12):
        balance = balance * monthly_factor + 1_000
    assert snap.taxes == 0
    assert snap.accounts["account"] == pytest.approx(balance)
