"""POST /api/plans/{plan_id}/tax-suggestions."""

import uuid

import pytest

pytestmark = pytest.mark.anyio


async def test_suggestions_route_returns_improving_rules_and_counts_use(client, db_session, test_user, recorded_usage):
    plan = (await client.post("/api/plans", json={"name": "Suggest", "birth_year": 1980, "plan_type": "NOW",
                                                  "life_expectancy": 90, "filing_status": "single"})).json()
    pid = plan["id"]
    k401 = (await client.post("/api/accounts", json={"name": "401(k)", "account_type": "traditional_401k", "balance": 50_000})).json()
    cash = (await client.post("/api/accounts", json={"name": "Cash", "account_type": "checking", "balance": 20_000})).json()
    wage = (await client.post(f"/api/plans/{pid}/incomes", json={"name": "Salary", "annual_amount": 180_000})).json()
    assert (await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living", "annual_amount": 60_000})).status_code == 201
    r = await client.put(f"/api/plans/{pid}/drawdown-order", json={"items": [{"rank": 1, "source_account_id": cash["id"]}]})
    assert r.status_code in (200, 201), r.text

    r = await client.post(f"/api/plans/{pid}/tax-suggestions")
    assert r.status_code == 200, r.text
    suggestions = r.json()["suggestions"]
    assert r.json()["pre_tax_discount_rate"] == 0.24
    by_key = {s["key"]: s for s in suggestions}
    assert "max_401k" in by_key
    max_401k = by_key["max_401k"]
    assert max_401k["title"] == "Max 401(k)"
    assert max_401k["end_net_worth_change"] > 0
    assert isinstance(max_401k["lifetime_tax_change"], float)
    [rule] = max_401k["rules"]
    assert rule["change"] == "add" and rule["priority_type"] == "pre_tax_contribution"
    assert rule["target_account_id"] == k401["id"] and rule["source_income_id"] == wage["id"]
    # Every suggestion improves end net worth or lowers lifetime taxes without lowering net worth.
    assert all(s["end_net_worth_change"] >= -1 for s in suggestions)

    # The suggested rule saves as an allocation rule.
    revision = (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"]
    item = {k: v for k, v in rule.items() if k != "change"}
    r = await client.put(f"/api/plans/{pid}/priorities", json={"expected_revision": revision, "items": [item]})
    assert r.status_code == 200, r.text

    assert recorded_usage.count("tax_suggestions") == 1


async def test_suggestions_route_404s_for_an_unknown_plan(client):
    r = await client.post(f"/api/plans/{uuid.uuid4()}/tax-suggestions")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
