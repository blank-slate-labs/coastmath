"""Account withdrawal locks through the account, milestone, plan and simulation APIs."""
import uuid

import pytest

from tests.scenario_support import post


async def _plan_with_milestone(client, **plan):
    created = await post(client, "/plans", {"name": "Locks", "birth_year": 1980, "plan_type": "NOW", **plan})
    milestone = await post(client, f"/plans/{created['id']}/milestones",
                           {"name": "Separation", "trigger_type": "age", "trigger_value": 55})
    return created, milestone


BROKERAGE = {"name": "Deferred comp", "account_type": "taxable_brokerage", "balance": 100_000, "cost_basis": 100_000}


@pytest.mark.anyio
@pytest.mark.parametrize("lock", [
    {"unlock": "age"},
    {"unlock": "age", "age": 62, "year": 2040},
    {"unlock": "milestone", "age": 62},
    {"unlock": "year", "year": 2040, "note": "extra"},
    {"unlock": "age", "age": 121},
    {"unlock": "someday", "year": 2040},
])
async def test_lock_needs_exactly_the_field_its_unlock_names(client, lock):
    response = await client.post("/api/accounts", json={**BROKERAGE, "withdrawal_lock": lock})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_unknown_or_foreign_milestone_is_rejected(client):
    plan, _ = await _plan_with_milestone(client)
    other, other_milestone = await _plan_with_milestone(client)
    missing = {"unlock": "milestone", "milestone_id": str(uuid.uuid4())}
    response = await client.post(f"/api/plans/{plan['id']}/accounts", json={**BROKERAGE, "withdrawal_lock": missing})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "withdrawal_lock.milestone_id"
    # A plan-scoped save only accepts that plan's milestones.
    foreign = {"unlock": "milestone", "milestone_id": other_milestone["id"]}
    response = await client.post(f"/api/plans/{plan['id']}/accounts", json={**BROKERAGE, "withdrawal_lock": foreign})
    assert response.status_code == 422
    # Without a plan, a household account may use any household plan's milestone.
    assert (await client.post("/api/accounts", json={**BROKERAGE, "withdrawal_lock": foreign})).status_code == 201


@pytest.mark.anyio
async def test_lock_round_trips_and_partial_updates_keep_it(client):
    plan, milestone = await _plan_with_milestone(client)
    lock = {"unlock": "milestone", "milestone_id": milestone["id"]}
    account = await post(client, f"/plans/{plan['id']}/accounts", {**BROKERAGE, "withdrawal_lock": lock})
    expected = {"unlock": "milestone", "age": None, "milestone_id": milestone["id"], "year": None}
    assert account["withdrawal_lock"] == expected
    listed = (await client.get(f"/api/plans/{plan['id']}/accounts")).json()
    assert next(row for row in listed if row["id"] == account["id"])["withdrawal_lock"] == expected

    # A client that omits the field (shipped native app) keeps the lock.
    path = f"/api/plans/{plan['id']}/accounts/{account['id']}"
    response = await client.put(path, json={"name": "Renamed", "balance": 90_000})
    assert response.status_code == 200, response.text
    assert response.json()["withdrawal_lock"] == expected

    response = await client.put(path, json={"withdrawal_lock": {"unlock": "age", "age": 59.5}})
    assert response.json()["withdrawal_lock"] == {"unlock": "age", "age": 59.5, "milestone_id": None, "year": None}
    response = await client.put(path, json={"withdrawal_lock": {"unlock": "milestone", "milestone_id": str(uuid.uuid4())}})
    assert response.status_code == 422
    response = await client.put(path, json={"withdrawal_lock": None})
    assert response.status_code == 200
    assert response.json()["withdrawal_lock"] is None


@pytest.mark.anyio
async def test_milestone_delete_is_blocked_while_a_lock_uses_it(client):
    plan, milestone = await _plan_with_milestone(client)
    lock = {"unlock": "milestone", "milestone_id": milestone["id"]}
    account = await post(client, f"/plans/{plan['id']}/accounts", {**BROKERAGE, "withdrawal_lock": lock})
    milestone_path = f"/api/plans/{plan['id']}/milestones/{milestone['id']}"
    response = await client.delete(milestone_path)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert (await client.get(f"/api/plans/{plan['id']}/accounts")).json()[0]["withdrawal_lock"]["milestone_id"] == milestone["id"]
    await client.put(f"/api/plans/{plan['id']}/accounts/{account['id']}", json={"withdrawal_lock": {"unlock": "year", "year": 2030}})
    assert (await client.delete(milestone_path)).status_code == 204


@pytest.mark.anyio
async def test_client_plan_duplicate_keeps_the_lock_on_the_copied_milestone(client):
    owner = (await client.post("/api/clients/personal")).json()
    plan, milestone = await _plan_with_milestone(client, client_id=owner["id"])
    lock = {"unlock": "milestone", "milestone_id": milestone["id"]}
    await post(client, f"/plans/{plan['id']}/accounts", {**BROKERAGE, "withdrawal_lock": lock})
    copied = await post(client, f"/plans/{plan['id']}/duplicate", {})
    copied_account = (await client.get(f"/api/plans/{copied['id']}/accounts")).json()[0]
    assert copied_account["withdrawal_lock"]["unlock"] == "milestone"
    assert copied_account["withdrawal_lock"]["milestone_id"] == copied["milestones"][0]["id"] != milestone["id"]


@pytest.mark.anyio
async def test_persisted_stateless_and_snapshot_simulations_honor_the_lock(client):
    plan = await post(client, "/plans", {"name": "Locked sim", "birth_year": 1980, "plan_type": "NOW"})
    lock = {"unlock": "year", "year": 2100}
    account = await post(client, f"/plans/{plan['id']}/accounts", {**BROKERAGE, "withdrawal_lock": lock})
    await post(client, f"/plans/{plan['id']}/expenses", {"name": "Living", "annual_amount": 10_000})
    persisted = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert persisted.status_code == 200, persisted.text
    first = persisted.json()["yearly_snapshots"][0]
    assert first["accounts"][account["id"]] >= 100_000
    assert first["unfunded_expenses"] > 0
    assert "locked_account_ids" not in first

    def stateless_body(account_lock):
        return {
            "plan_id": plan["id"], "birth_year": 1980, "start_year": 2026, "life_expectancy": 90,
            "accounts": {account["id"]: {**BROKERAGE, "withdrawal_lock": account_lock}},
            "drawdown_order": [{"rank": 1, "source_account_id": account["id"]}],
            "expenses": [{"id": "living", "name": "Living", "annual_amount": 10_000}],
        }
    stateless = await client.post("/api/simulate/stateless", json=stateless_body(lock))
    assert stateless.status_code == 200, stateless.text
    assert stateless.json()["yearly_snapshots"][0]["unfunded_expenses"] > 0
    unlocked = await client.post("/api/simulate/stateless", json=stateless_body(None))
    assert unlocked.json()["yearly_snapshots"][0]["unfunded_expenses"] == 0

    aid = str(uuid.uuid4())
    fixed = await post(client, "/plans", {
        "name": "Snapshot lock", "birth_year": 1980, "life_expectancy": 90, "plan_type": "FIXED_DATE",
        "start_date": "2026-01-01",
        "snapshot_conditions": {aid: {**BROKERAGE, "withdrawal_lock": lock}},
    })
    await post(client, f"/plans/{fixed['id']}/expenses", {"name": "Living", "annual_amount": 10_000})
    simulated = await client.post(f"/api/plans/{fixed['id']}/simulate")
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["yearly_snapshots"][0]["unfunded_expenses"] > 0
