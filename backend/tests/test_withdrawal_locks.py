"""Account withdrawal locks (coastmath.engine.withdrawal_locks).

Fixtures use zero growth, dividends and inflation, and cost basis equal to the
balance, so expected balances follow from the spending alone.
"""
from dataclasses import replace

import pytest

from coastmath.engine.monte_carlo import _compact_trial, aggregate_results
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    DrawdownEntryData,
    ExpenseData,
    MilestoneData,
    PlanData,
    PriorityData,
    SEPPSettingsData,
    SimState,
)
from coastmath.engine.withdrawal_locks import (
    is_withdrawal_locked,
    update_locked_accounts,
)

ZERO = AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0)


def _plan(accounts, *, order=None, **changes):
    options = dict(
        plan_id="00000000-0000-4000-8000-000000000071", birth_year=1980, birth_month=1,
        filing_status="single", life_expectancy=52, start_year=2026, state_code="FL",
        assumptions=ZERO, accounts=accounts,
        drawdown_order=[DrawdownEntryData(i + 1, aid) for i, aid in enumerate(order or accounts)],
        expenses=[ExpenseData("spend", "Living", 30_000, inflation_linked=False)],
        tax_settings={"cash_flow_frequency": "annual"},
    )
    options.update(changes)
    return PlanData(**options)


def _brokerage(balance, lock=None):
    return AccountInfo(balance, "taxable_brokerage", cost_basis=balance, withdrawal_lock=lock)


def _by_year(result):
    return {row.year: row for row in result.yearly_snapshots}


# --- Unlock rules -----------------------------------------------------------

def _state(year, *, self_age, birth_month=1, spouse_age=None, spouse_month=None, triggered=()):
    ages = {"self": self_age} | ({"spouse": spouse_age} if spouse_age is not None else {})
    return SimState(year=year, owner_ages=ages, triggered_milestones=set(triggered),
                    owner_birth_months={"self": birth_month, "spouse": spouse_month})


@pytest.mark.parametrize(("birth_month", "age", "locked"), [
    # Turning 62 in January..July: most of the year is at or past 62.
    (1, 62, False), (7, 62, False),
    # Born August: seven months before 62, so that year stays locked.
    (8, 62, True), (8, 63, False),
    # Unknown birth month counts as July, as for age 59.5.
    (None, 62, False), (None, 61, True),
])
def test_age_unlock_uses_the_59_half_majority_of_year_convention(birth_month, age, locked):
    account = AccountInfo(1, "taxable_brokerage", withdrawal_lock={"unlock": "age", "age": 62})
    assert is_withdrawal_locked(account, _state(2030, self_age=age, birth_month=birth_month), set()) is locked


def test_half_year_ages_and_owner_resolution():
    lock = {"unlock": "age", "age": 59.5}
    # Born June: 59.5 is reached in December of the age-59 year (11 months before).
    assert is_withdrawal_locked(AccountInfo(1, "traditional_ira", withdrawal_lock=lock), _state(2030, self_age=59, birth_month=6), set())
    assert not is_withdrawal_locked(AccountInfo(1, "traditional_ira", withdrawal_lock=lock), _state(2030, self_age=60, birth_month=6), set())
    state = _state(2030, self_age=70, spouse_age=55, spouse_month=1)
    assert is_withdrawal_locked(AccountInfo(1, "traditional_ira", owner="spouse", withdrawal_lock=lock), state, set())
    # A joint account uses the primary person.
    assert not is_withdrawal_locked(AccountInfo(1, "taxable_brokerage", owner="joint", withdrawal_lock=lock), state, set())


def test_year_and_milestone_rules():
    year_lock = AccountInfo(1, "savings", withdrawal_lock={"unlock": "year", "year": 2031})
    assert is_withdrawal_locked(year_lock, _state(2030, self_age=50), set())
    assert not is_withdrawal_locked(year_lock, _state(2031, self_age=51), set())
    milestone_lock = AccountInfo(1, "other", withdrawal_lock={"unlock": "milestone", "milestone_id": "m1"})
    assert is_withdrawal_locked(milestone_lock, _state(2030, self_age=50), {"m1"})
    assert not is_withdrawal_locked(milestone_lock, _state(2030, self_age=50, triggered={"m1"}), {"m1"})
    # A milestone outside this plan cannot be evaluated: the lock is ignored.
    assert not is_withdrawal_locked(milestone_lock, _state(2030, self_age=50), {"other"})
    state = _state(2030, self_age=50)
    state.accounts = {"a": milestone_lock, "b": year_lock, "c": AccountInfo(1, "checking")}
    update_locked_accounts(state, {"m1"})
    assert state.locked_account_ids == {"a", "b"}


# --- Drawdown ----------------------------------------------------------------

