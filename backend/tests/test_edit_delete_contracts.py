"""Plan edits and deletes keep saved data and dependencies intact.

A profile patch from one tab keeps fields another tab saved; an income that a
payroll allocation rule funds cannot be deleted until the rule is removed, and
the allocation revision contract still holds afterwards; an income is deleted
only through the plan that owns it.
"""
import pytest


@pytest.mark.anyio
async def test_profile_field_patch_preserves_another_tabs_saved_fields(client):
    plan = (await client.post("/api/plans", json={"name": "Original", "birth_year": 1990, "state_code": "TX"})).json()
    url = f"/api/plans/{plan['id']}"
    assert (await client.put(url, json={"name": "New name", "birth_year": 1985})).status_code == 200
    response = await client.put(url, json={"state_code": "FL"})
    assert response.status_code == 200, response.text
    reloaded = (await client.get(url)).json()
    assert (reloaded["name"], reloaded["birth_year"], reloaded["state_code"]) == ("New name", 1985, "FL")


@pytest.mark.anyio
async def test_payroll_delete_guard_preserves_rules_and_allows_repair_then_delete(client):
    plan = (await client.post("/api/plans", json={"name": "Payroll deletion", "birth_year": 1990})).json()
    base = f"/api/plans/{plan['id']}"
    income = (await client.post(f"{base}/incomes", json={"name": "Salary", "annual_amount": 100000})).json()
    retirement = (await client.post("/api/accounts", json={"name": "401k", "account_type": "traditional_401k", "balance": 0})).json()
    cash = (await client.post("/api/accounts", json={"name": "Emergency Fund", "account_type": "savings", "balance": 0})).json()
    rules = [
        {"priority_rank": 1, "priority_type": "income_percent", "source_income_id": income["id"], "target_account_id": retirement["id"], "employee_rate": 10},
        {"priority_rank": 2, "priority_type": "contribution", "target_account_id": cash["id"], "max_annual_amount": 20000},
    ]
    priorities = f"{base}/priorities"
    revision = (await client.get(priorities)).json()["revision"]
    saved = await client.put(priorities, json={"expected_revision": revision, "items": rules})
    assert saved.status_code == 200, saved.text
    saved = saved.json()
    deletion = await client.delete(f"{base}/incomes/{income['id']}")
    assert deletion.status_code == 409, deletion.text
    assert deletion.json()["error"]["code"] == "CONFLICT"
    assert "Income allocation" in deletion.json()["error"]["message"]
    assert (await client.get(priorities)).json() == saved
    assert len((await client.get(f"{base}/incomes")).json()) == 1

    # The previously blocked unrelated allocation save now remains possible.
    rules[1]["max_annual_amount"] = 21000
    changed = await client.put(priorities, json={"expected_revision": saved["revision"], "items": rules})
    assert changed.status_code == 200, changed.text
    # Explicitly remove the payroll dependency, then retry deletion.
    repaired = await client.put(priorities, json={"expected_revision": changed.json()["revision"], "items": [rules[1]]})
    assert repaired.status_code == 200, repaired.text
    assert (await client.delete(f"{base}/incomes/{income['id']}")).status_code == 204
    assert (await client.get(f"{base}/incomes")).json() == []
    latest = (await client.get(priorities)).json()
    assert latest["revision"] == repaired.json()["revision"] + 1
    assert len(latest["items"]) == 1
    assert latest["items"][0]["max_annual_amount"] == 21000
    # A pre-delete draft is still rejected by the existing concurrency contract.
    stale = await client.put(priorities, json={"expected_revision": repaired.json()["revision"], "items": rules})
    assert stale.status_code == 409
    assert (await client.get(priorities)).json() == latest


@pytest.mark.anyio
async def test_income_delete_remains_plan_scoped(client):
    first = (await client.post("/api/plans", json={"name": "First", "birth_year": 1990})).json()
    second = (await client.post("/api/plans", json={"name": "Second", "birth_year": 1990})).json()
    income = (await client.post(f"/api/plans/{first['id']}/incomes", json={"name": "Salary", "annual_amount": 100000})).json()
    assert (await client.delete(f"/api/plans/{second['id']}/incomes/{income['id']}")).status_code == 404
    assert len((await client.get(f"/api/plans/{first['id']}/incomes")).json()) == 1
