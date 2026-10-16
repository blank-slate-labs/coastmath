"""HTTP contracts with persisted read-back and independent cash expectations."""
from unittest.mock import Mock

import pytest

from app.auth.router import create_jwt
from app.models.user import User
from app.routers import simulation_stateless
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from tests.api_support import assert_error, blob, contract_plan

pytestmark = pytest.mark.anyio


async def test_assumption_crud_round_trip_and_mode_validation(client):
    pid = await contract_plan(client)
    url = f'/api/plans/{pid}/assumptions'
    response = await client.post(url, json={'curve_type': 'inflation', 'fixed_rate': .02})
    assert response.status_code == 201
    curve = response.json()
    item = url + '/' + curve['id']
    assert (await client.get(url)).json() == [curve]
    assert_error(await client.post(url, json={'curve_type': 'inflation', 'fixed_rate': .03}), 409, 'VALIDATION_ERROR')
    assert_error(await client.put(item, json={'mode': 'curve'}), 422, 'VALIDATION_ERROR')
    points = [{'x': 50, 'y': .02}, {'x': 70, 'y': .04}]
    updated = await client.put(item, json={'mode': 'curve', 'control_points': points, 'fixed_rate': None})
    assert updated.status_code == 200 and updated.json()['control_points'] == points
    assert (await client.get(url)).json() == [updated.json()]
    assert_error(await client.put(item, json={'control_points': []}), 422, 'VALIDATION_ERROR')
    assert_error(await client.put(item, json={'mode': 'fixed'}), 422, 'VALIDATION_ERROR')
    fixed = await client.put(item, json={'mode': 'fixed', 'fixed_rate': 0})
    assert fixed.status_code == 200 and fixed.json()['fixed_rate'] == 0
    assert (await client.put(item, json={})).json() == fixed.json()
    assert (await client.delete(item)).status_code == 204
    assert (await client.get(url)).json() == []
    assert_error(await client.delete(item), 404, 'NOT_FOUND')
    assert_error(await client.put(item, json={'fixed_rate': .01}), 404, 'NOT_FOUND')


@pytest.mark.parametrize('body', [
    {'curve_type': 'inflation', 'mode': 'curve'}, {'curve_type': 'inflation', 'mode': 'fixed'},
    {'curve_type': 'inflation', 'control_points': [{'x': 50}]}, {'curve_type': 'invalid', 'fixed_rate': .02},
])
async def test_assumption_invalid_create_does_not_persist(client, body):
    pid = await contract_plan(client)
    url = f'/api/plans/{pid}/assumptions'
    assert_error(await client.post(url, json=body), 422, 'VALIDATION_ERROR')
    assert (await client.get(url)).json() == []


