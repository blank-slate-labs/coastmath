"""Current-year HSA exposure must survive settlement and reset next year.

These controls test the boundary of the supported California wage allocation,
not HSA distribution qualification or California conformity. Real waterfall
contributions and specifically funded expenses establish the account history.
"""

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
    ResidencyPeriodData,
)


def _hsa_move_plan(*, opening_hsa: float, fund_in_2026: bool, expense_year: int) -> PlanData:
    priorities = []
    if fund_in_2026:
        priorities.append(PriorityData(
            priority_rank=1, target_account_id="hsa", max_annual_amount=4_000,
            end_milestone_id="funding_ends",
        ))
    priorities.append(PriorityData(priority_rank=2, target_account_id="cash"))
    return PlanData(
        plan_id=str(uuid5(NAMESPACE_URL, f"hsa-history-{opening_hsa}-{fund_in_2026}-{expense_year}")),
        birth_year=1990, birth_month=1, filing_status="single",
        life_expectancy=39, start_year=2026,
        milestones=[
            MilestoneData("funding_ends", "Contributions stop", "date", trigger_date="2027-01-01"),
            MilestoneData("expense_starts", "HSA expense begins", "date", trigger_date=f"{expense_year}-01-01"),
            MilestoneData("expense_ends", "HSA expense ends", "date", trigger_date=f"{expense_year + 1}-01-01"),
            MilestoneData("wages_end", "Last paid wage month", "date", trigger_date="2028-05-01"),
            MilestoneData("move", "Move to California", "date", trigger_date="2028-06-01"),
        ],
        income_streams=[IncomeData(
            "wages", "Wages earned and received before move", 120_000,
            growth_rate=0, end_milestone_id="wages_end", end_month=5,
        )],
        expenses=[ExpenseData(
            "hsa_expense", "Expense funded specifically from HSA", 4_000,
            start_milestone_id="expense_starts", end_milestone_id="expense_ends",
            inflation_linked=False, specific_funding_source_id="hsa",
        )],
        priorities=priorities, drawdown_order=["cash"],
        accounts={
            "cash": AccountInfo(100_000, "checking"),
            "hsa": AccountInfo(opening_hsa, "hsa", owner="self"),
        },
        assumptions=AssumptionData(
            inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
        ),
        tax_settings={
            "ca_exemption_eligible_owners": [],
            "hsa_coverage": [{
                "owner": "self", "start_year": 2026, "coverage": "self_only",
                "eligible_months": list(range(1, 13)),
            }],
        },
        state_code="TX",
        residency_periods=[ResidencyPeriodData("CA", start_milestone_id="move")],
    )


def _hsa_flow(snapshot, kind):
    assert snapshot.cash_flow is not None
    return sum(flow.amount for flow in getattr(snapshot.cash_flow, kind) if flow.account_id == "hsa")


def _move_year_warnings(result):
    return [warning for warning in result.metadata.warnings if warning.startswith("2028:")]


def test_previously_funded_hsa_depleted_in_move_year_keeps_final_fallback():
    plan = _hsa_move_plan(opening_hsa=0, fund_in_2026=True, expense_year=2028)
    result = run_simulation(plan)
    snapshots = {snapshot.year: snapshot for snapshot in result.yearly_snapshots}
    assert list(snapshots) == [2026, 2027, 2028]
    assert plan.accounts["hsa"].balance == 0
    assert _hsa_flow(snapshots[2026], "contributions") == pytest.approx(4_000)
    assert [snapshots[year].accounts["hsa"] for year in snapshots] == pytest.approx([4_000, 4_000, 0])
    assert _hsa_flow(snapshots[2027], "contributions") == 0
    assert _hsa_flow(snapshots[2027], "drawdowns") == 0
    assert _hsa_flow(snapshots[2028], "contributions") == 0
    assert _hsa_flow(snapshots[2028], "drawdowns") == pytest.approx(4_000)
    assert snapshots[2028].expenses == pytest.approx(4_000)
    assert snapshots[2028].gross_income == pytest.approx(50_000)
    assert snapshots[2028].unfunded_expenses == 0

    # Final snapshot tax and final diagnostics must retain the explicit legacy
    # fallback even though no HSA balance or contributions remain at settlement.
    legacy = run_simulation(replace(plan, state_code="CA", residency_periods=[]))
    assert snapshots[2028].state_tax > 0
    assert snapshots[2028].state_tax == pytest.approx(legacy.yearly_snapshots[-1].state_tax)
    assert any("HSA California conformity" in warning for warning in _move_year_warnings(result))
    assert not any("HSA eligibility is unspecified" in warning for warning in result.metadata.warnings)


def test_hsa_depleted_years_before_move_does_not_block_supported_wages():
    plan = _hsa_move_plan(opening_hsa=4_000, fund_in_2026=False, expense_year=2026)
    result = run_simulation(plan)
    snapshots = {snapshot.year: snapshot for snapshot in result.yearly_snapshots}
    assert list(snapshots) == [2026, 2027, 2028]
    assert plan.accounts["hsa"].balance == 4_000
    assert _hsa_flow(snapshots[2026], "drawdowns") == pytest.approx(4_000)
    assert [snapshots[year].accounts["hsa"] for year in snapshots] == [0, 0, 0]
    assert all(_hsa_flow(snapshot, "contributions") == 0 for snapshot in snapshots.values())
    assert _hsa_flow(snapshots[2027], "drawdowns") == 0
    assert _hsa_flow(snapshots[2028], "drawdowns") == 0
    assert snapshots[2028].expenses == 0
    assert snapshots[2028].gross_income == pytest.approx(50_000)
    assert snapshots[2028].unfunded_expenses == 0

    # All move-year wages precede entry to California. An empty account from
    # two years earlier must not convert this supported branch to annual CA tax.
    stayed_tx = run_simulation(replace(plan, residency_periods=[]))
    assert snapshots[2028].state_tax == pytest.approx(0)
    assert snapshots[2028].net_worth == pytest.approx(stayed_tx.yearly_snapshots[-1].net_worth)
    assert not any("HSA" in warning for warning in _move_year_warnings(result))
    assert any("residence" in warning.lower() for warning in _move_year_warnings(result))
    assert not any("HSA eligibility is unspecified" in warning for warning in result.metadata.warnings)
