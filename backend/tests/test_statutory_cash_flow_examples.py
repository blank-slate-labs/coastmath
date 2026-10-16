"""Independently calculated cash-flow and statutory examples, including the request paths."""
from uuid import uuid4

import pytest

from coastmath.engine.sepp import is_sepp_active, sepp_year_fraction
from coastmath.engine.simulator import run_simulation
from coastmath.engine.social_security import claiming_factor, full_retirement_age
from coastmath.engine.tax_engine import (
    _calculate_taxable_social_security,
    calculate,
    calculate_amt,
    calculate_fica_tax,
)
from coastmath.engine.types import (
    AssumptionCurveData,
    IncomeData,
    LiabilityData,
    MilestoneData,
)
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from tests.engine_support import audit_plan


def test_payoff_in_july_pays_six_months_interest_and_all_principal():
    p = audit_plan(milestones=[MilestoneData('pay', 'Pay off loan', 'date', trigger_date='2026-07-01')],
        liabilities=[LiabilityData('loan', 'Loan', 10_000, .12, monthly_payment=100,
            payment_type='interest_only', payoff_milestone_id='pay')])
    rows = run_simulation(p).yearly_snapshots
    assert rows[0].expenses == pytest.approx(10_600)
    assert rows[0].net_worth == pytest.approx(89_400)
    assert rows[1].expenses == 0


def test_income_activity_and_global_curves_compound_each_elapsed_year():
    p = audit_plan(income_streams=[IncomeData('w','Wage',1000), IncomeData('off','Disabled',1_000_000,is_active=False),
        IncomeData('ss','SS',1000,is_social_security=True)], assumption_curves=[
            AssumptionCurveData('wage_growth',fixed_rate=.1),
            AssumptionCurveData('social_security_cola',fixed_rate=.02)])
    assert [r.gross_income for r in run_simulation(p).yearly_snapshots[:3]] == pytest.approx([2000,2120,2250.4])



def test_explicit_zero_growth_remains_fixed_while_missing_growth_follows_curve():
    p = audit_plan(income_streams=[IncomeData('fixed', 'Fixed', 1000, growth_rate=0),
        IncomeData('curve', 'Curve', 1000)],
        assumption_curves=[AssumptionCurveData('wage_growth', fixed_rate=.1)])
    assert [r.gross_income for r in run_simulation(p).yearly_snapshots[:3]] == pytest.approx([2000, 2100, 2210])


def test_stateless_preserves_priority_income_and_payoff_fields():
    wire = PlanDataRequest(plan_id=uuid4(),birth_year=1980,start_year=2026,life_expectancy=50,
        accounts={'ira': {'balance': 100000, 'account_type': 'traditional_ira'},
                  'roth': {'balance': 0, 'account_type': 'roth_ira'}},
        income_streams=[{'id':'i','name':'Off','annual_amount':100,'is_active':False}],
        priorities=[{'priority_rank':1,'priority_type':'roth_conversion','conversion_mode':'fill_bracket',
            'source_account_id': 'ira', 'target_account_id': 'roth',
            'bracket_ceiling_rate':.22,'magi_cap':80000,'start_milestone_id':'s','end_milestone_id':'e'}],
        liabilities=[{'id':'l','name':'Loan','principal_balance':1000,'interest_rate':5,'payoff_milestone_id':'p'}])
    p=request_to_engine_data(wire)
    assert p.income_streams[0].is_active is False
    assert (p.priorities[0].conversion_mode,p.priorities[0].bracket_ceiling_rate,p.priorities[0].magi_cap,
            p.priorities[0].start_milestone_id,p.priorities[0].end_milestone_id) == ('fill_bracket',.22,80000,'s','e')
    assert p.liabilities[0].payoff_milestone_id == 'p'


def test_sepp_five_year_series_totals_exactly_sixty_months():
    assert sum(sepp_year_fraction(age,56,7) for age in range(55,64)) == 5
    assert sepp_year_fraction(61,56,7) == .5
    assert not is_sepp_active(61,56)
    assert sepp_year_fraction(59,50,1) == .5
    assert sepp_year_fraction(60,50,1) == 0


@pytest.mark.parametrize('birth,fra,factor62,factor70',[(1954,66,.75,1.32),(1955,66+2/12,1- .2-14*5/1200,1+46*.08/12),(1960,67,.70,1.24)])
def test_ss_cohort_factors(birth,fra,factor62,factor70):
    assert full_retirement_age(birth)==pytest.approx(fra)
    assert claiming_factor(62,birth)==pytest.approx(factor62)
    assert claiming_factor(70,birth)==pytest.approx(factor70)


def test_mfs_ss_worksheet_and_separated_exception():
    assert _calculate_taxable_social_security(20_000,20_000,'married_filing_separately') == 17_000
    assert _calculate_taxable_social_security(20_000,0,'married_filing_separately') == 8500
    assert _calculate_taxable_social_security(20_000,20_000,'married_filing_separately',True) == 2500


def test_2025_published_ss_wage_base_and_2026_reset():
    assert calculate_fica_tax(200_000,'single',tax_year=2025)['social_security_tax'] == pytest.approx(10_918.2)
    assert calculate_fica_tax(200_000,'single',tax_year=2026)['social_security_tax'] == 11_439
    assert calculate(200_000,0,'single',earned_income=200_000,tax_year=2025).fica_tax == pytest.approx(13_818.2)


def test_amt_gains_trigger_exemption_phaseout_but_keep_preferential_rates():
    # 2026 single: 600k AMTI; 90,100 exemption less50k phaseout =40,100.
    # Ordinary AMT base159,900; all400k LTCG stacked above200k regular ordinary.
    expected=159_900*.26 + (545_500-200_000)*.15 + (600_000-545_500)*.20
    assert calculate_amt(200_000,preferential_income=400_000)==pytest.approx(expected)
    result=calculate(200_000,0,'single',capital_gains=400_000)
    # CG tax is displayed separately and must not be added twice to AMT.
    assert result.federal + result.capital_gains_tax >= result.amt
