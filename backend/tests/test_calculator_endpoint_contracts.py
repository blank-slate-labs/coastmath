"""Calculator endpoint contracts and independent aggregate expectations."""
import pytest

from coastmath.engine.healthcare import ACAResult, HealthcareYearResult, MedicareResult
from coastmath.engine.types import SimState


def test_healthcare_total_includes_every_premium_and_handles_uncovered_households():
    medicare = MedicareResult(part_b_standard=50, part_b_irmaa=10, part_d_irmaa=15, part_d_plan=25, supplement=20)
    assert HealthcareYearResult().total == 0
    assert HealthcareYearResult(aca=ACAResult(net_premium=100)).total == 100
    assert HealthcareYearResult(medicare=medicare).total == 120
    assert HealthcareYearResult(aca=ACAResult(net_premium=100), medicare=medicare).total == 220


def test_portfolio_lookback_compounds_only_the_requested_trailing_years():
    state = SimState(year=2026, return_history=[1, .1, -.1])
    assert state.portfolio_return_over(4) is None
    assert state.portfolio_return_over(2) == pytest.approx(-.01)  # $100 -> $110 -> $99.
    assert state.portfolio_return_over(1) == pytest.approx(-.1)
    assert state.return_history == [1, .1, -.1]


@pytest.mark.anyio
async def test_ss_estimate_response_uses_the_documented_simplified_replacement_model(client):
    # This is the app's approximation, not a claim about an individual's SSA benefit.
    for age, factor, expected in [(62, .7, 6300), (67, 1, 9000), (70, 1.24, 11160)]:
        response = await client.post('/api/plans/ss-estimate', json={'current_annual_income': 10000, 'claiming_age': age})
        assert response.status_code == 200
        assert response.json() == pytest.approx({'estimated_annual_benefit': expected, 'claiming_age': age, 'claiming_factor': factor, 'full_retirement_age':67})


@pytest.mark.anyio
@pytest.mark.parametrize('body', [{'current_annual_income': -1}, {'current_annual_income': 10000, 'claiming_age': 61}, {'current_annual_income': 10000, 'claiming_age': 71}])
async def test_ss_estimate_rejects_unsupported_inputs(client, body):
    response = await client.post('/api/plans/ss-estimate', json=body)
    assert response.status_code == 422 and response.json()['error']['code'] == 'VALIDATION_ERROR'


@pytest.mark.anyio
@pytest.mark.parametrize('path,body', [('ss-estimate', {'current_annual_income': 10000}), ('sepp-preview', {'balance': 10000, 'start_age': 50})])
async def test_retirement_previews_require_a_session(client, path, body):
    client.cookies.clear()
    response = await client.post('/api/plans/' + path, json=body)
    assert response.status_code == 401 and response.json()['error']['code'] == 'AUTH_REQUIRED'
