"""Qualified charitable distributions are owner-aware.

Each IRA owner's own age and birth month decide eligibility (age 70 1/2), each
eligible spouse has an individual cap, and a QCD offsets only its owner's RMD
from an eligible IRA: never a spouse's RMD and never an inherited IRA's.
"""

from dataclasses import replace

import pytest

from coastmath.engine.simulator import _process_qcds, run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    IncomeData,
    PlanData,
    SimState,
)


def _state(accounts, ages, months):
    state = SimState(year=2026, accounts=accounts)
    state.owner_ages = ages
    state.owner_birth_months = months
    return state


def _gift(amount):
    return [CharityData("gift", "Gift", "qcd", amount)]


def test_qcd_uses_only_older_self_ira_and_does_not_pool_younger_spouse_rmd():
    state = _state(
        {
            "self_ira": AccountInfo(100_000, "traditional_ira", owner="self"),
            "spouse_ira": AccountInfo(80_000, "traditional_ira", owner="spouse"),
        },
        {"self": 74, "spouse": 60},
        {"self": 1, "spouse": 1},
    )

    amount = _process_qcds(
        state, _gift(10_000), rmd_amount=20_000, triggered_milestones=set(),
        age=74, birth_month=1, rmd_by_owner={"spouse": 20_000},
    )

    assert amount == 10_000
    assert state.accounts["self_ira"].balance == 90_000
    assert state.accounts["spouse_ira"].balance == 80_000


def test_qcd_reverse_older_spouse_younger_self():
    state = _state(
        {
            "self_ira": AccountInfo(80_000, "traditional_ira", owner="self"),
            "spouse_ira": AccountInfo(100_000, "traditional_ira", owner="spouse"),
        },
        {"self": 60, "spouse": 74},
        {"self": 1, "spouse": 1},
    )

    amount = _process_qcds(
        state, _gift(10_000), rmd_amount=0, triggered_milestones=set(),
        age=60, birth_month=1, rmd_by_owner={"self": 20_000},
    )

    assert amount == 10_000
    assert state.accounts["self_ira"].balance == 80_000
    assert state.accounts["spouse_ira"].balance == 90_000


def test_qcd_70_and_a_half_month_boundary_is_owner_specific():
    state = _state(
        {
            "self_ira": AccountInfo(100_000, "traditional_ira", owner="self"),
            "spouse_ira": AccountInfo(100_000, "traditional_ira", owner="spouse"),
        },
        {"self": 70, "spouse": 70},
        {"self": 6, "spouse": 7},
    )

    amount = _process_qcds(
        state, _gift(20_000), rmd_amount=0, triggered_milestones=set(),
        age=70, birth_month=7, rmd_by_owner={"self": 0, "spouse": 0},
    )

    assert amount == 20_000
    assert state.accounts["self_ira"].balance == 80_000
    assert state.accounts["spouse_ira"].balance == 100_000


def test_two_eligible_spouses_receive_two_individual_qcd_caps():
    state = _state(
        {
            "self_ira": AccountInfo(200_000, "traditional_ira", owner="self"),
            "spouse_ira": AccountInfo(200_000, "traditional_ira", owner="spouse"),
        },
        {"self": 74, "spouse": 74},
        {"self": 1, "spouse": 1},
    )

    amount = _process_qcds(
        state, _gift(250_000), rmd_amount=0, triggered_milestones=set(),
        age=74, birth_month=1, qcd_cap=111_000,
        rmd_by_owner={"self": 0, "spouse": 0},
    )

    assert amount == 222_000
    assert state.accounts["self_ira"].balance == 89_000
    assert state.accounts["spouse_ira"].balance == 89_000


def test_ineligible_inherited_ira_rmd_does_not_offset_eligible_owner_qcd():
    state = _state(
        {
            "self_ira": AccountInfo(100_000, "traditional_ira", owner="self"),
            "inherited_ira": AccountInfo(80_000, "traditional_ira", owner="spouse"),
        },
        {"self": 74, "spouse": 60},
        {"self": 1, "spouse": 1},
    )

    amount = _process_qcds(
        state, _gift(10_000), rmd_amount=20_000, triggered_milestones=set(),
        age=74, birth_month=1, rmd_by_owner={"spouse": 20_000},
    )

    assert amount == 10_000
    assert state.accounts["self_ira"].balance == 90_000
    assert state.accounts["inherited_ira"].balance == 80_000


