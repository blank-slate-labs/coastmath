"""Saved covered-record settings survive create, update and reload."""
import pytest

from tests.ss_household_support import PIA_INCOME, pia_plan

pytestmark = pytest.mark.anyio


async def test_record_fields_roundtrip(client):
    plan_id = await pia_plan(client)
    response = await client.post(f'/api/plans/{plan_id}/incomes', json={**PIA_INCOME, 'pia_reflects':'current_record', 'covered_years_to_date':20})
    assert response.status_code == 201
    income_id = response.json()['id']
    response = await client.put(f'/api/plans/{plan_id}/incomes/{income_id}', json={'covered_years_to_date':21})
    assert response.status_code == 200
    income = (await client.get(f'/api/plans/{plan_id}')).json()['income_streams'][0]
    assert income['pia_reflects'] == 'current_record'
    assert income['covered_years_to_date'] == 21
