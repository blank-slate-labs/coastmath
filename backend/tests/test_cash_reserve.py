"""Opt-in cash reserve: protected balances spent only after the rest of the order."""
import pytest

from coastmath.engine.cash_reserve import cash_reserve_from_settings, reserve_floors
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CashReserveData,
    DrawdownEntryData,
    ExpenseData,
    PlanData,
    SimState,
)
from coastmath.engine.waterfall import execute_drawdown

ZERO = AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0)


def _accounts():
    return {
        'cash': AccountInfo(20_000, 'checking'),
        'brokerage': AccountInfo(50_000, 'taxable_brokerage', cost_basis=50_000),
        'savings': AccountInfo(10_000, 'savings'),
    }


def _state(reserve_ids=('cash',), target=15_000):
    state = SimState(2026, accounts=_accounts())
    state.cash_reserve_accounts = tuple(reserve_ids)
    state.cash_reserve_target = target
    return state


ORDER = [DrawdownEntryData(1, 'cash'), DrawdownEntryData(2, 'savings'), DrawdownEntryData(3, 'brokerage')]


def test_floors_fill_in_listed_order_and_never_exceed_balances():
    assert reserve_floors({'a': 5, 'b': 10}, ('a', 'b'), 8) == {'a': 5, 'b': 3}
    assert reserve_floors({'a': 5}, ('a', 'b'), 100) == {'a': 5}
    assert reserve_floors({'a': 0}, ('a',), 100) == {}


def test_settings_parse_only_when_enabled_with_accounts_and_amount():
    assert cash_reserve_from_settings(None) is None
    assert cash_reserve_from_settings({'enabled': False, 'account_ids': ['a'], 'reserve_amount': 5}) is None
    assert cash_reserve_from_settings({'enabled': True, 'account_ids': [], 'reserve_amount': 5}) is None
    assert cash_reserve_from_settings({'enabled': True, 'account_ids': ['a'], 'reserve_amount': 0}) is None
    assert cash_reserve_from_settings({'enabled': True, 'account_ids': ['a'], 'reserve_amount': 5}) == CashReserveData(('a',), 5.0)


def test_default_order_unchanged_without_a_reserve():
    state = SimState(2026, accounts=_accounts())
    taken, _ = execute_drawdown(25_000, ORDER, state)
    assert taken == {'cash': 20_000, 'savings': 5_000}


def test_reserve_is_skipped_until_other_accounts_cannot_cover():
    state = _state()
    taken, _ = execute_drawdown(25_000, ORDER, state)
    # 5,000 of cash is above the 15,000 floor; savings and brokerage supply the rest.
    assert taken == {'cash': 5_000, 'savings': 10_000, 'brokerage': 10_000}
    assert state.get_balance('cash') == 15_000
    assert state.failure_year is None


def test_fallback_spends_reserve_only_after_everything_else_is_gone():
    state = _state()
    taken, _ = execute_drawdown(80_000, ORDER, state)
    assert taken['brokerage'] == 50_000 and taken['savings'] == 10_000
    assert taken['cash'] == 20_000
    assert state.get_balance('cash') == 0
    assert state.failure_year is None and state.unfunded_expenses == 0


def test_exhausted_reserve_records_the_shortfall_once():
    state = _state()
    taken, _ = execute_drawdown(100_000, ORDER, state)
    assert sum(taken.values()) == pytest.approx(80_000)
    assert state.failure_year == 2026
    assert state.unfunded_expenses == pytest.approx(20_000)


def test_locked_reserve_account_is_never_spent():
    state = _state()
    state.locked_account_ids = {'cash'}
    taken, _ = execute_drawdown(80_000, ORDER, state)
    assert 'cash' not in taken
    assert state.get_balance('cash') == 20_000
    assert state.unfunded_expenses == pytest.approx(20_000)


def test_listed_order_decides_which_reserve_account_goes_first():
    state = SimState(2026, accounts=_accounts())
    state.cash_reserve_accounts = ('savings', 'cash')
    state.cash_reserve_target = 30_000
    taken, _ = execute_drawdown(70_000, ORDER, state)
    # Brokerage covers 50,000; the fallback then drains savings before cash.
    assert taken['brokerage'] == 50_000
    assert taken['savings'] == 10_000 and taken['cash'] == 10_000


def test_partial_passes_do_not_touch_the_reserve():
    state = _state()
    taken, _ = execute_drawdown(40_000, [DrawdownEntryData(1, 'cash')], state, reserve_fallback=False)
    assert taken == {'cash': 5_000}
    assert state.unfunded_expenses == pytest.approx(35_000)


def _plan(reserve):
    return PlanData(
        plan_id='00000000-0000-4000-8000-000000000072', birth_year=1980, birth_month=1,
        filing_status='single', life_expectancy=48, start_year=2026, state_code='FL',
        assumptions=ZERO, accounts=_accounts(), drawdown_order=list(ORDER),
        expenses=[ExpenseData('spend', 'Living', 30_000, inflation_linked=False)],
        tax_settings={'cash_flow_frequency': 'annual'}, cash_reserve=reserve)


def test_simulation_holds_reserve_until_last():
    plain = {row.year: row for row in run_simulation(_plan(None)).yearly_snapshots}
    held = {row.year: row for row in run_simulation(_plan(CashReserveData(('cash',), 15_000))).yearly_snapshots}
    # Year one: default spends the 20,000 cash first; the reserve keeps 15,000 of it.
    assert plain[2026].accounts['cash'] == pytest.approx(0)
    assert held[2026].accounts['cash'] == pytest.approx(15_000)
    # Totals are conserved: the same money is spent, only from different accounts.
    assert sum(held[2026].accounts.values()) == pytest.approx(sum(plain[2026].accounts.values()))
