"""Switched-off milestones never fire; references treat them as never reached."""
from dataclasses import asdict, replace
from uuid import uuid4

import pytest

from app.schemas.milestone import MilestoneConditions
from coastmath.engine.milestones import (
    evaluate_milestones,
    resolve_deterministic_milestones,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    SimState,
)
from coastmath.schemas.plan_data_request import (
    PlanDataRequest,
    request_to_engine_data,
)


def conditions(items, deadline=None, combinator="all"):
    return MilestoneConditions.model_validate(
        {"combinator": combinator, "items": items, "deadline": deadline}).model_dump()


def plan(*milestones, income_end=None, expense_start=None):
    return PlanData(
        plan_id=str(uuid4()), birth_year=1980, birth_month=1, life_expectancy=55,
        filing_status="single", start_year=2026, accounts={"cash": AccountInfo(100_000, "checking")},
        assumptions=AssumptionData(inflation_rate=0, cash_yield_rate=0), milestones=list(milestones),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0},
        income_streams=[IncomeData("wages", "Wages", 20_000, end_milestone_id=income_end)],
        expenses=[ExpenseData("cost", "Living", 1_200, start_milestone_id=expense_start)],
    )


def by_year(result):
    return {row.year: row for row in result.yearly_snapshots}


BASE = MilestoneData("base", "Move", "date", trigger_date="2028-01-01")


def test_inactive_milestone_window_never_opens_or_closes():
    active = by_year(run_simulation(plan(BASE, income_end="base", expense_start="base")))
    assert active[2027].expenses == 0 and active[2028].expenses == 1_200
    assert active[2027].gross_income == 20_000 and active[2028].gross_income == 0
    off = run_simulation(plan(replace(BASE, is_active=False), income_end="base", expense_start="base"))
    rows = by_year(off)
    # The start never comes and the end never comes: same as an unreached milestone.
    assert all(row.expenses == 0 for row in off.yearly_snapshots)
    assert rows[2028].gross_income == rows[2030].gross_income == 20_000
    outcome = off.metadata.milestone_outcomes[0]
    assert outcome.year is None and outcome.missed_year is None


def test_condition_relative_and_deadline_references_see_never_reached():
    off = replace(BASE, is_active=False)
    goal = MilestoneData("goal", "Goal", "conditions",
                         conditions=conditions([{"kind": "milestone", "milestone_id": "base"}]))
    either = MilestoneData("either", "Either", "conditions", conditions=conditions(
        [{"kind": "milestone", "milestone_id": "base"}, {"kind": "year", "year": 2030}], combinator="any"))
    deadline = MilestoneData("late", "Late", "conditions", conditions=conditions(
        [{"kind": "year", "year": 2032}], deadline={"kind": "milestone", "value": "base", "action": "fire"}))
    relative = MilestoneData("after", "After", "relative", relative_to_id="base", offset_years=2)
    before = MilestoneData("before", "Before", "relative", relative_to_id="base", offset_years=-1)
    result = run_simulation(plan(off, goal, either, deadline, relative, before))
    years = {o.id: o.year for o in result.metadata.milestone_outcomes}
    assert years == {"base": None, "goal": None, "either": 2030, "late": 2032, "after": None, "before": None}
    # The same plan with the base switched on fires each reference from 2028.
    active = run_simulation(plan(BASE, goal, either, deadline, relative, before))
    years = {o.id: o.year for o in active.metadata.milestone_outcomes}
    assert years == {"base": 2028, "goal": 2028, "either": 2028, "late": 2028, "after": 2030, "before": 2027}


def test_inactive_milestone_never_misses_its_deadline_and_has_no_resolved_date():
    goal = MilestoneData("goal", "Goal", "conditions", is_active=False, conditions=conditions(
        [{"kind": "metric", "metric": "net_worth", "comparator": ">=", "value_unit": "dollars", "value": 1e12}],
        deadline={"kind": "year", "value": 2026, "action": "miss"}))
    state = SimState(2026, accounts={"cash": AccountInfo(100, "checking")})
    assert evaluate_milestones(state, [goal], 2027, 1980) == []
    assert state.missed_milestone_years == {} and state.triggered_milestones == set()
    resolved = resolve_deterministic_milestones([replace(BASE, is_active=False)], 1980)
    assert not resolved[0].is_active


def test_stateless_request_round_trips_switch_and_keeps_default_dumps():
    body = asdict(plan(BASE, expense_start="base"))
    request = PlanDataRequest.model_validate(body)
    assert "is_active" not in request.model_dump(exclude_unset=True)["milestones"][0]
    assert "is_active" not in request.model_dump()["milestones"][0]
    assert request_to_engine_data(request).milestones[0].is_active is True
    body["milestones"][0]["is_active"] = False
    request = PlanDataRequest.model_validate(body)
    converted = request_to_engine_data(request)
    assert converted.milestones[0].is_active is False
    assert all(row.expenses == 0 for row in run_simulation(converted).yearly_snapshots)


@pytest.mark.anyio
async def test_api_switch_round_trip_and_window_check(client):
    pid = (await client.post("/api/plans", json={"name": "Switch", "birth_year": 1980})).json()["id"]
    path = f"/api/plans/{pid}/milestones"
    created = (await client.post(path, json={"name": "Move", "trigger_type": "age", "trigger_value": 60})).json()
    assert created["is_active"] is True
    late = (await client.post(path, json={"name": "Early", "trigger_type": "age", "trigger_value": 50})).json()
    off = await client.put(f"{path}/{created['id']}", json={"is_active": False})
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert off.json()["trigger_value"] == 60
    assert (await client.put(f"{path}/{created['id']}", json={"is_active": None})).status_code == 422
    # A window bounded by a switched-off milestone has no known year to check.
    income = await client.post(f"/api/plans/{pid}/incomes", json={
        "name": "Wages", "annual_amount": 50_000,
        "start_milestone_id": created["id"], "end_milestone_id": late["id"]})
    assert income.status_code in (200, 201), income.text
    plan_body = (await client.get(f"/api/plans/{pid}")).json()
    assert {m["name"]: m["is_active"] for m in plan_body["milestones"]} == {"Move": False, "Early": True}
    simulated = await client.post(f"/api/plans/{pid}/simulate")
    assert simulated.status_code == 200, simulated.text
    assert all(row["gross_income"] == 0 for row in simulated.json()["yearly_snapshots"])
