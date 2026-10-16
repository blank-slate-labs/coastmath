"""Startup guards and authentication failures without external services."""
import json
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import db, main
from app.auth.dependencies import SESSION_SECRET
from app.middleware.error_handler import (
    generic_exception_handler,
    http_exception_handler,
)
from app.plugins import extensions

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize('failure', ['no_engine', 'default_secret', 'short_secret', 'connection', 'none'])
async def test_startup_checks_configuration_and_connection_before_serving(monkeypatch, failure):
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    monkeypatch.setattr(main, 'engine', None if failure == 'no_engine' else engine)
    # This is only a configuration flag: engine is a controlled boundary and
    # cannot open any network connection in this test.
    monkeypatch.setenv('DATABASE_URL', 'postgresql://invalid.test/not-used')
    monkeypatch.setattr(main, 'SESSION_SECRET', main.DEV_SESSION_SECRET if failure == 'default_secret' else ('short' if failure == 'short_secret' else 'controlled-test-secret-at-least-32-bytes'))
    if failure == 'connection':
        engine.connect.side_effect = OSError('controlled connection failure')
    expected = {'no_engine': 'DATABASE_URL is not configured', 'default_secret': 'SESSION_SECRET must be changed', 'short_secret': 'at least 32 characters', 'connection': 'Database is not reachable'}
    if failure in expected:
        with pytest.raises(RuntimeError, match=expected[failure]):
            async with main.lifespan(main.app):
                pytest.fail('startup must not succeed')
        if failure != 'connection':
            engine.connect.assert_not_called()
    else:
        async with main.lifespan(main.app):
            assert str(connection.execute.call_args.args[0]) == 'SELECT 1'
        engine.connect.return_value.__exit__.assert_called_once()


def test_database_dependency_fails_explicitly_or_closes_sessions_even_on_error(monkeypatch):
    monkeypatch.setattr(db, 'SessionLocal', None)
    with pytest.raises(HTTPException) as missing:
        next(db.get_db())
    assert missing.value.status_code == 503
    session = MagicMock()
    monkeypatch.setattr(db, 'SessionLocal', lambda: session)
    dependency = db.get_db()
    assert next(dependency) is session
    with pytest.raises(RuntimeError, match='caller failed'):
        dependency.throw(RuntimeError('caller failed'))
    session.close.assert_called_once()


# A fixed, valid UUID that no fixture creates: a random one changes the test ID
# per process, and pytest-xdist requires identical collection on every worker.
@pytest.mark.parametrize('subject', [None, 'not-a-uuid', '5b2f7c3e-9d41-4f8a-b6e0-1c7a2d9e4f30'])
async def test_signed_session_with_missing_malformed_or_deleted_subject_is_unauthenticated(client, subject):
    issuer = extensions.session_token_issuer
    payload = {'aud': issuer, 'iss': issuer}
    if subject is not None:
        payload['sub'] = subject
    client.cookies.set('session', jwt.encode(payload, SESSION_SECRET, algorithm='HS256'))
    response = await client.get('/api/plans')
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTH_REQUIRED'


async def test_missing_and_invalid_sessions_do_not_disclose_plans(client):
    client.cookies.clear()
    response = await client.get('/api/plans')
    assert response.status_code == 401 and response.json()['error']['code'] == 'AUTH_REQUIRED'
    client.cookies.set('session', 'invalid')
    response = await client.get('/api/plans')
    assert response.status_code == 401 and response.json()['error']['code'] == 'AUTH_REQUIRED'


@pytest.mark.parametrize('detail,expected', [
    ('Unavailable', {'code': 'HTTP_503', 'message': 'Unavailable', 'details': []}),
    ({'message': 'Try again', 'details': 'not-a-list'}, {'code': 'HTTP_503', 'message': 'Try again', 'details': []}),
    ({'error': {'code': 'RETRY', 'details': [{'field': 'account'}]}}, {'code': 'RETRY', 'message': 'Request failed', 'details': [{'field': 'account'}]}),
])
async def test_http_error_handler_preserves_contract(detail, expected):
    request = Request({'type': 'http'})
    response = await http_exception_handler(request, HTTPException(503, detail))
    assert response.status_code == 503 and json.loads(response.body) == {'error': expected}


async def test_unexpected_error_logs_its_location_but_never_its_message(caplog):
    # Exception text can quote saved values (SQL parameters, emails, balances), so
    # neither the client nor the log receives it; the type and frames locate it.
    detail = ' '.join(['private', 'database', 'detail'])  # Runtime data, not source text.
    try:
        raise RuntimeError(detail)
    except RuntimeError as exc:
        error = exc
    request = Request({'type': 'http', 'method': 'PUT', 'path': '/api/plans/x'})
    response = await generic_exception_handler(request, error)
    assert response.status_code == 500
    assert json.loads(response.body) == {'error': {'code': 'INTERNAL_ERROR', 'message': 'Internal server error', 'details': []}}
    assert 'private database detail' not in caplog.text
    assert 'PUT /api/plans/x' in caplog.text and 'RuntimeError (message withheld)' in caplog.text
    assert 'test_unexpected_error_logs_its_location_but_never_its_message' in caplog.text
