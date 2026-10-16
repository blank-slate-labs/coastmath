"""Tax adjustments and scheduled tax changes through the plan and stateless APIs."""
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.plan import TaxSettings
from coastmath.schemas.plan_data_request import PlanDataRequest
from coastmath.schemas.tax_adjustments import TaxAdjustment
from tests.api_support import create_plan

pytestmark = pytest.mark.anyio

CREDIT = {"id": "credit-1", "name": "Energy credit", "kind": "credit", "scope": "federal", "amount": 1200,
          "amount_basis": "nominal", "frequency": "once", "start_year": 2027}


def _deduction(milestone_id):
    return {"id": "ded-1", "name": "Alimony", "kind": "deduction", "deduction_type": "above_the_line",
            "scope": "both", "amount": 6000, "amount_basis": "today", "frequency": "annual",
            "end_milestone_id": milestone_id}


async def _plan_with_milestone(client):
    pid = (await create_plan(client, name="Tax", birth_year=1975, state_code="GA"))["id"]
    milestone = await client.post(f"/api/plans/{pid}/milestones",
                                  json={"name": "Retire", "trigger_type": "age", "trigger_value": 60})
    assert milestone.status_code == 201, milestone.text
    return pid, milestone.json()["id"]


def _settings(milestone_id):
    return {"mode": "detailed", "ordinary_income_tax_rate": None, "capital_gains_tax_rate": None,
            "taxable_withholding_rate": 0, "tax_deferred_withholding_rate": 0, "settlement_lag_years": 0,
            "adjustments": [CREDIT, _deduction(milestone_id)],
            "scheduled_changes": [{"milestone_id": milestone_id,
                                   "settings": {"mode": "flat", "ordinary_income_tax_rate": 0.12}}],
            "state_deduction_rules": True}


