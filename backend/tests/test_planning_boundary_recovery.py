"""Rejected references must leave saved household resources intact."""
import uuid

import pytest
from fastapi import HTTPException

from app.routers.helpers import resolve_milestone_year, validate_account_references
from coastmath.engine.household_lifecycle import simulation_end_year
from coastmath.engine.social_security import (
    estimate_ss_benefit_from_pia,
    full_retirement_age,
)
from coastmath.engine.types import EstateSettingsData, PlanData
from tests.scenario_support import extra_workspace, post


@pytest.mark.anyio
async def test_deleting_referenced_accounts_requires_removing_each_reference(client):
    household = (await client.post('/api/clients/personal')).json()
    plan = await post(client, '/plans', {'name': 'Base', 'birth_year': 1980, 'client_id': household['id']})
    root = '/plans/' + plan['id']
    account = await post(client, root + '/accounts', {'name': 'Cash', 'account_type': 'checking', 'balance': 10000})
    aid = account['id']
    for suffix, payload in [
        ('expenses', {'name': 'Living', 'annual_amount': 1000, 'specific_funding_source_ids': [aid]}),
        ('liabilities', {'name': 'Loan', 'principal_balance': 1000, 'interest_rate': 0, 'term_months': 12, 'offset_account_id': aid}),
        ('real-assets', {'name': 'Asset', 'current_value': 1000, 'liquidation_target_account_id': aid}),
    ]:
        resource = await post(client, root + '/' + suffix, payload)
        rejected = await client.delete('/api' + root + '/accounts/' + aid)
        assert rejected.status_code == 409, rejected.text
        assert (await client.get('/api' + root + '/accounts')).json()[0]['balance'] == 10000
        assert (await client.delete('/api' + root + '/' + suffix + '/' + resource['id'])).status_code == 204
    # A disabled, saved SEPP source is still a reference that must not dangle.
    response = await client.put('/api' + root, json={'sepp_settings': {'enabled': False, 'start_age': 50, 'source_account_id': aid}})
    assert response.status_code == 200, response.text
    assert (await client.delete('/api' + root + '/accounts/' + aid)).status_code == 409
    assert (await client.put('/api' + root, json={'sepp_settings': None})).status_code == 200
    assert (await client.delete('/api' + root + '/accounts/' + aid)).status_code == 204


@pytest.mark.anyio
async def test_client_plan_creation_and_comparison_do_not_cross_households(client, db_session, test_user):
    a = (await client.post('/api/clients/personal')).json()
    b = extra_workspace(db_session, test_user.id, 'B')
    base = {'name': 'Plan', 'birth_year': 1980, 'client_id': a['id']}
    aid = str(uuid.uuid4())
    for extra in [{'snapshot_conditions': {aid: 100}}, {'sepp_settings': {'source_account_id': aid, 'start_age': 50}}]:
        response = await client.post('/api/plans', json={**base, **extra})
        assert response.status_code == 422, response.text
    p = await post(client, '/plans', {**base, 'healthcare_settings': {'method': 'off'}, 'sepp_settings': {'enabled': False, 'start_age': 50}})
    q = await post(client, '/plans', {**base, 'name': 'Other client', 'client_id': b['id']})
    same = await post(client, '/plans', {**base, 'name': 'Alternative'})
    response = await client.put('/api/plans/' + p['id'], json={'baseline_plan_id': q['id']})
    assert response.status_code == 422, response.text
    assert (await client.get('/api/plans/' + p['id'])).json()['baseline_plan_id'] is None
    assert (await client.put('/api/plans/' + p['id'], json={'baseline_plan_id': same['id']})).status_code == 200
    assert {x['id'] for x in (await client.get('/api/plans', params={'client_id': a['id']})).json()} == {p['id'], same['id']}


@pytest.mark.anyio
@pytest.mark.parametrize('fields', [
    {'start_milestone_id': str(uuid.uuid4())},
    {'is_payroll_deduction': True, 'tied_income_id': str(uuid.uuid4())},
])
async def test_unknown_expense_dependencies_fail_without_persisting(client, fields):
    p = await post(client, '/plans', {'name': 'Rejected dependency', 'birth_year': 1980})
    response = await client.post('/api/plans/' + p['id'] + '/expenses', json={'name': 'Expense', 'annual_amount': 100, **fields})
    assert response.status_code == 422, response.text
    assert (await client.get('/api/plans/' + p['id'] + '/expenses')).json() == []


def test_empty_and_duplicate_account_reference_validation(db_session, test_user):
    # Empty optional selections need no lookup; duplicates are rejected before a write.
    pid, aid = uuid.uuid4(), uuid.uuid4()
    for empty in (None, []):
        validate_account_references(pid, empty, test_user.id, db_session, 'funding')
    with pytest.raises(HTTPException) as caught:
        validate_account_references(pid, [aid, aid], test_user.id, db_session, 'funding')
    assert caught.value.status_code == 422
    assert resolve_milestone_year(None, {}, 1980) is None


@pytest.mark.parametrize('pia,percentage', [(-1, 100), (float('inf'), 100), (2000, -1), (2000, 101), (2000, float('nan'))])
def test_pia_engine_boundary_rejects_nonfinite_and_out_of_range_inputs(pia, percentage):
    with pytest.raises(ValueError):
        estimate_ss_benefit_from_pia(pia, expected_benefit_percentage=percentage)


@pytest.mark.parametrize('birth,fra', [(1937, 65), (1938, 65 + 2/12), (1942, 65 + 10/12)])
def test_pia_cohort_full_retirement_ages(birth, fra):
    assert full_retirement_age(birth) == pytest.approx(fra)


@pytest.mark.parametrize('changes,settings,message', [
    ({}, {'household_lifecycle': 'unknown'}, 'Unknown household'),
    ({'spouse_birth_year': 1982}, {}, 'explicit spouse longevity'),
    ({'spouse_birth_year': 1982, 'spouse_life_expectancy': 49}, {}, '50 to 120'),
    ({'filing_status': 'married_filing_jointly'}, {}, 'spouse birth year'),
    ({}, {'filing_status_after_death': 'married_filing_jointly'}, 'unmarried'),
    ({'start_year': 2200}, {}, 'before the projection'),
])
def test_last_survivor_rejects_unsupported_household_inputs(changes, settings, message):
    plan = PlanData(plan_id='boundary', birth_year=1980, life_expectancy=90, filing_status='single', start_year=2026,
                    estate_settings=EstateSettingsData(household_lifecycle='last_survivor_calendar_year_end', **settings) if 'household_lifecycle' not in settings else EstateSettingsData(**settings))
    for key, value in changes.items():
        setattr(plan, key, value)
    with pytest.raises(ValueError, match=message):
        simulation_end_year(plan)
