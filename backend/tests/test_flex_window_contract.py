"""Saved and stateless flexible-spending windows must refer to their plan."""
from uuid import uuid4

import pytest


@pytest.mark.anyio
async def test_flex_window_save_copy_and_reference_validation(client):
    plan = (await client.post("/api/plans", json={"name": "Flex contract", "birth_year": 1980,
        "birth_month": 1, "plan_type": "FIXED_DATE", "start_date": "2026-09-09"})).json()
    path = f"/api/plans/{plan['id']}"
    milestones = [(await client.post(f"{path}/milestones", json={"name": name,
        "trigger_type": "date", "trigger_date": day})).json()
        for name, day in (("Start", "2028-01-01"), ("End", "2030-01-01"))]
    rules = {"performance_mode": "all_time_high", "interpolation": "linear", "spending_floor": .7,
        "thresholds": [{"threshold": -.1, "reduction": .1}, {"threshold": -.2, "reduction": .3}],
        "start_milestone_id": milestones[0]["id"], "end_milestone_id": milestones[1]["id"]}
    saved = await client.put(path, json={"spending_rules": rules})
    assert saved.status_code == 200, saved.text
    read = (await client.get(path)).json()["spending_rules"]
    assert all(read[key] == value for key, value in rules.items())
    copied = (await client.post(f"{path}/duplicate")).json()
    copy_ids = {m["name"]: m["id"] for m in copied["milestones"]}
    assert copied["spending_rules"]["start_milestone_id"] == copy_ids["Start"]
    assert copy_ids["Start"] != rules["start_milestone_id"]
    for invalid in ({"start_milestone_id": str(uuid4())},
                    {"start_milestone_id": milestones[1]["id"], "end_milestone_id": milestones[0]["id"]}):
        response = await client.put(path, json={"spending_rules": {**rules, **invalid}})
        assert response.status_code == 422, response.text
    assert (await client.get(path)).json()["spending_rules"] == read
    assert (await client.delete(f"{path}/milestones/{milestones[0]['id']}")).status_code == 409
    stateless = {"plan_id": plan["id"], "birth_year": 1980, "birth_month": 1,
        "start_year": 2026, "life_expectancy": 50, "milestones": milestones, "spending_rules": rules}
    response = await client.post("/api/simulate/stateless", json=stateless)
    assert response.status_code == 200, response.text
    stateless["spending_rules"] = {**rules, "start_milestone_id": "missing"}
    assert (await client.post("/api/simulate/stateless", json=stateless)).status_code == 422