async def test_round_trip_projection_milestone_guard_and_duplicate_remap(client):
    pid, milestone_id = await _plan_with_milestone(client)
    saved = await client.put(f"/api/plans/{pid}", json={"tax_settings": _settings(milestone_id)})
    assert saved.status_code == 200, saved.text
    settings = (await client.get(f"/api/plans/{pid}")).json()["tax_settings"]
    assert settings["adjustments"] == [TaxAdjustment.model_validate(row).model_dump()
                                       for row in (CREDIT, _deduction(milestone_id))]
    assert settings["adjustments"][0]["owner"] == "household"
    assert settings["scheduled_changes"][0]["settings"] == {"mode": "flat", "ordinary_income_tax_rate": 0.12}
    assert settings["state_deduction_rules"] is True

    projected = await client.post(f"/api/plans/{pid}/simulate", headers={"X-Client-Date": "2026-01-01"})
    assert projected.status_code == 200, projected.text
    rows = {row["year"]: row for row in projected.json()["yearly_snapshots"]}
    assert rows[2026]["tax_adjustment_credits"] == 0 and "tax_adjustment_credits" in rows[2027]

    blocked = await client.delete(f"/api/plans/{pid}/milestones/{milestone_id}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CONFLICT"

    copied = await client.post(f"/api/plans/{pid}/duplicate")
    assert copied.status_code == 201, copied.text
    copy = copied.json()
    new_milestone = copy["milestones"][0]["id"]
    assert new_milestone != milestone_id
    assert copy["tax_settings"]["adjustments"][1]["end_milestone_id"] == new_milestone
    assert copy["tax_settings"]["scheduled_changes"][0]["milestone_id"] == new_milestone
    # The adjustment's own id is not a plan identity and is kept.
    assert copy["tax_settings"]["adjustments"][0]["id"] == "credit-1"


async def test_foreign_or_missing_milestones_and_spouse_items_are_rejected(client):
    pid, _ = await _plan_with_milestone(client)
    other_pid, other_milestone = await _plan_with_milestone(client)
    before = (await client.get(f"/api/plans/{pid}")).json()["tax_settings"]
    response = await client.put(f"/api/plans/{pid}", json={"tax_settings": _settings(other_milestone)})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (await client.get(f"/api/plans/{pid}")).json()["tax_settings"] == before
    spouse_item = {**CREDIT, "owner": "spouse"}
    response = await client.put(f"/api/plans/{pid}", json={"tax_settings": {"adjustments": [spouse_item]}})
    assert response.status_code == 422
    created = await client.post("/api/plans", json={
        "name": "New", "birth_year": 1975, "tax_settings": {"adjustments": [_deduction(other_milestone)]}})
    assert created.status_code == 422
    assert other_pid != pid


async def test_unset_customization_is_not_stored(client):
    pid, _ = await _plan_with_milestone(client)
    saved = await client.put(f"/api/plans/{pid}", json={"tax_settings": {"mode": "detailed"}})
    assert saved.status_code == 200
    settings = saved.json()["tax_settings"]
    for key in ("adjustments", "scheduled_changes", "state_deduction_rules"):
        assert key not in settings


@pytest.mark.parametrize("bad", [
    {**CREDIT, "scope": "both"},
    {**CREDIT, "amount": float("inf")},
    {**CREDIT, "amount": -1},
    {**CREDIT, "refundable": True, "kind": "deduction", "deduction_type": "itemized"},
    {**CREDIT, "kind": "deduction"},
    {**CREDIT, "kind": "surcharge"},
    {**CREDIT, "end_year": 2030},
    {**CREDIT, "frequency": "every_n_years"},
    {**CREDIT, "start_milestone_id": "m"},
    {k: v for k, v in CREDIT.items() if k != "amount_basis"},
    {k: v for k, v in CREDIT.items() if k != "frequency"},
    {**CREDIT, "unknown": 1},
])
def test_adjustment_validation(bad):
    with pytest.raises(ValidationError):
        TaxAdjustment.model_validate(bad)


def test_settings_validation_requires_unique_ids_and_a_whitelisted_nonempty_change():
    with pytest.raises(ValidationError):
        TaxSettings.model_validate({"adjustments": [CREDIT, CREDIT]})
    with pytest.raises(ValidationError):
        TaxSettings.model_validate({"scheduled_changes": [{"year": 2030, "settings": {}}]})
    with pytest.raises(ValidationError):
        TaxSettings.model_validate({"scheduled_changes": [{"year": 2030, "settings": {"settlement_lag_years": 1}}]})
    with pytest.raises(ValidationError):
        TaxSettings.model_validate({"scheduled_changes": [
            {"year": 2030, "milestone_id": "m", "settings": {"mode": "flat"}}]})
    surcharge = {"id": "s", "kind": "surcharge", "scope": "state", "rate": .01, "base": "taxable_income",
                 "max_amount": 500, "amount_basis": "today", "frequency": "every_n_years", "interval_years": 2}
    assert TaxAdjustment.model_validate(surcharge).model_dump() == {**surcharge, "name": "", "owner": "household"}


def _request(**tax_settings):
    return dict(plan_id=str(uuid.uuid4()), birth_year=1975, start_year=2026,
                milestones=[{"id": "m1", "name": "Retire", "trigger_type": "age", "trigger_value": 60}],
                tax_settings=tax_settings)


def test_stateless_request_validates_milestones_and_spouse():
    ok = PlanDataRequest.model_validate(_request(adjustments=[_deduction("m1")]))
    assert ok.tax_settings.adjustments[0].end_milestone_id == "m1"
    with pytest.raises(ValidationError):
        PlanDataRequest.model_validate(_request(adjustments=[_deduction("m2")]))
    with pytest.raises(ValidationError):
        PlanDataRequest.model_validate(_request(scheduled_changes=[
            {"milestone_id": "m2", "settings": {"mode": "flat"}}]))
    with pytest.raises(ValidationError):
        PlanDataRequest.model_validate(_request(adjustments=[{**CREDIT, "owner": "spouse"}]))


async def test_stateless_projection_matches_persisted_semantics(client):
    body = {**_request(adjustments=[CREDIT]), "income_streams": [
        {"id": "w", "name": "Wages", "annual_amount": 90_000, "withholding_percent": 20}]}
    response = await client.post("/api/simulate/stateless", json=body)
    assert response.status_code == 200, response.text
    rows = {row["year"]: row for row in response.json()["yearly_snapshots"]}
    assert rows[2027]["tax_adjustment_credits"] == pytest.approx(1200)
    assert rows[2028]["tax_adjustment_credits"] == 0
