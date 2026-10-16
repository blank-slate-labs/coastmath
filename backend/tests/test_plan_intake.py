"""POST /plans/{id}/intake: new-plan goals become plan items in one transaction."""
import uuid

import pytest

from app.auth.router import create_jwt
from app.models.user import User
from tests.api_support import assert_error, create_plan

pytestmark = pytest.mark.anyio


async def new_plan(client, **overrides) -> dict:
    return await create_plan(client, **{"name": "Goals", "retirement_milestone_age": 65, **overrides})


async def intake(client, plan_id: str, **answers):
    return await client.post(f"/api/plans/{plan_id}/intake", json=answers)


async def items(client, plan_id: str) -> tuple[dict, dict, dict]:
    milestones = (await client.get(f"/api/plans/{plan_id}/milestones")).json()
    expenses = (await client.get(f"/api/plans/{plan_id}/expenses")).json()
    charities = (await client.get(f"/api/plans/{plan_id}/charities")).json()
    return ({m["name"]: m for m in milestones}, {e["name"]: e for e in expenses}, {c["name"]: c for c in charities})


ANSWERS = {
    "retirement_age": 60, "retirement_spending": 80000, "travel_budget": 15000,
    "travel_until_age": 80, "charitable_giving": 5000, "legacy_target": 1_000_000,
}


async def test_each_answer_maps_to_its_plan_item(client):
    plan = await new_plan(client)
    response = await intake(client, plan["id"], **ANSWERS)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == plan["id"]

    milestones, expenses, charities = await items(client, plan["id"])
    assert set(milestones) == {"Retirement", "Travel ends"}
    retirement, travel_end = milestones["Retirement"], milestones["Travel ends"]
    # The milestone seeded at 65 is updated in place, not duplicated.
    assert retirement["id"] == plan["milestones"][0]["id"]
    assert (retirement["trigger_type"], float(retirement["trigger_value"])) == ("age", 60.0)
    assert (travel_end["trigger_type"], float(travel_end["trigger_value"])) == ("age", 80.0)

    assert set(expenses) == {"Retirement spending", "Travel"}
    spending, travel = expenses["Retirement spending"], expenses["Travel"]
    assert (spending["annual_amount"], spending["category"], spending["inflation_linked"]) == (80000, "essential", True)
    assert (spending["start_milestone_id"], spending["end_milestone_id"]) == (retirement["id"], None)
    assert (travel["annual_amount"], travel["category"], travel["inflation_linked"]) == (15000, "discretionary", True)
    assert (travel["start_milestone_id"], travel["end_milestone_id"]) == (retirement["id"], travel_end["id"])

    assert list(charities) == ["Charitable giving"]
    giving = charities["Charitable giving"]
    assert (giving["entity_type"], giving["annual_amount"]) == ("direct", 5000)
    assert (giving["start_milestone_id"], giving["end_milestone_id"]) == (retirement["id"], None)

    # The legacy target is saved on the plan in today's dollars.
    assert response.json()["estate_settings"]["legacy_target"] == 1_000_000

    # The engine accepts the result.
    assert (await client.post(f"/api/plans/{plan['id']}/simulate")).status_code == 200


async def test_blank_answers_change_nothing(client):
    plan = await new_plan(client)
    before = await items(client, plan["id"])
    for body in ({}, dict.fromkeys(ANSWERS)):
        response = await client.post(f"/api/plans/{plan['id']}/intake", json=body)
        assert response.status_code == 200, response.text
        assert await items(client, plan["id"]) == before


