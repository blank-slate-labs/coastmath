"""Saved withdrawal strategy through the plan API (SQLite fixtures)."""

import pytest
from httpx import AsyncClient


async def _plan_with_retirement(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/api/plans", json={"name": "Saved strategy", "birth_year": 1965, "life_expectancy": 80})
    assert r.status_code == 201
    plan = r.json()
    r = await client.post("/api/accounts", json={"name": "Brokerage", "account_type": "taxable_brokerage",
                                                 "balance": 1_200_000, "cost_basis": 1_200_000})
    assert r.status_code == 201
    r = await client.post(f"/api/plans/{plan['id']}/expenses", json={"name": "Living", "annual_amount": 45_000})
    assert r.status_code == 201
    r = await client.post(f"/api/plans/{plan['id']}/milestones",
                          json={"name": "Retire", "trigger_type": "age", "trigger_value": 63, "sort_order": 0})
    assert r.status_code == 201
    return plan, r.json()


@pytest.mark.anyio
async def test_saved_strategy_round_trips_and_drives_the_projection(client: AsyncClient):
    plan, retire = await _plan_with_retirement(client)
    pid = plan["id"]
    assert "withdrawal_strategy" not in plan
    baseline = (await client.post(f"/api/plans/{pid}/simulate")).json()["yearly_snapshots"]
    assert all(s["strategy_spending"] is None for s in baseline)

    setting = {"enabled": True, "method": "clyatt_95", "initial_rate": 0.035, "start_milestone_id": retire["id"],
               "minimum": {"unit": "today_dollars", "amount": 30_000},
               "maximum": {"unit": "portfolio_percent", "amount": 0.06},
               "income_handling": "withdrawal_plus_income"}
    r = await client.put(f"/api/plans/{pid}", json={"withdrawal_strategy": setting})
    assert r.status_code == 200, r.text
    saved = (await client.get(f"/api/plans/{pid}")).json()["withdrawal_strategy"]
    assert {k: saved[k] for k in setting} == setting
    assert saved["clyatt_floor"] == 0.95 and saved["ratchet_threshold"] == 1.5

    snaps = (await client.post(f"/api/plans/{pid}/simulate")).json()["yearly_snapshots"]
    started = [s for s in snaps if s["strategy_spending"] is not None]
    assert started and started[0]["year"] == 1965 + 63
    assert snaps != baseline

    # Disabling keeps the saved choices but restores the baseline projection.
    r = await client.put(f"/api/plans/{pid}", json={"withdrawal_strategy": {**setting, "enabled": False}})
    assert r.status_code == 200
    assert (await client.post(f"/api/plans/{pid}/simulate")).json()["yearly_snapshots"] == baseline
    # Null clears it.
    r = await client.put(f"/api/plans/{pid}", json={"withdrawal_strategy": None})
    assert r.status_code == 200 and "withdrawal_strategy" not in r.json()


@pytest.mark.anyio
async def test_start_milestone_must_belong_to_the_plan_and_blocks_its_delete(client: AsyncClient):
    plan, retire = await _plan_with_retirement(client)
    pid = plan["id"]
    other, other_retire = await _plan_with_retirement(client)
    r = await client.put(f"/api/plans/{pid}", json={"withdrawal_strategy": {
        "enabled": True, "method": "vpw", "start_milestone_id": other_retire["id"]}})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "withdrawal_strategy.start_milestone_id"
    r = await client.put(f"/api/plans/{pid}", json={"withdrawal_strategy": {"enabled": True, "method": "fixed_amount"}})
    assert r.status_code == 422
    r = await client.put(f"/api/plans/{pid}", json={"withdrawal_strategy": {
        "enabled": True, "method": "vpw", "start_milestone_id": retire["id"]}})
    assert r.status_code == 200
    r = await client.delete(f"/api/plans/{pid}/milestones/{retire['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


@pytest.mark.anyio
async def test_duplicate_copies_the_strategy_with_the_new_milestone(client: AsyncClient):
    plan, retire = await _plan_with_retirement(client)
    r = await client.put(f"/api/plans/{plan['id']}", json={"withdrawal_strategy": {
        "enabled": True, "method": "kitces_ratchet", "start_milestone_id": retire["id"]}})
    assert r.status_code == 200
    r = await client.post(f"/api/plans/{plan['id']}/duplicate")
    assert r.status_code == 201, r.text
    copy = r.json()
    new_retire = next(m for m in copy["milestones"] if m["name"] == "Retire")
    assert new_retire["id"] != retire["id"]
    assert copy["withdrawal_strategy"]["method"] == "kitces_ratchet"
    assert copy["withdrawal_strategy"]["start_milestone_id"] == new_retire["id"]
