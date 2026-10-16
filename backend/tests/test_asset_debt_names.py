"""Whitespace identities must never replace a saved property/debt name."""
import pytest


@pytest.mark.anyio
@pytest.mark.parametrize("resource,payload", [
    ("liabilities", {"name": "UX Loan", "principal_balance": 10000, "interest_rate": 5.5, "term_months": 12}),
    ("real-assets", {"name": "UX Cabin", "current_value": 250000}),
])
async def test_blank_name_rejection_and_recovery(client, resource, payload):
    plan = (await client.post("/api/plans", json={"name": "Name validation", "birth_year": 1990})).json()
    path = f"/api/plans/{plan['id']}/{resource}"
    created = await client.post(path, json=payload)
    assert created.status_code == 201
    item = created.json()
    for blank in ["   ", "\t\n", "\u00a0\u2003"]:
        rejected = await client.put(f"{path}/{item['id']}", json={"name": blank})
        assert rejected.status_code == 422
        error = rejected.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["details"][0]["field"] == "name"
        assert "Enter a name containing at least one non-space character" in error["details"][0]["reason"]
        assert (await client.get(f"{path}/{item['id']}")).json() == item
        assert (await client.post(path, json={**payload, "name": blank})).status_code == 422
    assert len((await client.get(path)).json()) == 1
    corrected = await client.put(f"{path}/{item['id']}", json={"name": "  Corrected name  "})
    assert corrected.status_code == 200
    assert (await client.get(f"{path}/{item['id']}")).json()["name"] == "  Corrected name  "
    # An omitted name in a partial update remains supported.
    assert (await client.put(f"{path}/{item['id']}", json={})).status_code == 200
