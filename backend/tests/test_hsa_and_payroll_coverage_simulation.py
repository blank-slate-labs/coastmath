"""Cash conservation and persisted/stateless HSA and state payroll coverage, with explicit facts."""
from copy import deepcopy

import pytest

from coastmath.engine.simulator import run_simulation
from tests.corrected_fixture_support import (
    corrected_fixture,
    engine_request,
    persist_fixture,
)
from tests.engine_support import reconcile
from tests.persona.harness import build_plan_from_fixture


@pytest.mark.anyio
@pytest.mark.parametrize('coverage,expected', [('self_only', 4400), ('family', 8300), ('ineligible', 0)])
async def test_hsa_explicit_coverage_survives_reload_and_both_routes(coverage, expected, db_session, test_user, client):
    raw = corrected_fixture('high_earner_late_saver')
    raw['life_expectancy'] = 51
    raw['tax_settings'] = {'hsa_coverage': [{'owner': 'self', 'start_year': 2026, 'coverage': coverage}]}
    persisted = persist_fixture(raw, db_session, test_user)
    result = run_simulation(persisted)
    hsa_id = next(a['id'] for a in raw['accounts'] if a['account_type'] == 'hsa')
    contributed = sum(f.amount for f in result.yearly_snapshots[0].cash_flow.contributions if f.account_id == hsa_id)
    assert contributed == pytest.approx(expected, abs=.01)
    reconcile(result)
    a = await client.post(f'/api/plans/{persisted.plan_id}/simulate')
    b = await client.post('/api/simulate/stateless', json=engine_request(persisted).model_dump(mode='json'))
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() == result.model_dump(mode='json')


@pytest.mark.anyio
@pytest.mark.parametrize('case,rows,expected', [
    ('fire_persona', [{'owner': 'self', 'start_year': 2026, 'state_code': 'CA', 'ca_sdi': True}], 2340),
    ('inherited_ira', [{'owner': 'self', 'start_year': 2026, 'state_code': 'CA', 'ca_sdi': True}], 1820),
    ('hnw_estate', [{'owner': 'self', 'start_year': 2026, 'state_code': 'WA', 'wa_paid_leave': True, 'wa_cares': True}],
     184500 * .0113 * .7143 + 250000 * .0058),
])
async def test_localized_payroll_obligation_paid_once_and_both_routes(case, rows, expected, db_session, test_user, client):
    raw = corrected_fixture(case)
    raw['life_expectancy'] = max(50, 2027 - raw['birth_year'])
    raw['tax_settings'] = {'state_payroll_coverage': rows}
    p = persist_fixture(raw, db_session, test_user)
    result = run_simulation(p)
    snapshot = result.yearly_snapshots[0]
    payroll = sum(f.amount for f in snapshot.cash_flow.expenses if f.category == 'state_payroll_tax')
    assert payroll == pytest.approx(expected, abs=.01)
    baseline = deepcopy(p)
    baseline.tax_settings = None
    before = run_simulation(baseline).yearly_snapshots[0]
    # Each dollar spent also forgoes its remaining end-of-month growth.
    rate = p.assumptions.stock_growth_rate + p.assumptions.stock_dividend_yield
    # HNW's residual funds stay in checking; the other fixtures invest them.
    if case == 'hnw_estate':
        rate = 0
    monthly_value = sum((1 + rate) ** (month / 12) for month in range(12)) / 12
    assert snapshot.net_worth - before.net_worth == pytest.approx(-expected * monthly_value, abs=.01)
    assert snapshot.expenses - before.expenses == pytest.approx(expected, abs=.01)
    assert snapshot.taxes == before.taxes
    reconcile(result)
    a = await client.post(f'/api/plans/{p.plan_id}/simulate')
    b = await client.post('/api/simulate/stateless', json=engine_request(p).model_dump(mode='json'))
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() == result.model_dump(mode='json')


def test_ytd_payroll_payments_credit_only_opening_year_and_cap_uses_full_wages():
    p = build_plan_from_fixture(corrected_fixture('hnw_estate'))
    p.life_expectancy = 2028 - p.birth_year
    p.first_year_fraction = .5
    p.tax_settings = {
        'state_payroll_coverage': [{'owner': 'self', 'start_year': 2026, 'state_code': 'WA', 'wa_paid_leave': True}],
        'year_to_date': {'tax_year': 2026, 'w2_income_by_owner': {'self': 150000}},
        'state_payroll_paid_year_to_date': {'Washington Paid Leave': 150000 * .0113 * .7143},
    }
    result = run_simulation(p)
    first = sum(f.amount for f in result.yearly_snapshots[0].cash_flow.expenses if f.category == 'state_payroll_tax')
    second = sum(f.amount for f in result.yearly_snapshots[1].cash_flow.expenses if f.category == 'state_payroll_tax')
    assert first == pytest.approx((184500 - 150000) * .0113 * .7143)
    assert second == pytest.approx(184500 * 1.03 * .0113 * .7143)
    reconcile(result)


def test_unknown_coverage_preserves_legacy_with_visible_uncertainty():
    p = build_plan_from_fixture(corrected_fixture('high_earner_late_saver'))
    p.life_expectancy = 51
    p.state_code = 'CA'
    p.residency_periods = []
    result = run_simulation(p)
    warnings = ' '.join(result.metadata.warnings)
    assert 'HSA eligibility is unspecified' in warnings
    assert 'State payroll coverage is unspecified' in warnings
    assert 'California personal and senior exemption eligibility is unknown' in warnings
    assert not any(f.category == 'state_payroll_tax' for f in result.yearly_snapshots[0].cash_flow.expenses)
