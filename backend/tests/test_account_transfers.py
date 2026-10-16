"""Account-to-account transfers: sales, distributions and rollovers."""

from __future__ import annotations

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import execute_transfers


def move(accounts, *, age=70, year=2026, rates=None, limit=None, **state_kw):
    state = SimState(year, accounts=accounts, **state_kw)
    state.owner_ages = {"self": age, "spouse": age}
    rule = PriorityData(1, priority_type="transfer", source_account_id="src", target_account_id="dst",
                        max_annual_amount=limit)
    delivered = execute_transfers([rule], state, age=age, withholding_rates=rates or {})
    return state, delivered.get("dst", 0.0)


def test_cash_to_cash_is_neutral():
    state, got = move({"src": AccountInfo(10_000, "checking"), "dst": AccountInfo(0, "savings")})
    assert got == 10_000
    assert state.get_balance("src") == 0 and state.get_balance("dst") == 10_000
    assert state.capital_gains_this_year == 0 and state.transfer_income_this_year == 0


def test_brokerage_sale_realizes_only_the_gain_share():
    accounts = {"src": AccountInfo(100_000, "taxable_brokerage", cost_basis=60_000),
                "dst": AccountInfo(0, "checking")}
    state, got = move(accounts, limit=50_000)
    assert state.capital_gains_this_year == pytest.approx(20_000)
    assert got == pytest.approx(50_000)
    # Basis leaves pro rata and the rest of the account keeps its own gain.
    assert state.accounts["src"].cost_basis == pytest.approx(30_000)
    assert state.accounts["src"].balance == pytest.approx(50_000)


def test_brokerage_to_brokerage_conserves_basis():
    accounts = {"src": AccountInfo(100_000, "taxable_brokerage", cost_basis=60_000),
                "dst": AccountInfo(10_000, "taxable_brokerage", cost_basis=10_000)}
    state, got = move(accounts)
    gains = state.capital_gains_this_year
    assert gains == pytest.approx(40_000)
    # Sale proceeds are new basis in the target: no basis is created beyond
    # the dollars received, and none is lost from the source.
    assert state.accounts["dst"].cost_basis == pytest.approx(10_000 + got)
    assert state.accounts["src"].balance == 0
    assert got + state.get_balance("src") == pytest.approx(100_000)


def test_sale_withholding_applies_to_gain_share_and_target_gets_net():
    accounts = {"src": AccountInfo(100_000, "taxable_brokerage", cost_basis=50_000),
                "dst": AccountInfo(0, "checking")}
    state, got = move(accounts, rates={"taxable_brokerage": 0.2})
    assert state.drawdown_tax_withheld_this_year == pytest.approx(100_000 * 0.5 * 0.2)
    assert got == pytest.approx(100_000 - 10_000)
    assert got + state.drawdown_tax_withheld_this_year == pytest.approx(100_000)


def test_pretax_distribution_is_ordinary_income_and_not_a_contribution():
    accounts = {"src": AccountInfo(40_000, "traditional_401k"), "dst": AccountInfo(0, "savings")}
    state, got = move(accounts, age=65, rates={"traditional_401k": 0.1})
    assert state.transfer_income_this_year == pytest.approx(40_000)
    assert state.drawdown_tax_withheld_this_year == pytest.approx(4_000)
    assert got == pytest.approx(36_000)
    assert state.transfer_penalty_this_year == 0


def test_early_pretax_distribution_pays_the_additional_tax_from_the_proceeds():
    accounts = {"src": AccountInfo(40_000, "traditional_ira"), "dst": AccountInfo(0, "savings")}
    state, got = move(accounts, age=45)
    assert state.transfer_penalty_this_year == pytest.approx(4_000)
    assert got == pytest.approx(36_000)
    assert state.transfer_income_this_year == pytest.approx(40_000)


def test_separation_year_exempts_a_workplace_plan_from_the_additional_tax():
    plan = AccountInfo(40_000, "traditional_401k", distribution_settings={"separation_year": 2026})
    state, got = move({"src": plan, "dst": AccountInfo(0, "savings")}, age=56, year=2026)
    assert state.transfer_penalty_this_year == 0
    assert got == pytest.approx(40_000)


def test_ira_never_gets_the_separation_exemption():
    ira = AccountInfo(40_000, "traditional_ira", distribution_settings={"separation_year": 2026})
    state, _ = move({"src": ira, "dst": AccountInfo(0, "savings")}, age=56, year=2026)
    assert state.transfer_penalty_this_year == pytest.approx(4_000)


