"""Custom state brackets saved as the plan API's (upper bound, rate) pairs.

``TaxSettings.state_brackets`` stores pairs. The engine once read only the
{min, max, rate} dicts of its own data files and raised ``TypeError`` for
every saved plan that set them.

Illinois has no state standard deduction, so the expectations below are the
bracket arithmetic alone.
"""

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas.plan import TaxSettings
from coastmath.engine.tax_engine import _calculate_state_tax, calculate
from coastmath.schemas.plan_data_request import TaxSettingsRequest

PAIRS = [(50_000, .04), (999_999_999, .06)]
DICTS = [{"min": 0, "max": 50_000, "rate": .04}, {"min": 50_000, "max": 999_999_999, "rate": .06}]


@pytest.mark.parametrize("status,expected", [
    # 4% x 50,000 + 6% x 50,000.
    ("single", 5_000),
    # Custom thresholds keep the doubled joint convention: 4% x 100,000.
    ("married_filing_jointly", 4_000),
    ("head_of_household", 5_000),
])
def test_pairs_tax_like_dicts(status, expected):
    tax = _calculate_state_tax(100_000, "IL", custom_brackets=PAIRS, filing_status=status)
    assert tax == pytest.approx(expected)
    assert tax == pytest.approx(
        _calculate_state_tax(100_000, "IL", custom_brackets=DICTS, filing_status=status))


def test_calculate_accepts_serialized_tax_settings():
    settings = TaxSettings(state_brackets=PAIRS).model_dump(mode="json")
    assert settings["state_brackets"] == [[50_000, .04], [999_999_999, .06]]
    result = calculate(gross_income=100_000, deductions=0, filing_status="single",
                       settings=settings, state_code="IL")
    assert result.state == pytest.approx(5_000)


@pytest.mark.parametrize("model", [TaxSettings, TaxSettingsRequest])
@pytest.mark.parametrize("brackets", [
    [(50_000, .04), (50_000, .06)],          # bounds must increase
    [(80_000, .04), (50_000, .06)],
    [(0, .04)],                              # first bound must be positive
    [(-1, .04)],
    [(50_000, -.01)],                        # rates are fractions
    [(50_000, 1.01)],
    [(float("inf"), .04)],                   # JSONB cannot store non-finite numbers
    [(50_000, float("nan"))],
])
def test_settings_reject_invalid_brackets(model, brackets):
    with pytest.raises(ValidationError):
        model(state_brackets=brackets)


@pytest.mark.parametrize("model", [TaxSettings, TaxSettingsRequest])
def test_settings_accept_empty_and_valid_brackets(model):
    assert model(state_brackets=[]).state_brackets == []
    assert model(state_brackets=PAIRS).state_brackets == PAIRS
    assert model(state_brackets=[(999_999_999, 0)]).state_brackets == [(999_999_999, 0)]


@pytest.mark.anyio
async def test_saved_plan_with_custom_brackets_simulates(client: AsyncClient):
    created = await client.post("/api/plans", json={
        "name": "Custom Illinois brackets", "birth_year": 1980, "plan_type": "FIXED_DATE",
        "start_date": "2026-01-01", "state_code": "IL",
        "tax_settings": {"state_brackets": [[50_000, .04], [999_999_999, .06]]},
    })
    assert created.status_code == 201
    plan_id = created.json()["id"]
    assert created.json()["tax_settings"]["state_brackets"] == [[50_000, .04], [999_999_999, .06]]
    income = await client.post(f"/api/plans/{plan_id}/incomes",
                               json={"name": "Salary", "annual_amount": 100_000})
    assert income.status_code == 201

    simulated = await client.post(f"/api/plans/{plan_id}/simulate")
    assert simulated.status_code == 200
    first = simulated.json()["yearly_snapshots"][0]
    assert first["year"] == 2026
    assert first["state_tax"] == pytest.approx(5_000)


@pytest.mark.anyio
async def test_invalid_brackets_are_rejected_and_saved_ones_kept(client: AsyncClient):
    created = await client.post("/api/plans", json={
        "name": "Custom brackets", "birth_year": 1980, "state_code": "IL",
        "tax_settings": {"state_brackets": [[50_000, .04], [999_999_999, .06]]},
    })
    assert created.status_code == 201
    plan_id = created.json()["id"]

    rejected = await client.put(f"/api/plans/{plan_id}", json={
        "tax_settings": {"state_brackets": [[80_000, .04], [50_000, .06]]}})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
    saved = (await client.get(f"/api/plans/{plan_id}")).json()["tax_settings"]
    assert saved["state_brackets"] == [[50_000, .04], [999_999_999, .06]]
