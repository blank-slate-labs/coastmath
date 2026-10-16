"""Opening-value preconditions protect saved edits without blocking field merges."""
import pytest


@pytest.mark.anyio
@pytest.mark.parametrize("field,original,newer,stale", [
    ("name", "UX Cedar rent revised", "UX Cedar saved B", "UX Cedar local A"),
    ("annual_amount", 18000, 21000, 19000),
])
async def test_conflict_retains_saved_value_and_reviewed_retry(client, field, original, newer, stale):
    plan = (await client.post("/api/plans", json={"name": "Cedar", "birth_year": 1990})).json()
    base = f"/api/plans/{plan['id']}/expenses"
    expense = (await client.post(base, json={"name": "UX Cedar rent revised", "annual_amount": 18000})).json()
    path = f"{base}/{expense['id']}"
    assert (await client.put(path, json={field: newer})).status_code == 200
    rejected = await client.put(path, json={field: stale, "expected_values": {field: original}})
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "CONFLICT"
    assert rejected.json()["error"]["details"][0]["field"] == field
    assert (await client.get(base)).json()[0][field] == newer
    # Retrying without review still cannot overwrite the intervening save.
    assert (await client.put(path, json={field: stale, "expected_values": {field: original}})).status_code == 409
    assert (await client.put(path, json={field: stale, "expected_values": {field: newer}})).status_code == 200
    assert (await client.get(base)).json()[0][field] == stale


@pytest.mark.anyio
async def test_nonconflicting_merge_null_and_complete_preconditions(client):
    plan = (await client.post("/api/plans", json={"name": "Cedar", "birth_year": 1990})).json()
    base = f"/api/plans/{plan['id']}/expenses"
    expense = (await client.post(base, json={"name": "Rent", "annual_amount": 18000, "growth_rate": 2})).json()
    path = f"{base}/{expense['id']}"
    await client.put(path, json={"annual_amount": 21000})
    merged = await client.put(path, json={"name": "Revised", "expected_values": {"name": "Rent"}})
    assert merged.status_code == 200
    assert merged.json()["annual_amount"] == 21000
    cleared = await client.put(path, json={"growth_rate": None, "expected_values": {"growth_rate": 2}})
    assert cleared.status_code == 200 and cleared.json()["growth_rate"] is None
    # An opted-in caller must supply a baseline for every field it writes.
    assert (await client.put(path, json={"name": "Bad", "expected_values": {}})).status_code == 422
    assert (await client.put(path, json={"name": "Bad", "expected_values": {"unknown": 1}})).status_code == 422
    assert (await client.get(base)).json()[0]["name"] == "Revised"
