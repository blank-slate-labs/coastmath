"""Persist the narrow updates sent by the expense/account editors."""
import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_independent_expense_edits_preserve_rename(client: AsyncClient):
    plan = (await client.post('/api/plans', json={'name': 'Audit', 'birth_year': 1990, 'plan_type': 'NOW'})).json()
    base = f"/api/plans/{plan['id']}/expenses"
    created = await client.post(base, json={'name': 'Travel', 'annual_amount': 1200})
    assert created.status_code == 201
    url = f"{base}/{created.json()['id']}"
    assert (await client.put(url, json={'name': 'Renamed travel'})).status_code == 200
    assert (await client.put(url, json={'annual_amount': 2400})).status_code == 200
    saved = (await client.get(base)).json()[0]
    assert saved['name'] == 'Renamed travel'
    assert saved['annual_amount'] == 2400


@pytest.mark.anyio
async def test_independent_account_edits_preserve_rename_and_clear_basis(client: AsyncClient):
    created = await client.post('/api/accounts', json={'name': 'Cash', 'account_type': 'taxable_brokerage', 'balance': 1234.56, 'cost_basis': 500})
    assert created.status_code == 201
    url = f"/api/accounts/{created.json()['id']}"
    assert (await client.put(url, json={'name': 'Renamed cash'})).status_code == 200
    assert (await client.put(url, json={'balance': 2345.67})).status_code == 200
    assert (await client.put(url, json={'cost_basis': None})).status_code == 200
    saved = next(a for a in (await client.get('/api/accounts')).json() if a['id'] == created.json()['id'])
    assert saved['name'] == 'Renamed cash'
    assert saved['balance'] == 2345.67
    assert saved['cost_basis'] is None
