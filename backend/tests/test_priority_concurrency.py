"""Priority replacements require the current revision and return ranked items."""
import pytest


@pytest.mark.anyio
async def test_api_revision_conflict_and_missing_precondition(client):
    plan = (await client.post("/api/plans", json={"name": "Revision QA", "birth_year": 1990})).json()
    url = f"/api/plans/{plan['id']}/priorities"
    baseline = (await client.get(url)).json()
    assert baseline == {"items": [], "revision": 0}
    first = await client.put(url, json={"items": [], "expected_revision": 0})
    assert first.status_code == 200
    stale = await client.put(url, json={"items": [], "expected_revision": 0})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT"
    missing = await client.put(url, json={"items": []})
    assert missing.status_code == 422
    assert (await client.get(url)).json() == first.json()


@pytest.mark.anyio
async def test_priority_response_is_ordered_and_fk_deletes_invalidate_baseline(client):
    plan = (await client.post("/api/plans", json={"name": "References QA", "birth_year": 1990})).json()
    account = (await client.post("/api/accounts", json={"name": "QA cash", "account_type": "savings", "balance": 0})).json()
    base = f"/api/plans/{plan['id']}"
    response = await client.put(base + "/priorities", json={"expected_revision": 0, "items": [
        {"priority_rank": 2, "target_account_id": account["id"]},
        {"priority_rank": 1, "target_account_id": account["id"], "max_annual_amount": 100},
    ]})
    assert response.status_code == 200
    assert [p["priority_rank"] for p in response.json()["items"]] == [1, 2]
    for expected, resource, body in [
        (2, "incomes", {"name": "QA salary", "annual_amount": 10000}),
        (3, "milestones", {"name": "QA future", "trigger_type": "age", "trigger_value": 50}),
    ]:
        created = await client.post(base + "/" + resource, json=body)
        assert created.status_code == 201, created.text
        removed = await client.delete(base + "/" + resource + "/" + created.json()["id"])
        assert removed.status_code == 204
        latest = (await client.get(base + "/priorities")).json()
        assert latest["revision"] == expected
        assert latest["items"] == response.json()["items"]
        stale = await client.put(base + "/priorities", json={"expected_revision": 1, "items": []})
        assert stale.status_code == 409
