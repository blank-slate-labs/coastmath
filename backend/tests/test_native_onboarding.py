"""Native onboarding never seeds personal finances or changes authentication."""
from uuid import UUID

import pytest

from app.seed import seed_sample_household


@pytest.mark.anyio
async def test_empty_onboarding_resume_and_profile_edit(client):
    client.cookies.clear()
    created = await client.post('/api/auth/session', json={'seed_demo': False, 'client_workspace': True})
    assert created.status_code == 201
    assert 'client_workspaces' in created.json()['capabilities']
    assert (await client.get('/api/plans')).json() == []
    assert (await client.get('/api/clients')).json() == []
    assert (await client.get('/api/accounts')).json() == []
    profile = await client.put('/api/auth/me', json={'display_name': '  Advisor Smith  '})
    assert profile.status_code == 200 and profile.json()['display_name'] == 'Advisor Smith'
    assert profile.json()['id'] == created.json()['id'] and profile.json()['email'] is None
    for invalid in [{'display_name': ''}, {'display_name': 'x', 'email': 'takeover@example.com'}, {'display_name': 'x', 'is_anonymous': False}]:
        assert (await client.put('/api/auth/me', json=invalid)).status_code == 422
    resumed = await client.post('/api/auth/session', json={'seed_demo': True, 'client_workspace': True})
    assert resumed.status_code == 200 and resumed.json()['id'] == created.json()['id']
    assert (await client.get('/api/plans')).json() == []
    me = await client.get('/api/auth/me')
    assert 'session' in me.cookies and me.json()['display_name'] == 'Advisor Smith'
    client.cookies.clear()
    assert (await client.get('/api/auth/me')).status_code == 401

@pytest.mark.anyio
async def test_sample_household_is_a_separate_client_with_independent_accounts(client, db_session):
    # Sessions no longer seed it; the fixture reproduces the former session sample.
    client.cookies.clear()
    session = await client.post('/api/auth/session', json={'client_workspace': True})
    assert session.status_code == 201
    seed_sample_household(UUID(session.json()['id']), db_session)
    clients = (await client.get('/api/clients')).json()
    plans = (await client.get('/api/plans')).json()
    assert len(clients) == 1 and len(plans) == 1 and plans[0]['client_id'] == clients[0]['id']
    accounts = (await client.get(f'/api/plans/{plans[0]["id"]}/accounts')).json()
    assert accounts and all(a['plan_id'] == plans[0]['id'] for a in accounts)
    assert (await client.get('/api/accounts')).json() == []