def test_direct_first_owner_does_not_offset_second_owners_rmd():
    """A household gift must consume the selected owner's funds and RMD only."""
    state = _state(
        {
            "self_ira": AccountInfo(100_000, "traditional_ira", owner="self"),
            "spouse_ira": AccountInfo(80_000, "traditional_ira", owner="spouse"),
        },
        {"self": 71, "spouse": 75},
        {"self": 1, "spouse": 1},
    )

    amount = _process_qcds(
        state, _gift(10_000), rmd_amount=20_000, triggered_milestones=set(),
        age=71, birth_month=1, rmd_by_owner={"spouse": 20_000},
    )

    assert amount == 10_000
    assert state.accounts["self_ira"].balance == 90_000
    assert state.accounts["spouse_ira"].balance == 80_000


def test_missing_owner_age_is_not_authorized_by_holder_age():
    state = _state(
        {
            "self_ira": AccountInfo(100_000, "traditional_ira", owner="self"),
            "joint_ira": AccountInfo(100_000, "traditional_ira", owner="joint"),
        },
        {"self": 74},
        {"self": 1},
    )

    amount = _process_qcds(
        state, _gift(10_000), rmd_amount=0, triggered_milestones=set(),
        age=74, birth_month=1, rmd_by_owner={"joint": 20_000},
    )

    assert amount == 10_000
    assert state.accounts["self_ira"].balance == 90_000
    assert state.accounts["joint_ira"].balance == 100_000


def test_simulator_direct_self_qcd_keeps_spouse_rmd_tax_and_cash():
    p = PlanData(
        plan_id="00000000-0000-4000-8000-000000000003",
        birth_year=1955, birth_month=1, life_expectancy=72, start_year=2026,
        spouse_birth_year=1951, spouse_birth_month=1, spouse_life_expectancy=95,
        filing_status="married_filing_jointly",
        accounts={
            "self_ira": AccountInfo(100_000, "traditional_ira", owner="self"),
            "spouse_ira": AccountInfo(246_000, "traditional_ira", owner="spouse"),
            "cash": AccountInfo(100_000, "checking", owner="joint"),
        },
        assumptions=AssumptionData(
            inflation_rate=0, stock_growth_rate=0, stock_dividend_yield=0,
            bond_return_rate=0, cash_yield_rate=0,
        ),
        income_streams=[IncomeData("pension", "Pension", 100_000,
                                   tax_category="qualified_pension", growth_rate=0)],
    )
    before = run_simulation(p).yearly_snapshots[0]
    after = run_simulation(replace(p, charity_entities=_gift(10_000))).yearly_snapshots[0]
    assert after.federal_tax == pytest.approx(before.federal_tax)
    assert after.accounts["spouse_ira"] == before.accounts["spouse_ira"]
    assert after.accounts["cash"] == pytest.approx(before.accounts["cash"])
    assert after.accounts["self_ira"] == before.accounts["self_ira"] - 10_000
    assert after.net_worth == pytest.approx(before.net_worth - 10_000)


@pytest.mark.parametrize("holder_age,spouse_age,expected_gift", [(74, 60, 0), (60, 74, 10_000)])
def test_simulator_qcd_with_only_spouse_ira_uses_spouse_eligibility(
    holder_age, spouse_age, expected_gift,
):
    p = PlanData(
        plan_id="00000000-0000-4000-8000-000000000004",
        birth_year=2026 - holder_age, birth_month=1,
        life_expectancy=holder_age + 1, start_year=2026,
        spouse_birth_year=2026 - spouse_age, spouse_birth_month=1,
        spouse_life_expectancy=95, filing_status="married_filing_jointly",
        accounts={"spouse_ira": AccountInfo(100_000, "traditional_ira", owner="spouse")},
        assumptions=AssumptionData(
            inflation_rate=0, stock_growth_rate=0, stock_dividend_yield=0,
            bond_return_rate=0, cash_yield_rate=0,
        ),
    )
    before = run_simulation(p).yearly_snapshots[0]
    after = run_simulation(replace(p, charity_entities=_gift(10_000))).yearly_snapshots[0]
    assert after.expenses - before.expenses == expected_gift
    assert after.net_worth == pytest.approx(before.net_worth - expected_gift)
