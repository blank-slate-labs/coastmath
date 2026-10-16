"""Saved financial input round trips and failed computation contracts."""
import uuid
from unittest.mock import Mock

import pytest

from app.routers import helpers, monte_carlo_stateless, simulation
from tests.api_support import assert_error, blob, contract_plan

pytestmark = pytest.mark.anyio


async def test_saved_snapshot_preserves_opening_balance_and_account_fields(client):
    aid = str(uuid.uuid4())
    body = {'name': 'Frozen opening', 'birth_year': 1976, 'life_expectancy': 52, 'plan_type': 'FIXED_DATE', 'start_date': '2026-01-01',
            'snapshot_conditions': {aid: {'balance': 12345, 'account_type': 'checking', 'name': 'Snapshot cash', 'owner': 'self'}}}
    saved = await client.post('/api/plans', json=body)
    assert saved.status_code == 201, saved.text
    url = f"/api/plans/{saved.json()['id']}"
    assert (await client.get(url)).json()['snapshot_conditions'] == body['snapshot_conditions']
    result = await client.post(url + '/simulate')
    assert result.status_code == 200, result.text
    assert result.json()['initial_snapshot']['net_worth'] == 12345
    assert result.json()['yearly_snapshots'][0]['accounts'][aid] == 12345


async def test_asset_and_loan_round_trips_and_reference_validation(client):
    pid = await contract_plan(client)
    base = f'/api/plans/{pid}'
    account = (await client.post('/api/accounts', json={'name': 'Offset', 'account_type': 'savings', 'balance': 500})).json()
    milestone = (await client.post(base + '/milestones', json={'name': 'Payoff', 'trigger_type': 'age', 'trigger_value': 51})).json()
    asset_body = {'name': 'Home', 'current_value': 100000, 'liquidation_target_account_id': account['id']}
    asset = (await client.post(base + '/real-assets', json=asset_body)).json()
    assert (await client.get(base + '/real-assets')).json() == [asset]
    assert (await client.get(base + '/real-assets/' + asset['id'])).json() == asset
    for method in ('post', 'put'):
        path = base + '/real-assets' + ('/' + asset['id'] if method == 'put' else '')
        assert_error(await getattr(client, method)(path, json={**asset_body, 'liquidation_target_account_id': str(uuid.uuid4())}), 422, 'VALIDATION_ERROR')
    body = {'name': 'Loan', 'principal_balance': 12000, 'interest_rate': 0, 'term_months': 12, 'linked_asset_id': asset['id'], 'offset_account_id': account['id'], 'payoff_milestone_id': milestone['id']}
    created = await client.post(base + '/liabilities', json=body)
    assert created.status_code == 201, created.text
    loan = created.json()
    url = base + '/liabilities/' + loan['id']
    assert (await client.get(base + '/liabilities')).json() == [loan]
    assert (await client.get(url)).json() == loan
    for key, value in body.items():
        assert loan[key] == value
    for field in ('linked_asset_id', 'offset_account_id', 'payoff_milestone_id'):
        for method in ('post', 'put'):
            assert_error(await getattr(client, method)(base + '/liabilities' if method == 'post' else url, json={**body, field: str(uuid.uuid4())}), 422, 'VALIDATION_ERROR')
    updated = await client.put(url, json={'name': 'Updated loan', 'offset_account_id': None})
    assert updated.status_code == 200 and updated.json()['offset_account_id'] is None
    assert (await client.get(url)).json() == updated.json()
    schedule = await client.get(url + '/amortization')
    assert schedule.json() == {'schedule': [{'year': 1, 'principal_paid': 12000, 'interest_paid': 0, 'remaining_balance': 0, 'cumulative_interest': 0}]}
    assert (await client.delete(url)).status_code == 204
    assert_error(await client.get(url), 404, 'NOT_FOUND')
    assert (await client.delete(base + '/real-assets/' + asset['id'])).status_code == 204
    assert (await client.get(base + '/real-assets')).json() == []


