"""Boundary contracts shared by saved and stateless input validation."""
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.assumption_curve import AssumptionCurveCreate, AssumptionCurveUpdate
from app.schemas.cash_flow_priority import CashFlowPriorityCreate
from app.schemas.residency_period import (
    ResidencyPeriodCreate,
    ResidencyPeriodRequest,
    ResidencyPeriodUpdate,
)
from app.schemas.tax_jurisdiction import (
    TaxBracket,
    TaxJurisdictionCreate,
    TaxJurisdictionUpdate,
)


@pytest.mark.parametrize('model', [ResidencyPeriodCreate, ResidencyPeriodUpdate, ResidencyPeriodRequest])
@pytest.mark.parametrize('edge', ['start', 'end'])
def test_residency_cannot_anchor_one_boundary_to_both_year_and_milestone(model, edge):
    with pytest.raises(ValidationError, match=f'set only one of {edge}_milestone_id or {edge}_year'):
        model(state_code='ca', **{f'{edge}_year': 2030, f'{edge}_milestone_id': str(uuid.uuid4())})


@pytest.mark.parametrize('model', [ResidencyPeriodCreate, ResidencyPeriodUpdate, ResidencyPeriodRequest])
def test_residency_normalizes_and_retains_explicit_timing(model):
    item = model(state_code='ca', start_year=2026, end_year=2035, rank=2)
    assert item.model_dump(exclude_unset=True) == {'state_code': 'CA', 'start_year': 2026, 'end_year': 2035, 'rank': 2}
    with pytest.raises(ValidationError, match='state_code must be exactly 2 characters'):
        model(state_code='a ')


def test_partial_residency_patch_preserves_explicit_nulls():
    assert ResidencyPeriodUpdate(state_code=None, end_year=None).model_dump(exclude_unset=True) == {'state_code': None, 'end_year': None}


@pytest.mark.parametrize('model', [TaxJurisdictionCreate, TaxJurisdictionUpdate])
@pytest.mark.parametrize('brackets,message', [
    ([{'min': 0, 'max': None, 'rate': .1}, {'min': 100, 'rate': .2}], 'no upper limit'),
    ([{'min': 0, 'max': 200, 'rate': .1}, {'min': 100, 'rate': .2}], 'overlap'),
])
def test_custom_tax_brackets_reject_ambiguous_slices(model, brackets, message):
    with pytest.raises(ValidationError, match=message):
        model(level='state', jurisdiction_code='CA', custom_brackets=brackets)


@pytest.mark.parametrize('model', [TaxJurisdictionCreate, TaxJurisdictionUpdate])
def test_tax_jurisdiction_normalizes_state_and_round_trips_brackets(model):
    brackets = [{'min': 100, 'max': None, 'rate': .2}, {'min': 0, 'max': 100, 'rate': .1}]
    item = model(level='state', jurisdiction_code='ca', custom_brackets=brackets)
    assert item.jurisdiction_code == 'CA'
    assert item.model_dump()['custom_brackets'] == brackets
    with pytest.raises(ValidationError, match='Invalid state code'):
        model(level='state', jurisdiction_code='ZZ')
    assert model(level='federal', custom_brackets=[]).custom_brackets == []
    assert model(level='state').jurisdiction_code is None


@pytest.mark.parametrize('upper', [50, 100])
def test_tax_bracket_must_have_positive_width(upper):
    with pytest.raises(ValidationError, match='max must be greater than min'):
        TaxBracket(min=100, max=upper, rate=.2)
    assert TaxBracket(min=100, max=None, rate=.2).max is None


@pytest.mark.parametrize('model', [AssumptionCurveCreate, AssumptionCurveUpdate])
def test_control_point_shape_is_checked_at_each_index(model):
    with pytest.raises(ValidationError, match=r'control_points\[1\]'):
        model(curve_type='market_return', mode='curve', control_points=[{'x': 40, 'y': .03}, {'y': .04}])
    points = [{'x': 40, 'y': -.03}, {'x': 50, 'y': 0}]
    assert model(curve_type='market_return', mode='curve', control_points=points).control_points == points
    assert AssumptionCurveUpdate(control_points=None).model_dump(exclude_unset=True) == {'control_points': None}


@pytest.mark.parametrize('body,message', [
    ({'priority_type': 'transfer', 'allocation_mode': 'amount', 'allocation_value': 10}, 'only to surplus contribution'),
    ({'priority_type': 'contribution', 'conversion_mode': 'fill_bracket'}, 'applies only to roth_conversion'),
    ({'priority_type': 'gain_harvest', 'source_account_id': str(uuid.uuid4())}, 'must use conversion_mode'),
    ({'priority_type': 'roth_conversion', 'source_account_id': str(uuid.uuid4()), 'conversion_mode': 'fill_bracket'}, 'bracket_ceiling_rate is required'),
])
def test_priority_modes_cannot_silently_change_financial_meaning(body, message):
    with pytest.raises(ValidationError, match=message):
        CashFlowPriorityCreate(priority_rank=1, **body)


@pytest.mark.anyio
async def test_invalid_tax_bracket_write_does_not_replace_saved_configuration(client):
    original = {'level': 'federal', 'custom_brackets': [{'min': 0, 'max': None, 'rate': .2}]}
    created = await client.post('/api/tax-jurisdictions', json=original)
    assert created.status_code == 201
    saved = created.json()
    url = '/api/tax-jurisdictions/' + saved['id']
    failed = await client.put(url, json={'custom_brackets': [{'min': 100, 'max': 50, 'rate': .2}]})
    assert failed.status_code == 422
    assert failed.json()['error']['code'] == 'VALIDATION_ERROR'
    assert (await client.get(url)).json() == saved
