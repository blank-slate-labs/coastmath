"""Calendar anchoring and persisted/stateless milestone contracts."""
from dataclasses import replace
from uuid import uuid4

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo, AssumptionData, IncomeData, PriorityData
from tests.engine_support import audit_plan


def test_same_calendar_year_contribution_limit_independent_of_plan_start():
    p = replace(audit_plan(income_streams=[IncomeData('w', 'Salary', 100_000, growth_rate=0)],
        priorities=[PriorityData(1, target_account_id='ira', max_annual_amount=100_000)],
        tax_settings={'mode':'flat', 'ordinary_income_tax_rate':0}),
        accounts={'ira': AccountInfo(0, 'traditional_ira')}, life_expectancy=51,
        assumptions=AssumptionData(inflation_rate=.03, stock_growth_rate=0))
    early = run_simulation(p).yearly_snapshots[-1]
    late = run_simulation(replace(p, start_year=2030)).yearly_snapshots[0]
    for row in (early, late):
        contribution = sum(f.amount for f in row.cash_flow.contributions if f.account_id == 'ira')
        #2026 limit7500 plus1100catchup at age50, four indexed calendar years.
        assert contribution == pytest.approx(8_600 * 1.03**4)


@pytest.mark.parametrize('state_code', ['NY', 'OR'])
def test_builtin_state_thresholds_use_calendar_year_not_projection_start(state_code):
    p = replace(audit_plan(income_streams=[IncomeData('w', 'Salary', 100000, growth_rate=0)]),
        state_code=state_code, life_expectancy=51,
        assumptions=AssumptionData(inflation_rate=.03, stock_growth_rate=0))
    early = run_simulation(p).yearly_snapshots
    late = run_simulation(replace(p, start_year=2030)).yearly_snapshots[0]
    assert early[0].state_tax > late.state_tax > 0
    assert late.state_tax == pytest.approx(early[-1].state_tax)


def test_aca_fpl_uses_calendar_factor_for_future_start():
    p = replace(audit_plan(income_streams=[IncomeData('w','Salary',40_000,growth_rate=0)],
        tax_settings={'mode':'flat','ordinary_income_tax_rate':0}, healthcare_settings={
            'enabled':True,'aca_enabled':True,'aca_benchmark_premium_annual':12_000,
            'aca_plan_premium_annual':12_000,'aca_apply_age_curve':False}),
        life_expectancy=51, assumptions=AssumptionData(inflation_rate=.03,stock_growth_rate=0))
    early = run_simulation(p).yearly_snapshots
    late = run_simulation(replace(p,start_year=2030)).yearly_snapshots[0]
    assert late.healthcare.aca_fpl_ratio == pytest.approx(early[-1].healthcare.aca_fpl_ratio)
    assert late.healthcare.aca_fpl_ratio == pytest.approx(early[0].healthcare.aca_fpl_ratio / 1.03**4)


@pytest.mark.anyio
async def test_partner_month_persists_and_invalid_edit_keeps_saved_month(client):
    response = await client.post('/api/plans', json={'name':'Partner timing', 'birth_year':1980})
    assert response.status_code == 201, response.text
    url = f"/api/plans/{response.json()['id']}"
    saved = await client.put(url,json={'spouse':{'name':'Partner','birth_year':1982,'birth_month':12,'life_expectancy':90}})
    assert saved.status_code == 200, saved.text
    assert (await client.get(url)).json()['spouse']['birth_month'] == 12
    failed = await client.put(url,json={'spouse':{'birth_month':13}})
    assert failed.status_code == 422
    assert (await client.get(url)).json()['spouse']['birth_month'] == 12


@pytest.mark.anyio
async def test_stateless_negative_relative_milestone_cashflow_and_dynamic_rejection(client):
    data = dict(plan_id=str(uuid4()),birth_year=1980,birth_month=1,start_year=2026,life_expectancy=50,
        accounts={'cash':{'balance':100_000,'account_type':'checking'}},
        milestones=[{'id':'before','name':'One year before','trigger_type':'relative','relative_to_id':'retire','offset_years':-1},
            {'id':'retire','name':'Retire','trigger_type':'date','trigger_date':'2028-07-01'}],
        income_streams=[{'id':'salary','name':'Salary','annual_amount':12_000,'growth_rate':0,'end_milestone_id':'before'}],
        assumptions={'inflation_rate':0,'stock_growth_rate':0},tax_settings={'mode':'flat','ordinary_income_tax_rate':0})
    response = await client.post('/api/simulate/stateless',json=data)
    assert response.status_code == 200,response.text
    assert [r['gross_income'] for r in response.json()['yearly_snapshots'][:3]] == [12_000,6_000,0]
    data['milestones'][1] = {'id':'retire','name':'Target','trigger_type':'net_worth','trigger_value':1_000_000}
    rejected = await client.post('/api/simulate/stateless',json=data)
    assert rejected.status_code == 422
    assert rejected.json()['error']['code'] == 'VALIDATION_ERROR'
