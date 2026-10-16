"""Saved transfer windows must control cash movement, not only the editor."""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    MilestoneData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import execute_transfers


@pytest.mark.parametrize("triggered,expected", [
    (set(), 0), ({"start"}, 10_000), ({"start", "end"}, 0), ({"end"}, 0),
])
def test_transfer_respects_start_and_end_without_losing_cash(triggered, expected):
    state = SimState(year=2026, accounts={
        "cash": AccountInfo(50_000, "checking"),
        "save": AccountInfo(0, "savings"),
    }, triggered_milestones=triggered)
    rule = PriorityData(1, priority_type="transfer", source_account_id="cash",
        target_account_id="save", max_annual_amount=10_000,
        start_milestone_id="start", end_milestone_id="end")
    result = execute_transfers([rule], state)
    assert result == ({"save": expected} if expected else {})
    assert state.get_balance("save") == expected
    assert state.get_balance("cash") == 50_000 - expected
    assert sum(a.balance for a in state.accounts.values()) == 50_000


def test_simulator_moves_cash_only_in_saved_transfer_window():
    plan = PlanData(plan_id="00000000-0000-0000-0000-000000000001",
        birth_year=1980, birth_month=1, start_year=2026, life_expectancy=50,
        filing_status="single", accounts={
            "cash": AccountInfo(50_000, "checking"),
            "save": AccountInfo(0, "savings"),
        }, assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0),
        milestones=[MilestoneData("start", "Start", "date", trigger_date="2027-01-01"),
                    MilestoneData("end", "End", "date", trigger_date="2028-01-01")],
        priorities=[PriorityData(1, priority_type="transfer", source_account_id="cash",
            target_account_id="save", max_annual_amount=10_000,
            start_milestone_id="start", end_milestone_id="end")])
    snapshots = run_simulation(plan).yearly_snapshots
    assert [s.accounts["save"] for s in snapshots[:3]] == [0, 10_000, 10_000]
    assert [s.net_worth for s in snapshots[:3]] == [50_000] * 3


@pytest.mark.anyio
async def test_saved_transfer_window_matches_stateless_simulation(client):
    accounts = {}
    for name, kind, balance in [("Cash", "checking", 50_000), ("Save", "savings", 0)]:
        response = await client.post("/api/accounts", json={"name": name, "account_type": kind, "balance": balance})
        assert response.status_code == 201, response.text
        account = response.json()
        accounts[account["id"]] = {"name": name, "account_type": kind, "balance": balance}
    cash_id, save_id = accounts
    response = await client.post("/api/plans", json={"name": "Transfer window", "birth_year": 1980,
        "birth_month": 1, "life_expectancy": 50, "plan_type": "FIXED_DATE", "start_date": "2026-01-01",
        "snapshot_conditions": accounts})
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    bounds = []
    for name, date in [("Start", "2027-01-01"), ("End", "2028-01-01")]:
        response = await client.post(f"/api/plans/{pid}/milestones", json={
            "name": name, "trigger_type": "date", "trigger_date": date})
        assert response.status_code == 201, response.text
        bounds.append(response.json())
    rule = {"priority_rank": 1, "priority_type": "transfer", "source_account_id": cash_id,
        "target_account_id": save_id, "max_annual_amount": 10_000,
        "start_milestone_id": bounds[0]["id"], "end_milestone_id": bounds[1]["id"]}
    response = await client.put(f"/api/plans/{pid}/priorities", json={"expected_revision": 0, "items": [rule]})
    assert response.status_code == 200, response.text
    saved = (await client.get(f"/api/plans/{pid}/priorities")).json()["items"][0]
    assert saved["start_milestone_id"] == rule["start_milestone_id"]
    assert saved["end_milestone_id"] == rule["end_milestone_id"]
    persisted = await client.post(f"/api/plans/{pid}/simulate")
    stateless = await client.post("/api/simulate/stateless", json={"plan_id": pid,
        "birth_year": 1980, "birth_month": 1, "start_year": 2026, "life_expectancy": 50,
        "accounts": accounts, "milestones": bounds, "priorities": [rule]})
    for response in (persisted, stateless):
        assert response.status_code == 200, response.text
        rows = response.json()["yearly_snapshots"][:3]
        assert [row["accounts"][save_id] for row in rows] == [0, 10_000, 10_000]
        assert [row["net_worth"] for row in rows] == [50_000] * 3