def test_roth_basis_distribution_is_tax_free_and_earnings_follow_ordering():
    roth = AccountInfo(30_000, "roth_ira", roth_settings={"contribution_basis": 20_000, "first_contribution_year": 2000})
    state, got = move({"src": roth, "dst": AccountInfo(0, "savings")}, age=65, limit=15_000)
    assert state.transfer_income_this_year == 0
    assert got == pytest.approx(15_000)
    state, got = move({"src": AccountInfo(30_000, "roth_ira", roth_settings={
        "contribution_basis": 20_000, "first_contribution_year": 2000}),
        "dst": AccountInfo(0, "savings")}, age=45, limit=25_000)
    # 20k of contributions come out first; the 5k of earnings carry the 10% tax.
    assert state.roth_penalty_charged == pytest.approx(500)
    assert got == pytest.approx(25_000 - 500)


def test_same_owner_rollover_is_tax_neutral():
    accounts = {"src": AccountInfo(50_000, "traditional_401k"), "dst": AccountInfo(5_000, "traditional_ira")}
    state, got = move(accounts, age=40, rates={"traditional_401k": 0.2})
    assert got == 50_000
    assert state.get_balance("dst") == 55_000 and state.get_balance("src") == 0
    assert state.transfer_income_this_year == 0
    assert state.transfer_penalty_this_year == 0
    assert state.drawdown_tax_withheld_this_year == 0


@pytest.mark.parametrize("src,dst,message", [
    ("traditional_ira", "roth_ira", "conversion"),
    ("roth_ira", "roth_401k", "Roth-to-Roth"),
    ("checking", "traditional_ira", "Transfers cannot fund"),
    ("taxable_brokerage", "hsa", "Transfers cannot fund"),
    ("savings", "five_twenty_nine", "Transfers cannot fund"),
])
def test_invalid_combinations_are_rejected_before_money_moves(src, dst, message):
    accounts = {"src": AccountInfo(10_000, src), "dst": AccountInfo(0, dst)}
    state = SimState(2026, accounts=accounts)
    rule = PriorityData(1, priority_type="transfer", source_account_id="src", target_account_id="dst")
    with pytest.raises(ValueError, match=message):
        execute_transfers([rule], state)
    assert state.get_balance("src") == 10_000 and state.get_balance("dst") == 0


def test_rollover_across_owners_is_rejected():
    accounts = {"src": AccountInfo(10_000, "traditional_401k", owner="self"),
                "dst": AccountInfo(0, "traditional_ira", owner="spouse")}
    state = SimState(2026, accounts=accounts)
    rule = PriorityData(1, priority_type="transfer", source_account_id="src", target_account_id="dst")
    with pytest.raises(ValueError):
        execute_transfers([rule], state)
    assert state.get_balance("dst") == 0


def test_inherited_account_cannot_be_rolled_over():
    accounts = {"src": AccountInfo(10_000, "traditional_ira", inherited_year=2024),
                "dst": AccountInfo(0, "traditional_ira")}
    state = SimState(2026, accounts=accounts)
    rule = PriorityData(1, priority_type="transfer", source_account_id="src", target_account_id="dst")
    with pytest.raises(ValueError):
        execute_transfers([rule], state)


def test_locked_source_does_not_move():
    accounts = {"src": AccountInfo(10_000, "checking"), "dst": AccountInfo(0, "savings")}
    state = SimState(2026, accounts=accounts)
    state.locked_account_ids = {"src"}
    rule = PriorityData(1, priority_type="transfer", source_account_id="src", target_account_id="dst")
    assert execute_transfers([rule], state) == {}
    assert state.get_balance("src") == 10_000


def _transfer_plan(priorities, **kw):
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000076", birth_year=1960, birth_month=1,
        filing_status="single", life_expectancy=90, start_year=2026, state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0),
        accounts={"k": AccountInfo(100_000, "traditional_401k"), "sav": AccountInfo(0, "savings"),
                  "chk": AccountInfo(50_000, "checking")},
        priorities=priorities, tax_settings={"cash_flow_frequency": "annual"}, **kw)


def test_distribution_in_a_full_run_is_taxed_once_like_other_ordinary_income():
    rule = PriorityData(1, priority_type="transfer", source_account_id="k", target_account_id="sav",
                        max_annual_amount=60_000)
    conversion = PriorityData(1, priority_type="roth_conversion", source_account_id="k", target_account_id="roth",
                              max_annual_amount=60_000)
    base = run_simulation(_transfer_plan([])).yearly_snapshots[0]
    moved = run_simulation(_transfer_plan([rule])).yearly_snapshots[0]
    converted_plan = _transfer_plan([conversion])
    converted_plan.accounts["roth"] = AccountInfo(0, "roth_ira")
    converted = run_simulation(converted_plan).yearly_snapshots[0]
    assert moved.accounts["k"] == pytest.approx(base.accounts["k"] - 60_000, abs=1)
    assert moved.accounts["sav"] == pytest.approx(60_000, abs=1)
    assert moved.federal_tax > base.federal_tax
    # One ordinary-income recognition: the same dollars converted are taxed the same.
    assert moved.federal_tax == pytest.approx(converted.federal_tax)
