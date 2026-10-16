"""The same milestone as start and end with no months is an empty window: it never pays."""
import uuid

import pytest

from app.models.income import IncomeStream
from tests.api_support import create_plan


async def _plan_with_milestone(client):
    pid = (await create_plan(client, name="Empty window", birth_year=1980))["id"]
    milestone = (await client.post(f"/api/plans/{pid}/milestones",
                                   json={"name": "Retirement", "trigger_type": "age", "trigger_value": 60})).json()
    return pid, milestone["id"]


@pytest.mark.anyio
@pytest.mark.parametrize("resource", ["incomes", "expenses"])
async def test_same_milestone_without_months_is_refused(client, resource):
    pid, mid = await _plan_with_milestone(client)
    path = f"/api/plans/{pid}/{resource}"
    body = {"name": "Item", "annual_amount": 10_000, "start_milestone_id": mid, "end_milestone_id": mid}
    refused = await client.post(path, json=body)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"][0]["field"] == "end_milestone_id"

    # Months make it a window inside the trigger year.
    bounded = await client.post(path, json={**body, "start_month": 3, "end_month": 8})
    assert bounded.status_code == 201, bounded.text

    # Clearing the months on update empties it again.
    item_id = bounded.json()["id"]
    cleared = await client.put(f"{path}/{item_id}", json={"start_month": None, "end_month": None})
    assert cleared.status_code == 422, cleared.text


@pytest.mark.anyio
async def test_unrelated_update_of_a_saved_empty_window_still_saves(client, db_session):
    pid, mid = await _plan_with_milestone(client)
    path = f"/api/plans/{pid}/incomes"
    created = await client.post(path, json={"name": "Wages", "annual_amount": 10_000, "start_milestone_id": mid})
    assert created.status_code == 201, created.text
    income_id = created.json()["id"]
    # A record saved before the rule: written directly, as the API now refuses it.
    income = db_session.get(IncomeStream, uuid.UUID(income_id))
    income.end_milestone_id = uuid.UUID(mid)
    db_session.commit()
    renamed = await client.put(f"{path}/{income_id}", json={"name": "Renamed"})
    assert renamed.status_code == 200, renamed.text
