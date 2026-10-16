"""Rejected account and debt saves change nothing; a corrected retry saves once."""
import pytest


@pytest.mark.anyio
async def test_account_rejection_preserves_balance_and_correction_persists(client):
    plan = await client.post('/api/plans', json={'name': 'UX synthetic household', 'birth_year': 1990})
    assert plan.status_code == 201
    path = f"/api/plans/{plan.json()['id']}/accounts"
    created = await client.post(path, json={'name': 'Emergency Fund', 'balance': 20000, 'account_type': 'savings', 'owner': 'self'})
    assert created.status_code == 201
    url = f"{path}/{created.json()['id']}"
    for _ in range(2):
        rejected = await client.put(url, json={'name': 'UX account ' + 'A' * 250})
        assert rejected.status_code == 422
        assert rejected.json()['error']['details'] == [{'field': 'name', 'reason': 'String should have at most 255 characters'}]
    saved = (await client.get(path)).json()[0]
    assert saved['name'] == 'Emergency Fund'
    assert saved['balance'] == 20000
    assert (await client.put(url, json={'name': 'UX account control'})).status_code == 200
    saved = (await client.get(path)).json()[0]
    assert saved['name'] == 'UX account control'
    assert saved['balance'] == 20000
    assert saved['account_type'] == 'savings'
    assert saved['owner'] == 'self'


@pytest.mark.anyio
async def test_debt_rejection_does_not_create_and_retry_creates_once(client):
    plan = await client.post('/api/plans', json={'name': 'UX synthetic household', 'birth_year': 1990})
    assert plan.status_code == 201
    path = f"/api/plans/{plan.json()['id']}/liabilities"
    body = {'name': 'UX debt ' + 'B' * 250, 'principal_balance': 12000, 'interest_rate': 5, 'term_months': 60, 'monthly_payment': 230, 'payment_type': 'fixed', 'extra_payment': 0}
    for _ in range(2):
        rejected = await client.post(path, json=body)
        assert rejected.status_code == 422
        assert rejected.json()['error']['details'] == [{'field': 'name', 'reason': 'String should have at most 255 characters'}]
    assert (await client.get(path)).json() == []
    body['name'] = 'UX debt control'
    assert (await client.post(path, json=body)).status_code == 201
    saved = (await client.get(path)).json()
    assert len(saved) == 1
    assert all(saved[0][key] == value for key, value in body.items())
