"""The shared simulation response supplies real flows for every slider year."""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
)
from coastmath.schemas.simulation import SimulationResult


@pytest.mark.parametrize("first_year_fraction", [1.0, 0.5])
def test_cash_flow_timeline_through_retirement_and_depletion(first_year_fraction):
    result = run_simulation(PlanData(
        plan_id="00000000-0000-4000-8000-000000000001",
        birth_year=1960, filing_status="single", life_expectancy=72,
        start_year=2026, first_year_fraction=first_year_fraction,
        milestones=[MilestoneData(id="retire", name="Retirement", trigger_type="date", trigger_date="2028-01-01")],
        income_streams=[IncomeData(id="salary", name="Salary", annual_amount=80000,
                                   growth_rate=0, end_milestone_id="retire")],
        expenses=[ExpenseData(id="living", name="Living", annual_amount=60000, inflation_linked=False)],
        accounts={"cash": AccountInfo(balance=10000, account_type="checking", name="Cash reserve")},
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
    ))
    # Both persisted and stateless routes serialize this same response model.
    response = SimulationResult.model_validate_json(result.model_dump_json())
    snapshots = response.yearly_snapshots
    assert [s.year for s in snapshots] == list(range(2026, 2032))
    assert snapshots[0].cash_flow.gross_income == pytest.approx(80000 * first_year_fraction)
    assert snapshots[1].cash_flow.gross_income == pytest.approx(80000)
    retired = next(s for s in snapshots if s.year == 2028)
    assert retired.cash_flow.gross_income == 0
    assert retired.cash_flow.drawdowns
    assert retired.cash_flow.drawdowns[0].account_id == "cash"
    assert retired.cash_flow.drawdowns[0].account_name == "Cash reserve"
    assert response.metadata.failure_year is not None
    assert snapshots[-1].unfunded_expenses > 0

    previous_unfunded = 0.0
    for snapshot in snapshots:
        flow = snapshot.cash_flow
        assert flow is not None
        assert flow.gross_income == pytest.approx(sum(source.amount for source in flow.income_sources))
        # Unfunded expenses is a cumulative liability; only its annual change
        # funds this year's gap. Withdrawals are receipts, never earned income.
        receipts = flow.gross_income + sum(draw.amount for draw in flow.drawdowns) + flow.tax_delta
        uses = (flow.payroll_deductions + flow.early_withdrawal_penalty
                + sum(expense.amount for expense in flow.expenses)
                + sum(contribution.amount for contribution in flow.contributions))
        new_unfunded = snapshot.unfunded_expenses - previous_unfunded
        assert receipts + new_unfunded == pytest.approx(uses, abs=0.01)
        previous_unfunded = snapshot.unfunded_expenses