@pytest.mark.parametrize('method', ['get', 'post', 'put', 'delete'])
async def test_assumption_ownership(client, db_session, test_user, method):
    pid = await contract_plan(client)
    url = f'/api/plans/{pid}/assumptions'
    curve = (await client.post(url, json={'curve_type': 'inflation', 'fixed_rate': .02})).json()
    other = User(is_anonymous=True, settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set('session', create_jwt(other.id))
    path = url if method in ('get', 'post') else url + '/' + curve['id']
    kwargs = {} if method in ('get', 'delete') else {'json': {'curve_type': 'inflation', 'fixed_rate': .05}}
    assert_error(await getattr(client, method)(path, **kwargs), 404, 'NOT_FOUND')
    client.cookies.set('session', create_jwt(test_user.id))
    assert (await client.get(url)).json() == [curve]


async def test_progress_persistence_filter_order_delete_and_ownership(client, db_session, test_user):
    points = []
    for day, worth in [('2026-01-01', 10000), ('2026-02-01', 12500)]:
        body = {'recorded_date': day, 'net_worth': worth, 'assets_breakdown': {'cash': worth + 500}, 'liabilities_breakdown': {'loan': 500}, 'auto_logged': False}
        response = await client.post('/api/progress-points', json=body)
        assert response.status_code == 201
        for key, value in body.items():
            assert response.json()[key] == value
        points.append(response.json())
    assert (await client.get('/api/progress-points')).json() == points[::-1]
    assert (await client.get('/api/progress-points?since=2026-02-01')).json() == points[1:]
    assert_error(await client.get('/api/progress-points?since=invalid'), 422, 'VALIDATION_ERROR')
    # Totals beyond the clients' $1 trillion field range are refused, not stored.
    huge = 99_999_999_999_999
    for bad in [{'net_worth': huge}, {'net_worth': 0, 'assets_breakdown': {'liquid_assets': huge}},
                {'net_worth': 0, 'liabilities_breakdown': {'debt': -1}}]:
        assert_error(await client.post('/api/progress-points', json={'recorded_date': '2026-03-01', **bad}), 422, 'VALIDATION_ERROR')
    assert len((await client.get('/api/progress-points')).json()) == 2
    other = User(is_anonymous=True, settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set('session', create_jwt(other.id))
    assert (await client.get('/api/progress-points')).json() == []
    assert_error(await client.delete('/api/progress-points/' + points[0]['id']), 404, 'NOT_FOUND')
    client.cookies.set('session', create_jwt(test_user.id))
    assert (await client.delete('/api/progress-points/' + points[0]['id'])).status_code == 204
    assert (await client.get('/api/progress-points')).json() == points[1:]


async def test_tax_jurisdiction_crud_and_ownership(client, db_session, test_user):
    body = {'level': 'state', 'jurisdiction_code': 'ca', 'custom_brackets': [{'min': 0, 'max': 10000, 'rate': .02}, {'min': 10000, 'max': None, 'rate': .05}]}
    created = await client.post('/api/tax-jurisdictions', json=body)
    assert created.status_code == 201
    saved = created.json()
    assert saved['jurisdiction_code'] == 'CA'
    url = '/api/tax-jurisdictions/' + saved['id']
    assert (await client.get(url)).json() == saved
    updated = await client.put(url, json={'level': 'state', 'jurisdiction_code': 'ny', 'custom_brackets': []})
    assert updated.status_code == 200 and updated.json()['jurisdiction_code'] == 'NY'
    assert (await client.get('/api/tax-jurisdictions')).json() == [updated.json()]
    other = User(is_anonymous=True, settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set('session', create_jwt(other.id))
    assert (await client.get('/api/tax-jurisdictions')).json() == []
    for method in ('get', 'put', 'delete'):
        assert_error(await getattr(client, method)(url, **({'json': {}} if method == 'put' else {})), 404, 'NOT_FOUND')
    client.cookies.set('session', create_jwt(test_user.id))
    assert (await client.delete(url)).status_code == 204
    assert_error(await client.get(url), 404, 'NOT_FOUND')


async def test_stateless_cash_conservation_and_compare_year_union(client):
    current = blob(expenses=[{'id': 'e', 'name': 'Living', 'annual_amount': 1000, 'inflation_linked': False}])
    response = await client.post('/api/simulate/stateless', json=current)
    assert response.status_code == 200, response.text
    assert [s['net_worth'] for s in response.json()['yearly_snapshots']] == [9000, 8000]
    compare = await client.post('/api/compare/stateless', json={'current': current, 'baseline': blob(start_year=2027)})
    assert compare.status_code == 200
    assert compare.json()['delta'] == [
        {'year': 2026, 'current_net_worth': 9000, 'baseline_net_worth': 0, 'difference': 9000},
        {'year': 2027, 'current_net_worth': 8000, 'baseline_net_worth': 10000, 'difference': -2000}]


@pytest.mark.parametrize('year', [1927, 2025])
async def test_stateless_historical_range(client, year):
    assert_error(await client.post(f'/api/simulate/stateless?historical_start_year={year}', json=blob()), 422, 'VALIDATION_ERROR')


async def test_stateless_real_historical_cash_account(client):
    response = await client.post('/api/simulate/stateless?historical_start_year=1929', json=blob())
    assert response.status_code == 200, response.text
    assert [s['net_worth'] for s in response.json()['simulation_result']['yearly_snapshots']] == [10000, 10000]


@pytest.mark.parametrize('case', ['simulation', 'historical', 'current', 'baseline'])
async def test_stateless_engine_errors_are_sanitized(client, monkeypatch, case, caplog):
    if case == 'historical':
        monkeypatch.setattr(simulation_stateless, 'run_historical_stress_test', Mock(side_effect=RuntimeError('private detail')))
    elif case == 'baseline':
        valid = simulation_stateless.run_simulation(request_to_engine_data(PlanDataRequest(**blob())))
        monkeypatch.setattr(simulation_stateless, 'run_simulation', Mock(side_effect=[valid, RuntimeError('private detail')]))
    else:
        monkeypatch.setattr(simulation_stateless, 'run_simulation', Mock(side_effect=RuntimeError('private detail')))
    url = '/api/simulate/stateless' + ('?historical_start_year=1929' if case == 'historical' else '')
    body = blob()
    if case in ('current', 'baseline'):
        url, body = '/api/compare/stateless', {'current': body, 'baseline': blob()}
    response = await client.post(url, json=body)
    assert_error(response, 500, 'SIMULATION_FAILED')
    assert 'private detail' not in response.text
    assert 'RuntimeError (message withheld)' in caplog.text and 'private detail' not in caplog.text
