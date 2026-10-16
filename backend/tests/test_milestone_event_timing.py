"""Milestones fire in their actual event years and months, including relative dependencies."""
import pytest

from coastmath.engine.milestones import evaluate_milestones
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    SimState,
)


def plan(milestones, **kwargs):
    return PlanData(plan_id='00000000-0000-0000-0000-000000000001', filing_status='single', birth_year=1980, birth_month=kwargs.pop('birth_month', 1),
        start_year=2038, life_expectancy=62, milestones=milestones,
        accounts={'cash': AccountInfo(1_000_000, 'checking')},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0), **kwargs)


@pytest.mark.parametrize('reverse', [False, True])
def test_negative_relative_event_window(reverse):
    milestones = [MilestoneData('retire', 'Retirement', 'age', trigger_value=60),
        MilestoneData('before', 'Two years before', 'relative', relative_to_id='retire', offset_years=-2)]
    if reverse:
        milestones.reverse()
    result = run_simulation(plan(milestones, expenses=[ExpenseData('bridge', 'Bridge', 20_000,
        start_milestone_id='before', end_milestone_id='retire', inflation_linked=False)]))
    assert [s.expenses for s in result.yearly_snapshots[:3]] == [20_000, 20_000, 0]


def test_relative_chain_keeps_birth_month_independent_of_order():
    result = run_simulation(plan([
        MilestoneData('rel2', 'Rel2', 'relative', relative_to_id='rel', offset_years=0),
        MilestoneData('rel', 'Rel', 'relative', relative_to_id='retire', offset_years=0),
        MilestoneData('retire', 'Retirement', 'age', trigger_value=60)], birth_month=6,
        income_streams=[IncomeData('pay', 'Pay', 120_000, end_milestone_id='rel2')]))
    assert next(s for s in result.yearly_snapshots if s.year == 2040).gross_income == pytest.approx(50_000)


@pytest.mark.parametrize('month,year,amount', [(1,2039,60_000), (10,2040,90_000)])
def test_fractional_age_trigger(month, year, amount):
    result = run_simulation(plan([MilestoneData('half', '59.5', 'age', trigger_value=59.5)],
        birth_month=month, income_streams=[IncomeData('pay', 'Pay', 120_000, start_milestone_id='half')]))
    assert next(s for s in result.yearly_snapshots if s.year == year).gross_income == pytest.approx(amount)


def test_dynamic_relative_fixed_point_and_actual_year():
    state = SimState(year=2039, accounts={'cash':AccountInfo(1_000_000,'checking')})
    milestones = [MilestoneData('later','Later','relative',relative_to_id='fi',offset_years=1),
        MilestoneData('same','Same','relative',relative_to_id='fi',offset_years=0),
        MilestoneData('fi','FI','expense_multiple',expense_multiple=25)]
    fired = evaluate_milestones(state,milestones,2039,1980,annual_expenses=20_000)
    assert set(fired) == {'same','fi'}
    assert state.triggered_milestone_years == {'fi':2039, 'same':2039}
    assert evaluate_milestones(state,milestones,2040,1980,annual_expenses=20_000) == ['later']
