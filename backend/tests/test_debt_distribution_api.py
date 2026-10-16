"""API round trips, ownership checks and plan duplication for debt and distribution settings."""

from __future__ import annotations

import pytest

from tests.api_support import create_plan, save_priorities


async def _plan(client, name="Debt API"):
    return (await create_plan(client, name=name, birth_year=1980))["id"]


async def _loan(client, pid, **extra):
    body = {"name": "Car", "principal_balance": 20000, "interest_rate": 6, "term_months": 60, **extra}
    response = await client.post(f"/api/plans/{pid}/liabilities", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _account(client, kind, name, balance, **extra):
    response = await client.post("/api/accounts", json={"name": name, "account_type": kind, "balance": balance, **extra})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.anyio
async def test_debt_payment_rule_round_trips_and_runs(client):
    pid = await _plan(client)
    loan = await _loan(client, pid)
    saved = await save_priorities(client, pid, [{
        "priority_rank": 1, "priority_type": "debt_payment", "target_liability_id": loan["id"],
        "max_annual_amount": 3000}])
    assert saved.status_code == 200, saved.text
    row = saved.json()["items"][0]
    assert row["target_liability_id"] == loan["id"] and row["target_account_id"] is None
    assert (await client.get(f"/api/plans/{pid}/priorities")).json()["items"][0]["target_liability_id"] == loan["id"]


@pytest.mark.anyio
async def test_debt_payment_rule_requires_a_loan_in_the_same_plan(client):
    pid, other = await _plan(client), await _plan(client, "Other plan")
    foreign = await _loan(client, other)
    url = f"/api/plans/{pid}/priorities"
    before = (await client.get(url)).json()
    for target in (foreign["id"], "00000000-0000-4000-8000-000000000001"):
        response = await save_priorities(client, pid, [{
            "priority_rank": 1, "priority_type": "debt_payment", "target_liability_id": target}])
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    missing = await save_priorities(client, pid, [{"priority_rank": 1, "priority_type": "debt_payment"}])
    assert missing.status_code == 422
    assert (await client.get(url)).json() == before


@pytest.mark.anyio
async def test_stale_revision_is_a_conflict_and_keeps_saved_rules(client):
    pid = await _plan(client)
    loan = await _loan(client, pid)
    url = f"/api/plans/{pid}/priorities"
    first = (await client.get(url)).json()
    item = {"priority_rank": 1, "priority_type": "debt_payment", "target_liability_id": loan["id"]}
    assert (await client.put(url, json={"expected_revision": first["revision"], "items": [item]})).status_code == 200
    stale = await client.put(url, json={"expected_revision": first["revision"], "items": []})
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "CONFLICT"
    assert len((await client.get(url)).json()["items"]) == 1


@pytest.mark.anyio
async def test_referenced_loan_cannot_be_deleted(client):
    pid = await _plan(client)
    loan = await _loan(client, pid)
    assert (await save_priorities(client, pid, [{
        "priority_rank": 1, "priority_type": "debt_payment", "target_liability_id": loan["id"]}])).status_code == 200
    blocked = await client.delete(f"/api/plans/{pid}/liabilities/{loan['id']}")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "CONFLICT"
    assert (await save_priorities(client, pid, [])).status_code == 200
    assert (await client.delete(f"/api/plans/{pid}/liabilities/{loan['id']}")).status_code == 204


@pytest.mark.anyio
async def test_forgiveness_round_trip_and_validation(client):
    pid = await _plan(client)
    loan = await _loan(client, pid, forgiveness={"year": 2030})
    assert loan["forgiveness"]["year"] == 2030 and loan["forgiveness"]["tax_treatment"] == "taxable"
    url = f"/api/plans/{pid}/liabilities/{loan['id']}"
    declared = await client.put(url, json={"forgiveness": {
        "year": 2031, "amount": 5000, "tax_treatment": "declared_exclusion",
        "excluded_amount": 2000, "exclusion_basis": "insolvency"}})
    assert declared.status_code == 200, declared.text
    assert declared.json()["forgiveness"]["excluded_amount"] == 2000
    for bad in (
        {"amount": 1},  # neither year nor milestone
        {"year": 2030, "tax_treatment": "declared_exclusion"},  # exclusion needs a basis
        {"year": 2030, "excluded_amount": 10},  # exclusion needs the declared treatment
        {"year": 2030, "milestone_id": "00000000-0000-4000-8000-000000000001"},
    ):
        assert (await client.put(url, json={"forgiveness": bad})).status_code == 422, bad
    missing_milestone = await client.put(url, json={"forgiveness": {"milestone_id": "00000000-0000-4000-8000-000000000001"}})
    assert missing_milestone.status_code == 422
    assert (await client.put(url, json={"forgiveness": None})).json()["forgiveness"] is None


@pytest.mark.anyio
async def test_account_distribution_settings_round_trip_and_reject_ineligible_use(client):
    plan_401k = await _account(client, "traditional_401k", "Work plan", 100000,
                               distribution_settings={"separation_year": 2035})
    assert plan_401k["distribution_settings"]["separation_year"] == 2035
    ira = await client.post("/api/accounts", json={
        "name": "IRA", "account_type": "traditional_ira", "balance": 1,
        "distribution_settings": {"separation_year": 2035}})
    assert ira.status_code == 422, ira.text
    beneficiary = await _account(client, "traditional_ira", "IRA", 1000,
                                 distribution_settings={"spouse_sole_beneficiary": True})
    assert beneficiary["distribution_settings"]["spouse_sole_beneficiary"] is True
    plain = await _account(client, "checking", "Cash", 5)
    assert plain.get("distribution_settings") in (None, {})


@pytest.mark.anyio
async def test_cash_reserve_and_sepp_amount_round_trip(client):
    pid = await _plan(client)
    cash = await _account(client, "savings", "Emergency", 20000)
    brokerage = await _account(client, "taxable_brokerage", "Brokerage", 20000)
    url = f"/api/plans/{pid}"
    ok = await client.put(url, json={"cash_reserve_settings": {
        "enabled": True, "account_ids": [cash["id"]], "reserve_amount": 10000}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["cash_reserve_settings"]["account_ids"] == [cash["id"]]
    bad = await client.put(url, json={"cash_reserve_settings": {
        "enabled": True, "account_ids": [brokerage["id"]], "reserve_amount": 10000}})
    assert bad.status_code == 422, bad.text
    empty = await client.put(url, json={"cash_reserve_settings": {"enabled": True, "account_ids": [], "reserve_amount": 1}})
    assert empty.status_code == 422


@pytest.mark.anyio
async def test_duplicate_remaps_loan_milestone_and_reserve_identities(client):
    pid = await _plan(client)
    milestone = await client.post(f"/api/plans/{pid}/milestones", json={
        "name": "Reached", "trigger_type": "date", "trigger_date": "2030-01-01"})
    assert milestone.status_code == 201, milestone.text
    mid = milestone.json()["id"]
    loan = await _loan(client, pid, forgiveness={"milestone_id": mid})
    assert (await save_priorities(client, pid, [{
        "priority_rank": 1, "priority_type": "debt_payment", "target_liability_id": loan["id"]}])).status_code == 200
    copied = await client.post(f"/api/plans/{pid}/duplicate")
    assert copied.status_code == 201, copied.text
    new_pid = copied.json()["id"]
    new_loan = (await client.get(f"/api/plans/{new_pid}/liabilities")).json()[0]
    new_milestone = (await client.get(f"/api/plans/{new_pid}/milestones")).json()[0]
    assert new_loan["id"] != loan["id"] and new_milestone["id"] != mid
    assert new_loan["forgiveness"]["milestone_id"] == new_milestone["id"]
    rules = (await client.get(f"/api/plans/{new_pid}/priorities")).json()["items"]
    assert rules[0]["target_liability_id"] == new_loan["id"]
    # The original is untouched.
    assert (await client.get(f"/api/plans/{pid}/priorities")).json()["items"][0]["target_liability_id"] == loan["id"]


@pytest.mark.anyio
async def test_saved_plan_simulation_pays_the_loan_and_applies_forgiveness(client):
    pid = await _plan(client)
    await client.post(f"/api/plans/{pid}/incomes", json={"name": "Salary", "annual_amount": 120000, "tax_category": "employment"})
    savings = await _account(client, "savings", "Savings", 0)
    loan = await _loan(client, pid)
    plain = (await client.post(f"/api/plans/{pid}/simulate")).json()["yearly_snapshots"][0]
    assert (await save_priorities(client, pid, [
        {"priority_rank": 1, "priority_type": "debt_payment", "target_liability_id": loan["id"], "max_annual_amount": 4000},
        {"priority_rank": 2, "priority_type": "contribution", "target_account_id": savings["id"]}])).status_code == 200
    paid = (await client.post(f"/api/plans/{pid}/simulate")).json()["yearly_snapshots"][0]
    assert plain["liabilities_balance"] - paid["liabilities_balance"] == pytest.approx(4000, abs=0.01)
    flows = [f for f in paid["cash_flow"]["contributions"] if f["name"].startswith("Pay down")]
    assert flows and flows[0]["amount"] == pytest.approx(4000) and flows[0]["account_id"] is None
    assert (await client.put(f"/api/plans/{pid}/liabilities/{loan['id']}", json={"forgiveness": {"year": 2027}})).status_code == 200
    rows = (await client.post(f"/api/plans/{pid}/simulate")).json()["yearly_snapshots"]
    assert rows[0]["debt_forgiven"] == 0 and rows[1]["debt_forgiven"] > 0
    assert rows[1]["debt_forgiveness_taxable"] == pytest.approx(rows[1]["debt_forgiven"])
