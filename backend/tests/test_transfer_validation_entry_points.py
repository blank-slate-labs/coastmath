"""Every entry point rejects an invalid transfer, conversion or horizon before money moves."""
import pytest

from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.types import AccountInfo, PlanData, PriorityData, SimState
from coastmath.engine.waterfall import execute_roth_conversions, execute_transfers
from coastmath.schemas.plan_data_request import PlanDataRequest


def raw(**kwargs):
    return dict(plan_id='00000000-0000-0000-0000-000000000001',birth_year=1980,
        start_year=2026,filing_status='single',life_expectancy=90,**kwargs)


@pytest.mark.parametrize('source_kind,target_kind,message',[
    ('hsa','checking','Transfers support'),
    ('five_twenty_nine','checking','Transfers support'),
    ('checking','traditional_ira','Transfers cannot fund'),
    ('taxable_brokerage','roth_401k','Transfers cannot fund'),
    ('roth_ira','roth_401k','Roth-to-Roth'),
])
def test_invalid_transfer_cannot_move_money_in_engine_or_stateless_schema(source_kind,target_kind,message):
    accounts={'source':AccountInfo(100_000,source_kind),'target':AccountInfo(0,target_kind)}
    rule=PriorityData(1,priority_type='transfer',source_account_id='source',target_account_id='target')
    state=SimState(2026,accounts=accounts)
    with pytest.raises(ValueError,match=message):
        execute_transfers([rule],state)
    assert state.get_balance('source') == 100_000 and state.get_balance('target') == 0
    with pytest.raises(ValueError,match=message):
        PlanDataRequest(**raw(accounts={k:vars(a) for k,a in accounts.items()},priorities=[vars(rule)]))


@pytest.mark.anyio
async def test_personal_plan_rejects_contribution_transfer_without_replacing_saved_rules(client):
    created=await client.post('/api/plans',json={'name':'Transfer audit','birth_year':1980,'plan_type':'NOW'})
    assert created.status_code == 201,created.text
    plan_id=created.json()['id']
    accounts=[]
    for name,kind,balance in [('Cash','checking',100_000),('IRA','traditional_ira',0)]:
        response=await client.post('/api/accounts',json={'name':name,'account_type':kind,'balance':balance})
        assert response.status_code == 201,response.text
        accounts.append(response.json()['id'])
    url=f'/api/plans/{plan_id}/priorities'
    before=(await client.get(url)).json()
    response=await client.put(url,json={'expected_revision':before['revision'],'items':[{
        'priority_rank':1,'priority_type':'transfer','source_account_id':accounts[0],'target_account_id':accounts[1]}]})
    assert response.status_code == 422,response.text
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert (await client.get(url)).json() == before


@pytest.mark.parametrize('age',[76,77])
def test_nonpositive_horizon_is_validation_error(age):
    data=raw()
    data.update(birth_year=1950,life_expectancy=76,start_year=1950+age)
    with pytest.raises(ValueError,match='Life expectancy'):
        PlanDataRequest(**data)
    with pytest.raises(ValueError,match='Life expectancy'):
        run_monte_carlo(PlanData(**data),n_trials=1)


@pytest.mark.parametrize('target_kind,target_owner', [(None, 'self'), ('checking', 'self'), ('roth_ira', 'spouse')])
def test_conversion_cannot_lose_cash_or_change_owners(target_kind, target_owner):
    accounts = {'ira': AccountInfo(100_000, 'traditional_ira')}
    if target_kind:
        accounts['target'] = AccountInfo(0, target_kind, owner=target_owner)
    rule = PriorityData(1, priority_type='roth_conversion', source_account_id='ira', target_account_id='target')
    state = SimState(2026, accounts=accounts)
    with pytest.raises(ValueError, match='Roth conversions require'):
        execute_roth_conversions([rule], state)
    assert state.get_balance('ira') == 100_000
    with pytest.raises(ValueError, match='Roth conversions require'):
        PlanDataRequest(**raw(accounts={k: vars(a) for k, a in accounts.items()}, priorities=[vars(rule)]))


@pytest.mark.parametrize('history', [
    {'first_contribution_year': 2027},
    {'conversions': [{'year': 2027, 'taxable_basis': 5000}]},
])
def test_opening_roth_history_cannot_create_future_basis(history):
    with pytest.raises(ValueError, match='opening history cannot include future'):
        PlanDataRequest(**raw(accounts={'roth': {'balance': 10000, 'account_type': 'roth_ira', 'roth_settings': history}}))
