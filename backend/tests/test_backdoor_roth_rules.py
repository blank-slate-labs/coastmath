"""Backdoor Roth contributions bypass the income phaseout but stay pro-rata.

A backdoor rule keeps the IRA contribution limit while ignoring the income
phaseout, and the taxable share follows the pro-rata rule against the owner's
own non-inherited traditional IRA balances, with a projection warning when
any of it is taxable.
"""
from __future__ import annotations

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import allocate_surplus, backdoor_prorata_taxable


def _plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()), birth_year=1992, filing_status="single", life_expectancy=89,
        start_year=2026, milestones=[], income_streams=[], expenses=[], priorities=[], drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0), accounts={},
    )
    defaults.update(overrides)
    return PlanData(**defaults)


def _state(**accounts):
    return SimState(2026, accounts={"roth": AccountInfo(0, "roth_ira", name="Roth IRA"), "cash": AccountInfo(0, "checking", name="Cash"), **accounts})


def test_backdoor_rule_ignores_the_income_phaseout_but_keeps_the_ira_limit():
    plain, backdoor = _state(), _state()
    assert allocate_surplus(20_000, [PriorityData(1, "roth"), PriorityData(2, "cash")], plain, 34, "single", 400_000) == {"cash": 20_000}
    assert "income_eligibility" in plain.allocation_flows[0].funding_reasons
    out = allocate_surplus(20_000, [PriorityData(1, "roth", backdoor_roth=True), PriorityData(2, "cash")], backdoor, 34, "single", 400_000)
    assert out["roth"] == 7_500 and out["cash"] == 12_500
    assert backdoor.allocation_flows[0].funding_reasons == []
    assert backdoor.roth_conversions_this_year == 0  # no pre-tax IRA money: tax-free


def test_backdoor_contribution_is_prorated_against_pretax_ira_balances():
    s = _state(trad=AccountInfo(22_500, "traditional_ira"), inherited=AccountInfo(50_000, "traditional_ira", inherited_year=2020),
               spouse=AccountInfo(90_000, "traditional_ira", owner="spouse"), k401=AccountInfo(500_000, "traditional_401k"))
    assert backdoor_prorata_taxable(7_500, "self", s) == pytest.approx(7_500 * 22_500 / 30_000)
    allocate_surplus(7_500, [PriorityData(1, "roth", backdoor_roth=True)], s, 34, "single", 400_000)
    assert s.roth_conversions_this_year == pytest.approx(5_625)
    assert s.backdoor_prorata_taxable == pytest.approx(5_625)


def test_backdoor_prorata_surfaces_a_projection_warning():
    accounts = {"roth": AccountInfo(0, "roth_ira", name="Roth IRA"), "trad": AccountInfo(30_000, "traditional_ira", name="Old IRA"),
                "cash": AccountInfo(10_000, "checking", name="Cash")}
    plan = _plan(
        accounts=accounts,
        income_streams=[IncomeData(id="job", name="Salary", annual_amount=250_000)],
        priorities=[PriorityData(1, "roth", backdoor_roth=True), PriorityData(2, "cash")],
    )
    result = run_simulation(plan)
    assert any(w.startswith("Backdoor Roth contributions were partly taxable") for w in result.metadata.warnings)
    assert result.yearly_snapshots[0].accounts["roth"] > 0
    clean = run_simulation(_plan(accounts={k: v for k, v in accounts.items() if k != "trad"},
                                 income_streams=plan.income_streams, priorities=plan.priorities))
    assert not any(w.startswith("Backdoor Roth") for w in clean.metadata.warnings)
