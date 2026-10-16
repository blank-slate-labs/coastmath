"""Qualified pensions are ordinary income, excluded from payroll tax and NIIT."""
import pytest

from app.schemas.income import IncomeCreate, IncomeUpdate
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import IncomeData
from tests.engine_support import audit_plan


@pytest.mark.parametrize('category,niit',[('qualified_pension',0),('other_ordinary',0),
    ('investment',3800),('nonqualified_annuity',3800)])
def test_income_tax_category_controls_niit_without_changing_gross(category,niit):
    result=run_simulation(audit_plan(income_streams=[IncomeData('i','Income',300_000,tax_category=category)])).yearly_snapshots[0]
    assert result.gross_income == 300_000
    assert result.fica_tax == 0
    assert result.niit_tax == niit


def test_category_overrides_inconsistent_legacy_flags():
    for data in (IncomeCreate(name='Pension',tax_category='qualified_pension'),
                 IncomeUpdate(tax_category='qualified_pension')):
        assert data.is_earned_income is False
        assert data.model_dump(exclude_unset=True)['is_earned_income'] is False


@pytest.mark.anyio
async def test_pension_category_survives_reload_and_partial_updates(client):
    response=await client.post('/api/plans',json={'name':'Pension audit','birth_year':1980})
    pid=response.json()['id']
    url=f'/api/plans/{pid}/incomes'
    response=await client.post(url,json={'name':'Pension','annual_amount':300_000,'tax_category':'qualified_pension'})
    assert response.status_code == 201,response.text
    iid=response.json()['id']
    assert response.json()['is_earned_income'] is False
    assert (await client.put(f'{url}/{iid}',json={'annual_amount':310_000})).status_code==200
    saved=(await client.get(url)).json()[0]
    assert saved['tax_category']=='qualified_pension' and saved['annual_amount']==310_000
    # An older client changing employment flags can still deliberately change treatment.
    changed=await client.put(f'{url}/{iid}',json={'is_earned_income':True})
    assert changed.json()['tax_category'] is None
    assert changed.json()['is_earned_income'] is True
