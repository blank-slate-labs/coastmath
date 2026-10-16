"""Social Security claiming age and milestone windows that never open.

A claiming age persists through the API and schedules the benefit from the
year that age is reached, for the owner or the spouse, unless an explicit
start milestone overrides it. Income and expense windows that never open in
the projection are reported as warnings. The API round trip also covers the
backdoor Roth flag on a priority.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from coastmath.engine.milestones import (
    never_active_windows,
    with_social_security_claiming,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AssumptionData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
)


def _plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()), birth_year=1992, filing_status="single", life_expectancy=89,
        start_year=2026, milestones=[], income_streams=[], expenses=[], priorities=[], drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0), accounts={},
    )
    defaults.update(overrides)
    return PlanData(**defaults)


def _ss(**overrides) -> IncomeData:
    fields = dict(id="ss", name="Social Security", annual_amount=28_800, is_social_security=True,
                  is_earned_income=False, claiming_age=70)
    fields.update(overrides)
    return IncomeData(**fields)


def _by_year(result):
    return {snap.year: snap for snap in result.yearly_snapshots}


# --- Claiming age ------------------------------------------------------------

def test_claiming_age_starts_benefits_the_year_that_age_is_reached():
    result = run_simulation(_plan(income_streams=[_ss()]))
    years = _by_year(result)
    assert years[2026].gross_income == 0
    assert years[2061].gross_income == 0
    assert years[2062].gross_income > 0
    assert years[2063].gross_income == pytest.approx(28_800)
    outcome = next(o for o in result.metadata.milestone_outcomes if o.id == "ss:claiming")
    assert (outcome.name, outcome.trigger_type, outcome.year) == ("Social Security at 70", "age", 2062)


def test_explicit_start_milestone_overrides_claiming_age():
    plan = _plan(
        milestones=[MilestoneData(id="early", name="Claim early", trigger_type="age", trigger_value=62)],
        income_streams=[_ss(start_milestone_id="early")],
    )
    years = _by_year(run_simulation(plan))
    assert years[2053].gross_income == 0
    assert years[2054].gross_income > 0
    assert not any(o.id == "ss:claiming" for o in run_simulation(plan).metadata.milestone_outcomes)


def test_claiming_age_without_value_keeps_legacy_start_now_behaviour():
    years = _by_year(run_simulation(_plan(income_streams=[_ss(claiming_age=None)])))
    assert years[2026].gross_income == pytest.approx(28_800)


def test_spouse_claiming_age_uses_the_spouse_birth_year():
    plan = _plan(spouse_birth_year=1995, income_streams=[_ss(owner="spouse", claiming_age=67)])
    adjusted = with_social_security_claiming(plan)
    milestone = next(m for m in adjusted.milestones if m.id == "ss:claiming")
    # Spouse turns 67 in 2062, which is the owner's age 70.
    assert milestone.trigger_value == 70
    assert plan.milestones == []  # the caller's plan is untouched
    years = _by_year(run_simulation(plan))
    assert years[2061].gross_income == 0
    assert years[2062].gross_income > 0


# --- Windows that never open -------------------------------------------------

def test_reversed_window_is_reported_after_the_projection():
    plan = _plan(
        milestones=[
            MilestoneData(id="retire", name="Retirement", trigger_type="age", trigger_value=47),
            MilestoneData(id="fi", name="FI", trigger_type="age", trigger_value=43),
            MilestoneData(id="never", name="Net worth $1B", trigger_type="net_worth", trigger_value=1e9),
        ],
        expenses=[
            ExpenseData(id="travel", name="Travel", annual_amount=12_000, start_milestone_id="retire", end_milestone_id="fi"),
            ExpenseData(id="bridge", name="Bridge", annual_amount=1_000, start_milestone_id="never", end_milestone_id="fi"),
            ExpenseData(id="ok", name="Living", annual_amount=1_000, start_milestone_id="fi", end_milestone_id="retire"),
        ],
    )
    warnings = run_simulation(plan).metadata.warnings
    assert any(w.startswith("“Travel” never runs: it starts at “Retirement” (2039) after it ends at “FI” (2035)") for w in warnings), warnings
    assert any(w.startswith("“Bridge” never runs: it ends at “FI” (2035) but its start milestone “Net worth $1B” is never reached") for w in warnings), warnings
    assert not any("Living" in w for w in warnings)


def test_never_active_windows_ignores_open_and_unfinished_windows():
    ms = [MilestoneData(id="a", name="A", trigger_type="age", trigger_value=50), MilestoneData(id="b", name="B", trigger_type="age", trigger_value=60)]
    assert never_active_windows([("x", None, "b"), ("y", "a", None), ("z", "a", "a"), ("w", "a", "b")], ms, {"a": 2042}) == []


# --- API persistence ----------------------------------------------------------

@pytest.mark.anyio
async def test_claiming_age_and_backdoor_flag_round_trip_through_the_api(client: AsyncClient):
    plan = (await client.post("/api/plans", json={"name": "FIRE", "birth_year": 1992})).json()
    url = f"/api/plans/{plan['id']}"
    created = await client.post(url + "/incomes", json={"name": "Social Security", "annual_amount": 28_800, "is_social_security": True, "claiming_age": 70})
    assert created.status_code == 201, created.text
    assert created.json()["claiming_age"] == 70
    fetched = await client.get(url)
    assert fetched.json()["income_streams"][0]["claiming_age"] == 70
    updated = await client.put(f"{url}/incomes/{created.json()['id']}", json={"claiming_age": 62})
    assert updated.json()["claiming_age"] == 62
    assert (await client.post(url + "/incomes", json={"name": "Bad", "annual_amount": 1, "is_social_security": True, "claiming_age": 75})).status_code == 422
    simulated = await client.post(url + "/simulate")
    assert simulated.status_code == 200, simulated.text
    by_year = {s["year"]: s for s in simulated.json()["yearly_snapshots"]}
    assert by_year[2026]["gross_income"] == 0 and by_year[2055]["gross_income"] > 0

    roth = (await client.post("/api/accounts", json={"name": "Roth IRA", "account_type": "roth_ira", "balance": 0})).json()
    saved = await client.put(url + "/priorities", json={"expected_revision": 0, "items": [{"priority_rank": 1, "target_account_id": roth["id"], "backdoor_roth": True}]})
    assert saved.status_code == 200, saved.text
    assert (await client.get(url + "/priorities")).json()["items"][0]["backdoor_roth"] is True
