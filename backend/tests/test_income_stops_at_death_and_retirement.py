"""Income, withholding and payroll deductions stop together at death or retirement."""
from dataclasses import replace

import pytest

from coastmath.engine.healthcare import calculate_premium_tax_credit
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
)


def household(**kwargs):
    return PlanData(plan_id='00000000-0000-0000-0000-000000000001', birth_year=1960,
        birth_month=1, filing_status='married_filing_jointly', start_year=2029, life_expectancy=73,
        spouse_birth_year=1966, spouse_birth_month=7, spouse_life_expectancy=64,
        accounts={'cash':AccountInfo(1_000_000,'checking')},
        assumptions=AssumptionData(inflation_rate=0,stock_growth_rate=0), **kwargs)


def test_spouse_income_stops_at_death_and_keeps_survivor_income():
    p = household(income_streams=[IncomeData('self','Survivor',20_000),
        IncomeData('salary','Spouse Salary',80_000,owner='spouse'),
        IncomeData('ss','Spouse SS',30_000,owner='spouse',is_social_security=True)])
    # Isolate death timing from the earnings test; death remains July 2030.
    p = replace(p, spouse_birth_year=1960, spouse_life_expectancy=70)
    snapshots = run_simulation(p).yearly_snapshots
    assert [s.gross_income for s in snapshots[:3]] == pytest.approx([130_000,75_000,20_000])
    # A plan starting after the death must not resurrect the streams.
    assert run_simulation(replace(p,start_year=2031)).yearly_snapshots[0].gross_income == pytest.approx(20_000)


def test_working_early_claimant_withholding_stops_with_deceased_streams():
    p = household(income_streams=[IncomeData('self','Survivor',20_000),
        IncomeData('salary','Spouse Salary',80_000,owner='spouse'),
        IncomeData('ss','Spouse SS',30_000,owner='spouse',is_social_security=True)])
    rows = run_simulation(p).yearly_snapshots[:3]
    # Zero wage growth holds the 2026 annual exemption at $24,480.
    # Wages are $80,000, then $40,000 in the July death year.
    assert [s.ss_earnings_test_withheld for s in rows] == pytest.approx([27_760, 7_760, 0])
    assert [s.gross_income for s in rows] == pytest.approx([102_240, 67_240, 20_000])


def test_payroll_deduction_follows_tied_salary_death():
    p = household(income_streams=[IncomeData('salary','Spouse Salary',80_000,owner='spouse')],
        expenses=[ExpenseData('health','Employer coverage',12_000,is_payroll_deduction=True,
            tied_income_id='salary',inflation_linked=False)])
    rows = run_simulation(p).yearly_snapshots
    assert [s.cash_flow.payroll_deductions for s in rows[:3]] == pytest.approx([12_000,6_000,0])


def test_disjoint_payroll_and_income_windows_do_not_charge():
    p = household(milestones=[MilestoneData('july','July','date',trigger_date='2029-07-01')],
        income_streams=[IncomeData('salary','Salary',80_000,end_milestone_id='july')],
        expenses=[ExpenseData('benefit','Benefit',12_000,is_payroll_deduction=True,
            tied_income_id='salary',start_milestone_id='july',inflation_linked=False)])
    assert all(s.cash_flow.payroll_deductions == 0 for s in run_simulation(p).yearly_snapshots)


@pytest.mark.parametrize('owner', ['self','spouse'])
@pytest.mark.parametrize('first_fraction,expected_aca,expected_medicare', [(1,22_000,1/12),(0.5,10_000,1/12)])
def test_december_medicare_has_no_missing_or_double_counted_coverage(owner,first_fraction,expected_aca,expected_medicare):
    p = household(healthcare_settings={'enabled':True,'aca_enabled':True,'medicare_enabled':True,
        'aca_benchmark_premium_annual':24_000,'aca_plan_premium_annual':24_000,
        'aca_apply_age_curve':False,'medical_inflation_rate':0})
    p = replace(p,start_year=2029,first_year_fraction=first_fraction,spouse_life_expectancy=100,
        birth_year=1964 if owner=='self' else 1950,spouse_birth_year=1964 if owner=='spouse' else 1950,
        life_expectancy=100,birth_month=12,spouse_birth_month=12)
    hc = run_simulation(p).yearly_snapshots[0].healthcare
    # The other adult is already on Medicare for the entire active period, so
    # the entered premium prices the one covered adult:
    # $24,000 x 11/12 (January-November), or x 5/12 from a July start.
    assert hc.aca_gross_premium == pytest.approx(expected_aca)
    assert hc.medicare_persons == pytest.approx(expected_medicare + first_fraction)


def test_partial_aca_credit_prorates_contribution_by_covered_months():
    annual = calculate_premium_tax_credit(30_000,1,12_000,12_000,covered_adults=1)
    partial = calculate_premium_tax_credit(30_000,1,6_000,6_000,covered_adults=1,
        coverage_periods=[(12_000,12_000,0.5)])
    assert partial.credit == pytest.approx(annual.credit/2)
    assert partial.net_premium == pytest.approx(annual.net_premium/2)


def test_death_year_keeps_joint_tax_family_and_reduces_only_coverage():
    p = replace(household(healthcare_settings={'enabled': True, 'aca_enabled': True,
        'aca_benchmark_premium_annual': 24000, 'aca_plan_premium_annual': 24000,
        'aca_apply_age_curve': False, 'medical_inflation_rate': 0}), birth_year=1970)
    rows = run_simulation(p).yearly_snapshots[:3]
    assert [row.healthcare.aca_household_size for row in rows] == [2, 2, 1]
    # Death is July 2030: two adults for six months, survivor for six.
    assert [row.healthcare.aca_gross_premium for row in rows] == pytest.approx([24000, 18000, 12000])
