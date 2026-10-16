"""Contribution room settings (intl_settings.starting_room, prior_year_earned_income) through the API,
with the test-only QZ pack (tests/intl_fixture_pack.py)."""
import uuid

import pytest

from app.engine.plan_converter import plan_to_engine_data
from app.models.account import CurrentAccount
from app.models.plan import Plan
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from tests.api_support import create_plan

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("fixture_pack")]

ROOM = {"starting_room": [{"kind": "QZ:free_saver", "owner": "self", "amount": 25_000},
                          {"kind": "QZ:pension_saver", "owner": "spouse", "amount": 40_000}],
        "prior_year_earned_income": {"self": 90_000}}


async def _plan(client, **fields):
    return await create_plan(client, **{"name": "North", "birth_year": 1975, "tax_country": "QZ",
                                        "tax_region": "N", "currency": "EUR", **fields})


async def test_room_settings_persist_convert_and_duplicate(client, db_session):
    plan = await _plan(client, intl_settings=ROOM)
    assert plan["intl_settings"]["starting_room"][1] == {"kind": "QZ:pension_saver", "owner": "spouse", "amount": 40_000.0}
    assert plan["intl_settings"]["prior_year_earned_income"] == {"self": 90_000.0}
    read = (await client.get(f"/api/plans/{plan['id']}")).json()
    assert read["intl_settings"]["starting_room"] == plan["intl_settings"]["starting_room"]
    row = db_session.get(Plan, uuid.UUID(plan["id"]))
    data = plan_to_engine_data(row, db_session.query(CurrentAccount).all())
    assert data.intl_settings["starting_room"][0]["kind"] == "QZ:free_saver"
    assert data.intl_settings["prior_year_earned_income"] == {"self": 90_000.0}
    copied = await client.post(f"/api/plans/{plan['id']}/duplicate")
    assert copied.status_code == 201, copied.text
    assert copied.json()["intl_settings"]["starting_room"] == plan["intl_settings"]["starting_room"]
    # Clearing the room keeps the other settings.
    cleared = await client.put(f"/api/plans/{plan['id']}", json={"intl_settings": {"benefits": []}})
    assert cleared.status_code == 200, cleared.text
    assert "starting_room" not in cleared.json()["intl_settings"]


async def test_plans_without_room_settings_store_no_new_keys(client, db_session):
    plan = await _plan(client, intl_settings={"benefits": []})
    row = db_session.get(Plan, uuid.UUID(plan["id"]))
    assert set(row.intl_settings) == {"benefits", "custom_regime", "wealth_tax", "transaction_tax"}


@pytest.mark.parametrize("settings", [
    {"starting_room": [{"kind": "QZ:general", "amount": 1}]},
    {"starting_room": [{"kind": "QZ:free_saver", "amount": -1}]},
    {"prior_year_earned_income": {"self": -1}},
])
async def test_invalid_room_settings_are_rejected(client, settings):
    response = await client.post("/api/plans", json={"name": "Bad", "birth_year": 1975, "tax_country": "QZ",
                                                     "intl_settings": settings})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_switching_country_keeps_saved_room(client):
    """Room for a kind of a country the plan left is kept (unused), so it never blocks a country switch."""
    plan = await _plan(client, intl_settings=ROOM)
    switched = await client.put(f"/api/plans/{plan['id']}", json={"tax_country": "US", "currency": "USD"})
    assert switched.status_code == 200, switched.text
    assert switched.json()["intl_settings"]["starting_room"] == plan["intl_settings"]["starting_room"]


def test_stateless_request_carries_room_settings():
    request = PlanDataRequest.model_validate({
        "plan_id": str(uuid.uuid4()), "birth_year": 1975, "start_year": 2026, "tax_country": "QZ",
        "tax_region": "N", "currency": "EUR", "intl_settings": ROOM})
    data = request_to_engine_data(request)
    assert data.intl_settings["starting_room"][0] == {"kind": "QZ:free_saver", "owner": "self", "amount": 25_000.0}