def test_locked_brokerage_is_not_drawn_before_its_unlock_age_and_is_drawn_from_it():
    # Born January 1980: a 48 lock opens in 2028.
    lock = {"unlock": "age", "age": 48}
    rows = _by_year(run_simulation(_plan({"cash": AccountInfo(40_000, "checking"),
                                          "broker": _brokerage(500_000, lock)})))
    assert rows[2026].accounts["broker"] == pytest.approx(500_000)
    assert rows[2027].accounts["broker"] == pytest.approx(500_000)
    # Only the remaining $10,000 of cash was available in 2027: the existing
    # unfunded path records the shortfall and the failure year.
    assert rows[2026].unfunded_expenses == pytest.approx(0)
    assert rows[2027].unfunded_expenses == pytest.approx(20_000)
    # Unlocked in 2028, it funds the year and the carried shortfall.
    assert rows[2028].accounts["broker"] == pytest.approx(450_000)
    assert rows[2028].unfunded_expenses == pytest.approx(0)


def test_spending_is_funded_from_other_accounts_while_locked():
    lock = {"unlock": "age", "age": 48}
    rows = _by_year(run_simulation(_plan({"broker": _brokerage(500_000, lock),
                                          "cash": AccountInfo(100_000, "checking")})))
    assert rows[2027].accounts["broker"] == pytest.approx(500_000)
    assert rows[2027].accounts["cash"] == pytest.approx(40_000)
    assert rows[2027].unfunded_expenses == pytest.approx(0)
    # Unlocked, the brokerage comes first in the drawdown order again.
    assert rows[2028].accounts["broker"] == pytest.approx(470_000)
    assert rows[2028].accounts["cash"] == pytest.approx(40_000)


def test_null_lock_matches_an_account_without_the_field():
    accounts = {"cash": AccountInfo(40_000, "checking"), "broker": _brokerage(500_000)}
    baseline = run_simulation(_plan(accounts))
    explicit = run_simulation(_plan({key: replace(value, withdrawal_lock=None) for key, value in accounts.items()}))
    assert explicit.model_dump() == baseline.model_dump()
    assert _by_year(baseline)[2027].accounts["broker"] == pytest.approx(480_000)


def test_year_and_milestone_unlocks_in_a_projection():
    milestone = MilestoneData("ms", "Separation", "date", trigger_date="2029-03-01")
    plan = _plan({"cash": AccountInfo(60_000, "checking"),
                  "year": AccountInfo(100_000, "savings", withdrawal_lock={"unlock": "year", "year": 2028}),
                  "ms": AccountInfo(100_000, "savings", withdrawal_lock={"unlock": "milestone", "milestone_id": "ms"})},
                 order=["ms", "year", "cash"], milestones=[milestone])
    rows = _by_year(run_simulation(plan))
    assert (rows[2027].accounts["ms"], rows[2027].accounts["year"]) == (pytest.approx(100_000), pytest.approx(100_000))
    assert rows[2028].accounts["year"] == pytest.approx(70_000)
    assert rows[2028].accounts["ms"] == pytest.approx(100_000)
    # Unlocked from the milestone's year, and first in the drawdown order.
    assert rows[2029].accounts["ms"] == pytest.approx(70_000)
    assert rows[2029].accounts["year"] == pytest.approx(70_000)


def test_lock_on_a_milestone_outside_the_plan_is_ignored_with_a_warning():
    plan = _plan({"broker": _brokerage(500_000, {"unlock": "milestone", "milestone_id": "elsewhere"})})
    result = run_simulation(plan)
    assert result.yearly_snapshots[0].accounts["broker"] == pytest.approx(470_000)
    assert any("withdrawal lock" in warning for warning in result.metadata.warnings)


def test_specific_expense_funding_cannot_use_a_locked_account():
    expense = ExpenseData("tuition", "Tuition", 10_000, inflation_linked=False, specific_funding_source_ids=["broker"])
    plan = _plan({"cash": AccountInfo(100_000, "checking"),
                  "broker": _brokerage(500_000, {"unlock": "year", "year": 2030})},
                 expenses=[expense])
    first = run_simulation(plan).yearly_snapshots[0]
    assert first.accounts["broker"] == pytest.approx(500_000)
    assert first.unfunded_expenses == pytest.approx(10_000)


# --- RMDs, conversions, transfers, SEPP, gifts ------------------------------

def test_rmds_still_come_out_of_a_locked_traditional_ira():
    plan = _plan({"cash": AccountInfo(500_000, "checking"),
                  "ira": AccountInfo(400_000, "traditional_ira", withdrawal_lock={"unlock": "year", "year": 2040})},
                 birth_year=1950, life_expectancy=80, expenses=[])
    first = run_simulation(plan).yearly_snapshots[0]
    rmd = sum(item.amount for item in first.cash_flow.income_sources if item.source == "rmd")
    # Age 76 in 2026: Uniform Lifetime factor 23.7.
    assert rmd == pytest.approx(400_000 / 23.7)
    assert first.accounts["ira"] == pytest.approx(400_000 - rmd)


