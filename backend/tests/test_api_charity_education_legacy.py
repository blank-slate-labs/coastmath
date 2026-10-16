"""Saved-plan round trips for 529 expenses, share gifts, estate detail and tax options."""

import pytest

from tests.scenario_support import post


@pytest.mark.anyio
async def test_share_gift_round_trip_and_source_rules(client):
    plan = await post(client, "/plans", {"name": "Gifts", "birth_year": 1960, "life_expectancy": 70})
    root = "/plans/" + plan["id"]
    brokerage = await post(client, root + "/accounts", {
        "name": "Brokerage", "account_type": "taxable_brokerage", "balance": 300_000, "cost_basis": 100_000})
    cash = await post(client, root + "/accounts", {"name": "Cash", "account_type": "checking", "balance": 50_000})

    legacy = await post(client, root + "/charities", {"name": "Church", "entity_type": "direct", "annual_amount": 1_000})
    assert legacy["funding"] == "cash"

    payload = {"name": "DAF", "entity_type": "daf", "annual_amount": 20_000,
               "funding": "appreciated_shares", "source_account_id": brokerage["id"]}
    for invalid in ({"source_account_id": cash["id"]}, {"source_account_id": None}, {"entity_type": "qcd"}):
        response = await client.post("/api" + root + "/charities", json={**payload, **invalid})
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    gift = await post(client, root + "/charities", payload)
    assert gift["funding"] == "appreciated_shares"
    assert (await client.get("/api" + root + "/charities/" + gift["id"])).json()["funding"] == "appreciated_shares"

    # The source account cannot change type or be deleted while it funds the gift.
    changed = await client.put("/api" + root + "/accounts/" + brokerage["id"], json={"account_type": "checking"})
    assert changed.status_code == 409
    assert "gift of shares" in changed.json()["error"]["message"]
    deleted = await client.delete("/api" + root + "/accounts/" + brokerage["id"])
    assert deleted.status_code == 409

    # Back to cash: clear the source; an explicit null funding is ignored.
    patched = await client.patch("/api" + root + "/charities/" + gift["id"],
                                 json={"funding": "cash", "source_account_id": None})
    assert patched.status_code == 200, patched.text
    assert patched.json()["funding"] == "cash"
    kept = await client.patch("/api" + root + "/charities/" + gift["id"], json={"funding": None, "annual_amount": 5})
    assert kept.status_code == 200 and kept.json()["funding"] == "cash"

    result = await client.post("/api" + root + "/simulate")
    assert result.status_code == 200, result.text


@pytest.mark.anyio
async def test_education_expense_529_basis_estate_and_tax_options_round_trip(client):
    plan = await post(client, "/plans", {"name": "College", "birth_year": 1975, "life_expectancy": 60,
                                         "state_code": "NY"})
    root = "/plans/" + plan["id"]
    edu = await post(client, root + "/accounts", {
        "name": "529", "account_type": "five_twenty_nine", "balance": 80_000, "cost_basis": 50_000})
    assert edu["cost_basis"] == 50_000
    other = await post(client, root + "/accounts", {
        "name": "Savings", "account_type": "savings", "balance": 5_000_000, "cost_basis": 500})
    assert other["cost_basis"] is None

    expense = await post(client, root + "/expenses", {"name": "Tuition", "annual_amount": 20_000,
                                                      "qualified_education": True})
    assert expense["qualified_education"] is True
    plain = await post(client, root + "/expenses", {"name": "Living", "annual_amount": 30_000})
    assert plain["qualified_education"] is False
    patched = await client.put("/api" + root + "/expenses/" + plain["id"], json={"qualified_education": True})
    assert patched.status_code == 200 and patched.json()["qualified_education"] is True

    estate = {"heir_capital_gains_rate": 0.15, "estate_selling_cost_percent": 6,
              "charitable_bequest_percent": 10, "joint_account_step_up": True, "step_up_basis_on_death": False}
    tax = {"medical_expense_deductions": True, "state_529_deduction": True}
    saved = await client.put("/api" + root, json={"estate_settings": estate, "tax_settings": tax})
    assert saved.status_code == 200, saved.text
    body = (await client.get("/api" + root)).json()
    for key, value in estate.items():
        assert body["estate_settings"][key] == value
    assert body["tax_settings"]["medical_expense_deductions"] is True
    assert body["tax_settings"]["state_529_deduction"] is True

    bad = await client.put("/api" + root, json={"estate_settings": {**estate, "charitable_bequest_percent": 101}})
    assert bad.status_code == 422

    # Settings documents without the new keys stay as they were.
    await client.put("/api" + root, json={"estate_settings": {"step_up_basis_on_death": True},
                                          "tax_settings": {"mode": "detailed"}})
    body = (await client.get("/api" + root)).json()
    assert "charitable_bequest_percent" not in body["estate_settings"]
    assert "medical_expense_deductions" not in body["tax_settings"]

    await client.put("/api" + root, json={"estate_settings": estate})
    result = await client.post("/api" + root + "/simulate")
    assert result.status_code == 200, result.text
    legacy = result.json()["metadata"]["net_legacy"]
    assert legacy["education_savings_outside_estate"] > 0
    assert legacy["charitable_bequest"] > 0