@pytest.mark.parametrize('body,expected', [
    ({'payment_type': 'custom'}, []),
    ({'payment_type': 'fixed', 'term_months': 1, 'interest_rate': 12}, [{'year': 1, 'principal_paid': 1000, 'interest_paid': 10, 'remaining_balance': 0, 'cumulative_interest': 10}]),
    ({'payment_type': 'percent_of_balance', 'monthly_payment': .5}, None),
])
async def test_amortization_modes(client, body, expected):
    pid = await contract_plan(client)
    url = f'/api/plans/{pid}/liabilities'
    created = await client.post(url, json={'name': 'Loan', 'principal_balance': 1000, 'interest_rate': 0, **body})
    assert created.status_code == 201, created.text
    result = await client.get(url + '/' + created.json()['id'] + '/amortization')
    assert result.status_code == 200
    if expected is not None:
        assert result.json()['schedule'] == expected
    else:
        # Half the zero-interest balance is paid each month: 1000 / 2^12.
        assert result.json()['schedule'][0]['remaining_balance'] == .24
        assert result.json()['schedule'][0]['principal_paid'] == 999.76


@pytest.mark.parametrize('historical', [False, True])
async def test_saved_simulation_error_contract(client, monkeypatch, historical, caplog):
    pid = await contract_plan(client)
    monkeypatch.setattr(simulation, 'run_historical_stress_test' if historical else 'run_simulation', Mock(side_effect=RuntimeError('private detail')))
    response = await client.post(f'/api/plans/{pid}/simulate' + ('?historical_start_year=1929' if historical else ''))
    assert_error(response, 500, 'SIMULATION_FAILED')
    assert 'private detail' not in response.text
    # The log locates the failure without repeating the engine's message.
    assert 'RuntimeError (message withheld)' in caplog.text and 'private detail' not in caplog.text


@pytest.mark.parametrize('year', [1927, 1929, 2025])
async def test_saved_historical_range_and_success(client, year):
    pid = await contract_plan(client)
    response = await client.post(f'/api/plans/{pid}/simulate?historical_start_year={year}')
    if year == 1929:
        assert response.status_code == 200 and len(response.json()['simulation_result']['yearly_snapshots']) == 2
    else:
        assert_error(response, 422, 'VALIDATION_ERROR')


async def test_stateless_monte_carlo_seeded_real_worker_and_failure(client, monkeypatch, caplog):
    body = {'plan': blob(), 'num_simulations': 3, 'block_size': 3, 'seed': 42}
    first = await client.post('/api/monte-carlo/stateless', json=body)
    second = await client.post('/api/monte-carlo/stateless', json=body)
    assert first.status_code == second.status_code == 200, first.text
    assert first.json()['n_trials'] == 3
    assert first.json()['success_rate'] == 1
    assert first.json()['percentile_curves'] == second.json()['percentile_curves']
    monkeypatch.setattr(monte_carlo_stateless, 'run_monte_carlo', Mock(side_effect=RuntimeError('private detail')))
    assert_error(await client.post('/api/monte-carlo/stateless', json=body), 500, 'SIMULATION_FAILED')
    assert 'RuntimeError (message withheld)' in caplog.text and 'private detail' not in caplog.text


async def test_real_session_rate_limit_remains_enabled(client):
    for _ in range(30):
        assert (await client.post('/api/auth/session')).status_code == 200
    assert (await client.post('/api/auth/session')).status_code == 429


async def test_snapshot_conversion_retains_tax_and_owner_metadata_without_creating_accounts(client, db_session, test_user):
    aid = str(uuid.uuid4())
    snapshot = {'balance': 1000, 'account_type': 'taxable_brokerage', 'name': 'Inherited holding', 'owner': 'spouse', 'cost_basis': 600, 'inherited_year': 2020, 'beneficiary_type': 'edb'}
    saved = await client.post('/api/plans', json={'name': 'Frozen tax data', 'birth_year': 1976, 'plan_type': 'FIXED_DATE', 'start_date': '2026-01-01', 'snapshot_conditions': {aid: snapshot}})
    assert saved.status_code == 201
    converted = helpers.load_plan_data(uuid.UUID(saved.json()['id']), test_user, db_session)
    account = converted.accounts[aid]
    for field, value in snapshot.items():
        assert getattr(account, field) == value
    assert (await client.get('/api/accounts')).json() == []