async def test_resubmitting_updates_the_same_items(client):
    plan = await new_plan(client)
    assert (await intake(client, plan["id"], **ANSWERS)).status_code == 200
    first = await items(client, plan["id"])
    changed = {**ANSWERS, "retirement_spending": 90000, "travel_until_age": 75, "charitable_giving": 7000}
    assert (await intake(client, plan["id"], **changed)).status_code == 200
    assert (await intake(client, plan["id"], **changed)).status_code == 200
    milestones, expenses, charities = await items(client, plan["id"])

    assert {name: row["id"] for name, row in milestones.items()} == {name: row["id"] for name, row in first[0].items()}
    assert {name: row["id"] for name, row in expenses.items()} == {name: row["id"] for name, row in first[1].items()}
    assert {name: row["id"] for name, row in charities.items()} == {name: row["id"] for name, row in first[2].items()}
    assert len((await client.get(f"/api/plans/{plan['id']}/expenses")).json()) == 2
    assert expenses["Retirement spending"]["annual_amount"] == 90000
    assert float(milestones["Travel ends"]["trigger_value"]) == 75.0
    assert charities["Charitable giving"]["annual_amount"] == 7000

    # A later answer for one goal leaves the others as they were.
    assert (await intake(client, plan["id"], travel_budget=12000)).status_code == 200
    _, expenses, charities = await items(client, plan["id"])
    assert expenses["Travel"]["annual_amount"] == 12000 and expenses["Travel"]["end_milestone_id"] is None
    assert expenses["Retirement spending"]["annual_amount"] == 90000
    assert charities["Charitable giving"]["annual_amount"] == 7000


async def test_retirement_age_creates_the_milestone_when_missing(client):
    plan = await new_plan(client, retirement_milestone_age=None)
    assert plan["milestones"] == []
    assert (await intake(client, plan["id"], retirement_age=62)).status_code == 200
    milestones, expenses, charities = await items(client, plan["id"])
    assert [(name, float(m["trigger_value"])) for name, m in milestones.items()] == [("Retirement", 62.0)]
    assert expenses == {} and charities == {}


async def test_legacy_target_keeps_other_estate_settings_and_needs_no_retirement(client):
    plan = await new_plan(client, retirement_milestone_age=None)
    estate = {"settlement_cost_fixed": 5000, "household_lifecycle": "legacy_primary_endpoint"}
    assert (await client.put(f"/api/plans/{plan['id']}", json={"estate_settings": estate})).status_code == 200
    response = await intake(client, plan["id"], legacy_target=250_000)
    assert response.status_code == 200, response.text
    saved = response.json()["estate_settings"]
    assert saved["legacy_target"] == 250_000 and saved["settlement_cost_fixed"] == 5000
    assert saved["household_lifecycle"] == "legacy_primary_endpoint"
    assert (await intake(client, plan["id"], legacy_target=300_000)).json()["estate_settings"]["legacy_target"] == 300_000
    assert (await intake(client, plan["id"], legacy_target=None)).json()["estate_settings"]["legacy_target"] == 300_000
    assert await items(client, plan["id"]) == ({}, {}, {})


async def test_retirement_items_need_a_retirement_milestone(client):
    plan = await new_plan(client, retirement_milestone_age=None)
    assert_error(await intake(client, plan["id"], retirement_spending=60000), 422, "VALIDATION_ERROR", "retirement_age")
    assert await items(client, plan["id"]) == ({}, {}, {})


async def test_invalid_answers_write_nothing(client):
    plan = await new_plan(client)
    before = await items(client, plan["id"])
    # Travel cannot end before retirement starts; the earlier writes roll back.
    response = await intake(client, plan["id"], retirement_age=70, retirement_spending=60000,
                            travel_budget=10000, travel_until_age=65)
    assert_error(response, 422, "VALIDATION_ERROR")
    assert await items(client, plan["id"]) == before
    assert_error(await intake(client, plan["id"], travel_until_age=80), 422, "VALIDATION_ERROR")
    assert_error(await intake(client, plan["id"], retirement_spending=-1), 422, "VALIDATION_ERROR")
    assert_error(await intake(client, plan["id"], legacy_target=0), 422, "VALIDATION_ERROR")
    assert_error(await intake(client, plan["id"], heirs=1), 422, "VALIDATION_ERROR")
    assert await items(client, plan["id"]) == before


async def test_other_accounts_cannot_apply_intake(client, db_session, test_user):
    plan = await new_plan(client)
    other = User(is_anonymous=True, settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set("session", create_jwt(other.id))
    assert_error(await intake(client, plan["id"], **ANSWERS), 404, "NOT_FOUND")
    assert_error(await intake(client, str(uuid.uuid4()), **ANSWERS), 404, "NOT_FOUND")
    client.cookies.set("session", create_jwt(test_user.id))
    milestones, expenses, charities = await items(client, plan["id"])
    assert list(milestones) == ["Retirement"] and expenses == {} and charities == {}
