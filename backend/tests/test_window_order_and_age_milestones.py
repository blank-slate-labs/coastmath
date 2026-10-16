"""Income and expense windows stay in order, balances stay non-negative, and age milestones
report the year they were reached."""


import pytest
from httpx import AsyncClient

from coastmath.engine.milestones import evaluate_milestones
from coastmath.engine.types import MilestoneData, SimState
from tests.api_support import create_plan


async def _plan(client: AsyncClient, **overrides) -> dict:
    return await create_plan(client, **({"name": "Audit", "birth_year": 1992} | overrides))


async def _milestone(client: AsyncClient, plan_id: str, name: str, age: int) -> dict:
    r = await client.post(f"/api/plans/{plan_id}/milestones",
                          json={"name": name, "trigger_type": "age", "trigger_value": age, "sort_order": 0})
    assert r.status_code == 201
    return r.json()


# Start and end milestones must be in order.

@pytest.mark.anyio
async def test_expense_start_after_end_is_rejected(client: AsyncClient):
    plan = await _plan(client)
    retire = await _milestone(client, plan["id"], "Retirement", 47)
    ss = await _milestone(client, plan["id"], "Social Security Begins", 70)
    r = await client.post(f"/api/plans/{plan['id']}/expenses", json={
        "name": "Housing", "annual_amount": 28000,
        "start_milestone_id": ss["id"], "end_milestone_id": retire["id"],
    })
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert {d["field"] for d in err["details"]} == {"start_milestone_id", "end_milestone_id"}
    assert "2062" in err["message"] and "2039" in err["message"]


@pytest.mark.anyio
async def test_expense_update_checks_merged_window(client: AsyncClient):
    plan = await _plan(client)
    retire = await _milestone(client, plan["id"], "Retirement", 47)
    ss = await _milestone(client, plan["id"], "Social Security Begins", 70)
    created = await client.post(f"/api/plans/{plan['id']}/expenses", json={
        "name": "Housing", "annual_amount": 28000, "start_milestone_id": retire["id"], "end_milestone_id": ss["id"],
    })
    assert created.status_code == 201
    r = await client.put(f"/api/plans/{plan['id']}/expenses/{created.json()['id']}",
                         json={"end_milestone_id": None, "start_milestone_id": ss["id"]})
    assert r.status_code == 200, "clearing the end while moving the start leaves an open window"
    r = await client.put(f"/api/plans/{plan['id']}/expenses/{created.json()['id']}",
                         json={"end_milestone_id": retire["id"]})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_income_window_is_validated_too(client: AsyncClient):
    plan = await _plan(client)
    retire = await _milestone(client, plan["id"], "Retirement", 47)
    ss = await _milestone(client, plan["id"], "Social Security Begins", 70)
    r = await client.post(f"/api/plans/{plan['id']}/incomes", json={
        "name": "Salary", "annual_amount": 185000, "start_milestone_id": ss["id"], "end_milestone_id": retire["id"],
    })
    assert r.status_code == 422


@pytest.mark.anyio
async def test_same_year_and_projection_dependent_windows_pass(client: AsyncClient):
    plan = await _plan(client)
    retire = await _milestone(client, plan["id"], "Retirement", 47)
    fi = await client.post(f"/api/plans/{plan['id']}/milestones", json={
        "name": "FI", "trigger_type": "expense_multiple", "expense_multiple": 25, "metric": "liquid_net_worth", "sort_order": 1,
    })
    r = await client.post(f"/api/plans/{plan['id']}/expenses", json={
        "name": "Bridge", "annual_amount": 1000, "start_milestone_id": fi.json()["id"], "end_milestone_id": retire["id"],
    })
    assert r.status_code == 201, "FI year is unknown before simulating, so no ordering check applies"


# Account balances cannot be negative.

@pytest.mark.anyio
async def test_negative_account_balance_is_rejected(client: AsyncClient):
    r = await client.post("/api/accounts", json={"name": "Emergency Fund", "account_type": "savings", "balance": -100})
    assert r.status_code == 422
    ok = await client.post("/api/accounts", json={"name": "Emergency Fund", "account_type": "savings", "balance": 25000})
    assert ok.status_code == 201
    r = await client.put(f"/api/accounts/{ok.json()['id']}", json={"balance": -1})
    assert r.status_code == 422


# Age milestones report the year they were reached.

def test_age_milestone_reports_the_year_it_was_reached():
    state = SimState(year=2026)
    ms = MilestoneData(id="retire", name="Retirement", trigger_type="age", trigger_value=30)
    assert evaluate_milestones(state, [ms], 2026, birth_year=1992) == ["retire"]
    assert state.triggered_milestone_years["retire"] == 2022


def test_future_age_milestone_still_fires_in_its_own_year():
    state = SimState(year=2039)
    ms = MilestoneData(id="retire", name="Retirement", trigger_type="age", trigger_value=47)
    assert evaluate_milestones(state, [ms], 2038, birth_year=1992) == []
    assert evaluate_milestones(state, [ms], 2039, birth_year=1992) == ["retire"]
    assert state.triggered_milestone_years["retire"] == 2039


@pytest.mark.anyio
async def test_past_retirement_shows_actual_year_and_stops_salary_for_the_whole_first_year(client: AsyncClient):
    plan = await _plan(client, birth_month=11)
    retire = await _milestone(client, plan["id"], "Retirement", 30)
    r = await client.post(f"/api/plans/{plan['id']}/incomes",
                          json={"name": "Salary", "annual_amount": 120000, "end_milestone_id": retire["id"]})
    assert r.status_code == 201
    sim = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert sim.status_code == 200
    body = sim.json()
    outcomes = {o["name"]: o["year"] for o in body["metadata"]["milestone_outcomes"]}
    assert outcomes["Retirement"] == 2022
    assert body["yearly_snapshots"][0]["gross_income"] == 0
