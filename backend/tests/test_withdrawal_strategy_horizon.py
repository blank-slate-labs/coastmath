"""1/N and VPW count the modeled years left, this year included, so the
final modeled year withdraws the whole remaining portfolio."""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    PlanData,
)
from coastmath.engine.withdrawal_strategy import (
    WithdrawalStrategySpec,
    WithdrawalStrategyState,
    strategy_spending,
)

ZERO = AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0)
FLAT = {"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0}


def _plan(life_expectancy: int, method: str) -> PlanData:
    # Born January 1960: life expectancy 67 ends the projection after 2026.
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000102", birth_year=1960, birth_month=1,
        life_expectancy=life_expectancy, start_year=2026, filing_status="single", state_code="FL",
        assumptions=ZERO, accounts={"cash": AccountInfo(100_000, "checking")},
        drawdown_order=[DrawdownEntryData(1, "cash")], tax_settings=FLAT,
        withdrawal_strategy=WithdrawalStrategySpec(method),
    )


@pytest.mark.parametrize("method", ["one_over_n", "vpw"])
def test_one_year_plan_spends_the_whole_portfolio(method):
    snaps = run_simulation(_plan(67, method)).yearly_snapshots
    assert [s.year for s in snaps] == [2026]
    assert snaps[0].strategy_spending == pytest.approx(100_000)
    assert snaps[0].accounts["cash"] == pytest.approx(0.0, abs=1e-6)


def test_one_over_n_divides_by_the_modeled_years_left():
    snaps = run_simulation(_plan(70, "one_over_n")).yearly_snapshots
    assert [s.year for s in snaps] == [2026, 2027, 2028, 2029]
    # Zero growth: 100k / 4, then 75k / 3, ... -> 25k a year, nothing left after the final year.
    assert [s.strategy_spending for s in snaps] == pytest.approx([25_000] * 4)
    assert snaps[-1].accounts["cash"] == pytest.approx(0.0, abs=1e-6)


def test_vpw_final_modeled_year_spends_everything_left():
    snaps = run_simulation(_plan(70, "vpw")).yearly_snapshots
    assert snaps[-1].year == 2029
    assert snaps[-1].strategy_spending == pytest.approx(snaps[-2].accounts["cash"])
    assert snaps[-1].accounts["cash"] == pytest.approx(0.0, abs=1e-6)


def _gk(state, years_remaining, *, year, portfolio):
    return strategy_spending(WithdrawalStrategySpec("guyton_klinger", 0.05), state, year=year, age=65,
                             portfolio=portfolio, inflation_factor=1.0, years_remaining=years_remaining)


@pytest.mark.parametrize("years_remaining,cut", [(16, True), (15, False)])
def test_guardrail_cuts_stop_in_the_last_fifteen_modeled_years(years_remaining, cut):
    state = WithdrawalStrategyState()
    _gk(state, years_remaining + 1, year=2030, portfolio=1_000_000)
    # Rate 50k / 700k = 7.1% exceeds 120% of 5%: a cut applies only outside the last 15 years.
    spent = _gk(state, years_remaining, year=2031, portfolio=700_000)
    assert spent == pytest.approx(45_000 if cut else 50_000)
    assert state.guardrail_cuts == (1 if cut else 0)