def test_no_roth_conversion_or_transfer_comes_from_a_locked_account():
    lock = {"unlock": "year", "year": 2028}
    plan = _plan({"cash": AccountInfo(200_000, "checking"),
                  "ira": AccountInfo(300_000, "traditional_ira", withdrawal_lock=lock),
                  "roth": AccountInfo(0, "roth_ira"),
                  "cd": AccountInfo(50_000, "savings", withdrawal_lock=lock),
                  "broker": _brokerage(0)},
                 order=["cash"], expenses=[],
                 priorities=[PriorityData(1, priority_type="roth_conversion", source_account_id="ira",
                                          target_account_id="roth", max_annual_amount=10_000),
                             PriorityData(2, priority_type="transfer", source_account_id="cd",
                                          target_account_id="broker", max_annual_amount=5_000)])
    rows = _by_year(run_simulation(plan))
    for year in (2026, 2027):
        assert rows[year].transfers == []
        assert rows[year].accounts["ira"] == pytest.approx(300_000)
        assert rows[year].accounts["cd"] == pytest.approx(50_000)
    moved = {(t.source_account_id, t.target_account_id): t.amount for t in rows[2028].transfers}
    assert moved == {("ira", "roth"): pytest.approx(10_000), ("cd", "broker"): pytest.approx(5_000)}


def test_sepp_from_a_locked_account_waits_for_the_unlock():
    plan = _plan({"cash": AccountInfo(500_000, "checking"),
                  "ira": AccountInfo(400_000, "traditional_ira", withdrawal_lock={"unlock": "year", "year": 2028})},
                 order=["cash"], expenses=[],
                 sepp_settings=SEPPSettingsData(enabled=True, source_account_id="ira", start_age=45))
    rows = _by_year(run_simulation(plan))
    sepp = {year: sum(i.amount for i in rows[year].cash_flow.income_sources if i.source == "sepp") for year in rows}
    assert sepp[2026] == sepp[2027] == 0
    assert sepp[2028] > 0


def test_charitable_gifts_and_qcds_skip_locked_accounts():
    lock = {"unlock": "year", "year": 2040}
    gifts = [CharityData("gift", "Gift", "direct", 5_000), CharityData("qcd", "QCD", "qcd", 50_000)]
    plan = _plan({"cash": AccountInfo(500_000, "checking", withdrawal_lock=lock),
                  "savings": AccountInfo(100_000, "savings"),
                  "ira": AccountInfo(400_000, "traditional_ira", withdrawal_lock=lock)},
                 birth_year=1950, life_expectancy=80, expenses=[], order=["savings"], charity_entities=gifts)
    first = run_simulation(plan).yearly_snapshots[0]
    rmd = 400_000 / 23.7
    # The IRA gives only its RMD; the direct gift comes from unlocked savings.
    assert first.accounts["ira"] == pytest.approx(400_000 - rmd)
    assert first.accounts["cash"] == pytest.approx(500_000)
    assert first.accounts["savings"] < 100_000


# --- Liquidity ---------------------------------------------------------------

def test_monte_carlo_liquid_assets_failure_treats_locked_balances_as_illiquid():
    lock = {"unlock": "age", "age": 48}
    locked = run_simulation(_plan({"cash": AccountInfo(40_000, "checking"), "broker": _brokerage(500_000, lock)}))
    unlocked = run_simulation(_plan({"cash": AccountInfo(40_000, "checking"), "broker": _brokerage(500_000)}))
    years = len(locked.yearly_snapshots)

    failed = aggregate_results([locked], plan_years=years)
    assert failed.success_rate == 0
    assert failed.failure_analysis[0].failure_year == 2027
    assert aggregate_results([unlocked], plan_years=years).success_rate == 1
    # With nothing left unfunded, only the liquidity test fails: net worth
    # still counts the locked balance.
    idle = run_simulation(_plan({"cash": AccountInfo(0, "checking"), "broker": _brokerage(500_000, lock)}, expenses=[]))
    assert aggregate_results([idle], plan_years=years).failure_analysis[0].failure_year == 2026
    assert aggregate_results([idle], plan_years=years, failure_mode="net_worth").success_rate == 1
    # The compact cross-process trial keeps the same liquidity.
    compact = _compact_trial(locked)
    assert compact.yearly_snapshots[1].liquid_assets == pytest.approx(0)
    assert compact.yearly_snapshots[2].liquid_assets == pytest.approx(450_000)
    # The engine-only field never reaches the wire format.
    assert "locked_account_ids" not in str(locked.yearly_snapshots[0].model_dump())


def test_liquid_net_worth_milestones_exclude_locked_balances():
    plan = _plan({"cash": AccountInfo(10_000, "checking"),
                  "broker": _brokerage(1_000_000, {"unlock": "year", "year": 2029})},
                 expenses=[ExpenseData("spend", "Living", 1_000, inflation_linked=False)],
                 milestones=[MilestoneData("fi", "FI", "expense_multiple", expense_multiple=25, metric="liquid_net_worth")])
    result = run_simulation(plan)
    outcome = next(m for m in result.metadata.milestone_outcomes if m.id == "fi")
    assert outcome.year == 2029
