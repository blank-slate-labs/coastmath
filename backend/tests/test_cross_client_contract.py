"""Cross-client contracts with isolated synthetic users."""
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError

from app.auth.dependencies import decode_jwt
from app.auth.router import ANONYMOUS_COOKIE_MAX_AGE, COOKIE_MAX_AGE
from app.middleware.error_handler import validation_exception_handler
from app.models.plan import Plan
from app.models.user import User
from app.schemas.user import SessionRead
from app.seed import seed_sample_household

pytestmark = pytest.mark.anyio

async def test_session_shape_and_lifetime(client, db_session, test_user):
    for anonymous, lifetime in [(True, ANONYMOUS_COOKIE_MAX_AGE), (False, COOKIE_MAX_AGE)]:
        test_user.is_anonymous = anonymous
        db_session.commit()
        for method, path in [('GET', '/api/auth/me'), ('POST', '/api/auth/session')]:
            result = await client.request(method, path)
            assert result.status_code == 200
            assert result.json() == SessionRead.model_validate(test_user).model_dump(mode='json')
            assert f'Max-Age={lifetime}' in result.headers['set-cookie']
            token = result.headers['set-cookie'].split('session=', 1)[1].split(';', 1)[0]
            remaining = decode_jwt(token)['exp'] - datetime.now(UTC).timestamp()
            assert lifetime - 5 < remaining <= lifetime
        updated = await client.put('/api/auth/me', json={'display_name': 'Contract tester'})
        assert updated.json()['capabilities'] == result.json()['capabilities']

async def test_nested_validation_paths():
    exc = RequestValidationError([{'loc': ('body', 'spouse', 'birth_year'), 'msg': 'Invalid'}, {'loc': ('body', 'items', 2, 'amount'), 'msg': 'Invalid'}])
    result = await validation_exception_handler(Request({'type': 'http'}), exc)
    assert [d['field'] for d in json.loads(result.body)['error']['details']] == ['spouse.birth_year', 'items.2.amount']

async def test_summaries_preserve_ownership(client, db_session, test_user):
    owner = (await client.post('/api/clients/personal')).json()
    saved = (await client.post('/api/plans', json={'name': 'Own', 'birth_year': 1990, 'client_id': owner['id']})).json()
    other = User(id=uuid4(), is_anonymous=True, settings={})
    db_session.add(other)
    db_session.flush()
    db_session.add(Plan(user_id=other.id, name='Private elsewhere', birth_year=1990))
    db_session.commit()
    result = await client.get('/api/plans/summaries')
    assert result.status_code == 200
    assert result.json() == [{key: saved[key] for key in ('id', 'client_id', 'name', 'plan_type', 'created_at')}]
    assert (await client.get('/api/plans/summaries', params={'client_id': str(uuid4())})).status_code == 404
    assert 'expenses' in (await client.get('/api/plans')).json()[0]

async def test_web_workspace_creation_is_independent(client, db_session):
    client.cookies.clear()
    session = await client.post('/api/auth/session', json={'client_workspace': True})
    assert session.status_code == 201
    assert f'Max-Age={ANONYMOUS_COOKIE_MAX_AGE}' in session.headers['set-cookie']
    seed_sample_household(UUID(session.json()['id']), db_session)  # Sessions no longer seed it.
    sample = (await client.get('/api/plans')).json()[0]
    assert sample['client_id'] is not None
    assert (await client.get(f"/api/plans/{sample['id']}/accounts")).json()
    owner = (await client.post('/api/clients/personal')).json()
    plan = (await client.post('/api/plans', json={'name': 'Personal', 'birth_year': 1990, 'client_id': owner['id']})).json()
    assert (await client.get(f"/api/plans/{plan['id']}/accounts")).json() == []
    assert (await client.get(f"/api/plans/{sample['id']}/accounts")).json()

async def test_priority_account_deletion_uses_conflict_code(client, db_session):
    client.cookies.clear()
    session = await client.post('/api/auth/session', json={'client_workspace': True})
    seed_sample_household(UUID(session.json()['id']), db_session)
    plan = (await client.get('/api/plans')).json()[0]
    account_id = next(p['target_account_id'] for p in plan['priorities'] if p['target_account_id'])
    response = await client.delete(f"/api/plans/{plan['id']}/accounts/{account_id}")
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'CONFLICT'
