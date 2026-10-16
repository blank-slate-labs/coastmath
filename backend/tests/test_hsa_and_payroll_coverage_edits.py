"""Editing HSA and state payroll coverage keeps plans independent and rejected drafts unsaved."""
from copy import deepcopy

import pytest

from tests.corrected_fixture_support import (
    corrected_fixture,
    engine_request,
    persist_fixture,
)


@pytest.mark.anyio
async def test_coverage_edit_reload_isolation_and_old_client_patch(db_session, test_user, client):
    raw = corrected_fixture('high_earner_late_saver')
    raw['life_expectancy'] = 51
    a = persist_fixture(raw, db_session, test_user)
    created = await client.post('/api/plans', json={'name': 'Independent', 'birth_year': 1976})
    assert created.status_code == 201
    b = created.json()['id']
    settings = {'hsa_coverage': [{'owner': 'self', 'start_year': 2026, 'end_year': 2026,
        'coverage': 'family', 'eligible_months': [1, 2, 3, 4, 5, 6]}],
        'ca_exemption_eligible_owners': [], 'state_payroll_paid_year_to_date': {'California SDI': 0}}
    saved = await client.put(f'/api/plans/{a.plan_id}', json={'tax_settings': settings})
    assert saved.status_code == 200, saved.text
    reloaded = (await client.get(f'/api/plans/{a.plan_id}')).json()
    assert reloaded['tax_settings']['hsa_coverage'][0]['eligible_months'] == [1, 2, 3, 4, 5, 6]
    assert reloaded['tax_settings']['ca_exemption_eligible_owners'] == []
    assert not ((await client.get(f'/api/plans/{b}')).json().get('tax_settings') or {}).get('hsa_coverage')
    assert (await client.put(f'/api/plans/{a.plan_id}', json={'name': 'Old client rename'})).status_code == 200
    assert (await client.get(f'/api/plans/{a.plan_id}')).json()['tax_settings'] == reloaded['tax_settings']
    for bad in [dict(settings, hsa_coverage=settings['hsa_coverage'] * 2),
                dict(settings, hsa_coverage=[dict(settings['hsa_coverage'][0], eligible_months=[])]),
                dict(settings, state_payroll_paid_year_to_date={'California SDI': -1})]:
        response = await client.put(f'/api/plans/{a.plan_id}', json={'tax_settings': bad})
        assert response.status_code == 422
        assert (await client.get(f'/api/plans/{a.plan_id}')).json()['tax_settings'] == reloaded['tax_settings']
        req = engine_request(a).model_dump(mode='json')
        req['tax_settings'] = bad
        assert (await client.post('/api/simulate/stateless', json=req)).status_code == 422
    req = engine_request(a).model_dump(mode='json')
    req['tax_settings'] = deepcopy(reloaded['tax_settings'])
    persisted = await client.post(f'/api/plans/{a.plan_id}/simulate')
    stateless = await client.post('/api/simulate/stateless', json=req)
    assert persisted.status_code == stateless.status_code == 200
    assert persisted.json() == stateless.json()
