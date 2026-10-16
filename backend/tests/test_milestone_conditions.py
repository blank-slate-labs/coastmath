"""Multi-condition milestone boundaries, persistence and identity checks."""
from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.account import CurrentAccount
from app.models.user import User
from app.schemas.milestone import MilestoneConditions
from coastmath.engine.milestone_statistics import milestone_distributions
from coastmath.engine.milestones import evaluate_milestones, is_event_active
from coastmath.engine.monte_carlo import run_monte_carlo
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


def metric(name="net_worth", value=100, **changes):
    return {"kind": "metric", "metric": name, "comparator": ">=", "value_unit": "dollars", "value": value, **changes}


def milestone(items, *, combinator="all", deadline=None, identity="goal"):
    settings = {"combinator": combinator, "items": items, "deadline": deadline}
    return MilestoneData(identity, identity, "conditions", conditions=MilestoneConditions.model_validate(settings).model_dump())


def evaluate(state, goals, year=2026):
    return evaluate_milestones(state, goals, year, 1980, spouse_birth_year=1983)


def test_all_any_and_inclusive_comparators():
    items = [{"kind": "age", "owner": "self", "age": 50}, metric(value=100)]
    state = SimState(2026, accounts={"cash": AccountInfo(100, "checking")})
    assert evaluate(state, [milestone(items)]) == []
    assert evaluate(state, [milestone(items, combinator="any")]) == ["goal"]
    state = SimState(2026, accounts={"cash": AccountInfo(100, "checking")})
    assert evaluate(state, [milestone([metric(value=100, comparator="<=")])]) == ["goal"]


def test_age_and_liquid_balance_use_three_completed_spending_years():
    state = SimState(2030, accounts={"cash": AccountInfo(1_000_000, "checking")},
                     milestone_metric_history=[{"annual_spending": v} for v in (900_000, 30_000, 40_000, 50_000)])
    goal = milestone([{"kind": "age", "owner": "self", "age": 50}, metric("liquid_net_worth", 25,
                      value_unit="multiple_of_metric", other_metric="annual_spending", average_years=3)])
    assert evaluate(state, [goal], 2029) == []
    assert evaluate(state, [goal], 2030) == ["goal"]


def test_average_uses_available_years_but_requires_history():
    goal = milestone([metric("liquid_net_worth", 25, value_unit="multiple_of_metric", other_metric="annual_spending", average_years=3)])
    state = SimState(2026, accounts={"cash": AccountInfo(1_000_000, "checking")})
    assert evaluate(state, [goal]) == []
    state.milestone_metric_history = [{"annual_spending": 40_000}]
    assert evaluate(state, [goal]) == ["goal"]


def test_today_dollars_and_nominal_use_opening_inflation():
    state = SimState(2026, accounts={"cash": AccountInfo(150, "checking")}, inflation_factor=2)
    assert evaluate(state, [milestone([metric(value=100, value_unit="today_dollars")])]) == []
    assert evaluate(state, [milestone([metric(value=100)])]) == ["goal"]


def test_account_debt_savings_and_missing_account():
    state = SimState(2026, accounts={"cash": AccountInfo(100, "checking")}, milestone_metric_history=[{"savings_rate": .2}])
    assert evaluate(state, [milestone([metric("account_balance", 100, account_id="cash"), metric("total_debt", 0, comparator="<="), metric("savings_rate", 20, value_unit="percent")])]) == ["goal"]
    assert evaluate(SimState(2026), [milestone([metric("account_balance", 0, account_id="absent")])]) == []


def test_same_year_dependency_fixed_point_precedes_miss_deadline():
    state = SimState(2026)
    base = MilestoneData("base", "Base", "net_worth", trigger_value=0)
    first = milestone([{"kind": "milestone", "milestone_id": "second"}], deadline={"kind": "year", "value": 2026, "action": "miss"})
    second = milestone([{"kind": "milestone", "milestone_id": "base"}], identity="second")
    assert evaluate(state, [first, second, base]) == ["base", "second", "goal"]
    assert state.missed_milestone_years == {}


def test_partner_fractional_age_and_negative_fixed_offset():
    state = SimState(2030)
    goals = [MilestoneData("base", "Base", "age", trigger_value=52), milestone([
        {"kind": "age", "owner": "spouse", "age": 46.5}, {"kind": "date", "date": "2030-12"},
        {"kind": "year", "year": 2030}, {"kind": "milestone", "milestone_id": "base", "offset_years": -2}])]
    assert evaluate(state, goals, 2029) == []
    assert evaluate(state, goals, 2030) == ["goal"]
    assert state.triggered_milestone_months["goal"] == 12
    assert evaluate_milestones(SimState(2030), [milestone([{"kind": "age", "owner": "spouse", "age": 40}])], 2030, 1980) == []


def plan(goal):
    return PlanData(plan_id=str(uuid4()), birth_year=1980, birth_month=6, life_expectancy=50,
                    filing_status="single", start_year=2026, accounts={"cash": AccountInfo(100_000, "checking")},
                    assumptions=AssumptionData(inflation_rate=0, cash_yield_rate=0), milestones=[goal],
                    tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0},
                    income_streams=[IncomeData("pension", "Pension", 10_000, tax_category="qualified_pension"),
                                    IncomeData("wages", "Wages", 20_000), IncomeData("business", "Business", 15_000, tax_category="self_employment")],
                    expenses=[ExpenseData("cost", "Living", 1200, start_milestone_id="goal")])


def test_deadline_fire_miss_permanent_events_and_statistics():
    goal = milestone([metric(value=1_000_000)], deadline={"kind": "year", "value": 2027, "action": "miss"})
    missed = run_simulation(plan(goal))
    outcome = missed.metadata.milestone_outcomes[0]
    assert outcome.year is None and outcome.missed_year == 2027
    assert all(row.expenses == 0 for row in missed.yearly_snapshots)
    fired_goal = replace(goal, conditions={**goal.conditions, "deadline": {"kind": "year", "value": 2027, "action": "fire"}})
    fired = run_simulation(plan(fired_goal))
    assert fired.metadata.milestone_outcomes[0].year == 2027
    assert fired.yearly_snapshots[1].expenses == 1200
    summary = milestone_distributions([missed, fired])[0]
    assert (summary.reached_trials, summary.unreached_trials, summary.reach_rate) == (1, 1, .5)
    state = SimState(2026)
    evaluate(state, [goal], 2027)
    state.accounts["cash"] = AccountInfo(2_000_000, "checking")
    assert evaluate(state, [goal], 2028) == []
    assert not is_event_active("goal", None, state.triggered_milestones)


@pytest.mark.parametrize("combinator, expected", [("all", 300), ("any", 1200)])
def test_date_and_metric_combination_preserves_event_month(combinator, expected):
    goal = milestone([metric(value=100), {"kind": "date", "date": "2026-10"}], combinator=combinator)
    result = run_simulation(plan(goal))
    assert result.yearly_snapshots[0].expenses == expected


def test_fractional_age_and_deadline_months_prorate_events():
    goal = milestone([{"kind": "age", "owner": "self", "age": 46.5}])
    assert run_simulation(plan(goal)).yearly_snapshots[0].expenses == pytest.approx(100)
    goal = milestone([{"kind": "date", "date": "2026-12"}], deadline={"kind": "date", "value": "2026-10", "action": "miss"})
    assert run_simulation(plan(goal)).metadata.milestone_outcomes[0].missed_year == 2026
    goal = replace(goal, conditions={**goal.conditions, "deadline": {"kind": "date", "value": "2026-10", "action": "fire"}})
    assert run_simulation(plan(goal)).yearly_snapshots[0].expenses == 300


def test_passive_income_completed_year_excludes_work_and_annualizes_partial_year():
    goal = milestone([metric("passive_income", 10_000)])
    assert run_simulation(replace(plan(goal), first_year_fraction=.5)).metadata.milestone_outcomes[0].year == 2027
    assert run_simulation(plan(milestone([metric("passive_income", 10_001)]))).metadata.milestone_outcomes[0].year is None


@pytest.mark.parametrize("items,deadline", [([], None), ([metric()] * 11, None), ([metric("account_balance")], None),
    ([metric(value=float("nan"))], None), ([metric(value_unit="multiple_of_metric")], None), ([metric("savings_rate")], None),
    ([metric(average_years=11)], None), ([{"kind": "date", "date": "2026-13"}], None),
    ([metric()], {"kind": "age", "value": -1, "action": "fire"})])
def test_schema_rejects_invalid_conditions(items, deadline):
    with pytest.raises(ValidationError):
        milestone(items, deadline=deadline)


@pytest.mark.anyio
async def test_api_validation_round_trip_and_dependencies(client):
    pid = (await client.post("/api/plans", json={"name": "Conditions", "birth_year": 1980})).json()["id"]
    path = f"/api/plans/{pid}/milestones"
    for settings in (None, {"combinator": "all", "items": [metric("account_balance", account_id=str(uuid4()))]}):
        bad = await client.post(path, json={"name": "Bad", "trigger_type": "conditions", "conditions": settings})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"
    base = (await client.post(path, json={"name": "Base", "trigger_type": "age", "trigger_value": 50})).json()
    settings = milestone([{"kind": "milestone", "milestone_id": base["id"]}]).conditions
    saved = await client.post(path, json={"name": "Goal", "trigger_type": "conditions", "conditions": settings})
    assert saved.status_code == 201, saved.text
    assert saved.json()["conditions"] == settings
    assert (await client.get(path)).json()[1]["conditions"] == settings
    assert (await client.put(f"{path}/{saved.json()['id']}", json={"conditions": None})).status_code == 422
    cycle = milestone([{"kind": "milestone", "milestone_id": saved.json()["id"]}]).conditions
    assert (await client.put(f"{path}/{base['id']}", json={"trigger_type": "conditions", "conditions": cycle})).status_code == 422
    assert (await client.delete(f"{path}/{base['id']}")).status_code == 409


@pytest.mark.anyio
async def test_duplicate_remaps_account_other_metric_milestone_and_deadline(client):
    cid = (await client.post("/api/clients/personal")).json()["id"]
    created = await client.post("/api/plans", json={"name": "Copy", "birth_year": 1980, "client_id": cid})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    account = await client.post(f"/api/plans/{pid}/accounts", json={"name": "Cash", "account_type": "checking", "balance": 100})
    assert account.status_code == 201, account.text
    aid = account.json()["id"]
    path = f"/api/plans/{pid}/milestones"
    base = (await client.post(path, json={"name": "Base", "trigger_type": "age", "trigger_value": 50})).json()["id"]
    settings = milestone([metric(value=1, value_unit="multiple_of_metric", other_metric="account_balance", account_id=aid), {"kind": "milestone", "milestone_id": base}], deadline={"kind": "milestone", "value": base, "action": "fire"}).conditions
    assert (await client.post(path, json={"name": "Goal", "trigger_type": "conditions", "conditions": settings})).status_code == 201
    blocked = await client.delete(f"/api/plans/{pid}/accounts/{aid}")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "CONFLICT"
    response = await client.post(f"/api/plans/{pid}/duplicate")
    assert response.status_code == 201, response.text
    copied = response.json()
    copied_account = (await client.get(f"/api/plans/{copied['id']}/accounts")).json()[0]["id"]
    by_name = {row["name"]: row for row in copied["milestones"]}
    conditions = by_name["Goal"]["conditions"]
    assert conditions["items"][0]["account_id"] == copied_account != aid
    assert conditions["items"][1]["milestone_id"] == by_name["Base"]["id"] != base
    assert conditions["deadline"]["value"] == by_name["Base"]["id"]


def test_past_deadline_is_already_effective_or_missed_at_plan_start():
    items = [metric(value=0)]
    fire = milestone(items, deadline={"kind": "date", "value": "2025-10", "action": "fire"})
    result = run_simulation(plan(fire))
    assert result.metadata.milestone_outcomes[0].year == 2025
    assert result.yearly_snapshots[0].expenses == 1200
    miss = replace(fire, conditions={**fire.conditions, "deadline": {"kind": "date", "value": "2025-10", "action": "miss"}})
    result = run_simulation(plan(miss))
    assert result.metadata.milestone_outcomes[0].missed_year == 2025
    assert all(row.expenses == 0 for row in result.yearly_snapshots)


def test_any_condition_timing_settles_earliest_same_year_dependency():
    state = SimState(2026)
    goal = milestone([{"kind": "date", "date": "2026-12"}, {"kind": "milestone", "milestone_id": "base"}], combinator="any")
    base = milestone([{"kind": "date", "date": "2026-03"}], identity="base")
    assert evaluate(state, [goal, base]) == ["goal", "base"]
    assert state.triggered_milestone_months["goal"] == 3


def test_real_monte_carlo_trials_keep_missed_milestones_unreached():
    goal = milestone([metric(value=1_000_000)], deadline={"kind": "year", "value": 2027, "action": "miss"})
    summary = run_monte_carlo(plan(goal), n_trials=3, seed=19).milestone_distributions[0]
    assert (summary.reached_trials, summary.unreached_trials, summary.reach_rate) == (0, 3, 0)


def test_savings_rate_uses_actual_contributions_over_gross_income():
    goal = milestone([metric("savings_rate", 80, value_unit="percent")])
    inputs = replace(plan(goal), income_streams=[IncomeData("wages", "Wages", 100_000)],
                     expenses=[ExpenseData("living", "Living", 20_000)])
    result = run_simulation(inputs)
    opening = result.yearly_snapshots[0]
    assert sum(flow.amount for flow in opening.cash_flow.contributions) == 80_000
    assert opening.gross_income == 100_000
    assert result.metadata.milestone_outcomes[0].year == 2027


@pytest.mark.anyio
async def test_conditions_reject_another_households_account_and_accept_own_snapshot(client, db_session):
    owner = User(id=uuid4(), is_anonymous=True, settings={})
    foreign = CurrentAccount(id=uuid4(), user_id=owner.id, name="Private", account_type="checking", balance=100)
    db_session.add_all([owner, foreign])
    db_session.commit()
    response = await client.post("/api/plans", json={"name": "Snapshot", "birth_year": 1980,
                                                 "plan_type": "FIXED_DATE", "start_date": "2026-01-01"})
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    path = f"/api/plans/{pid}/milestones"
    bad = await client.post(path, json={"name": "Bad", "trigger_type": "conditions", "conditions": milestone([metric("account_balance", account_id=str(foreign.id))]).conditions})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
    # Frozen account identities belong to the plan even without a current account.
    aid = str(uuid4())
    response = await client.put(f"/api/plans/{pid}", json={"snapshot_conditions": {aid: {"name": "Frozen cash", "account_type": "checking", "balance": 100}}})
    assert response.status_code == 200, response.text
    saved = await client.post(path, json={"name": "Snapshot goal", "trigger_type": "conditions", "conditions": milestone([metric("account_balance", account_id=aid)]).conditions})
    assert saved.status_code == 201, saved.text
    simulated = await client.post(f"/api/plans/{pid}/simulate")
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["metadata"]["milestone_outcomes"][0]["year"] == 2026


def test_numeric_age_deadline_is_normalized_before_engine_evaluation():
    goal = milestone([metric(value=1_000_000)], deadline={"kind": "age", "value": "46.5", "action": "fire"})
    result = run_simulation(plan(goal))
    assert result.metadata.milestone_outcomes[0].year == 2026
    assert result.yearly_snapshots[0].expenses == pytest.approx(100)


def test_stateless_request_validates_and_preserves_condition_settings():
    goal = milestone([metric("account_balance", 100, account_id="cash"), {"kind": "date", "date": "2026-10"}])
    body = asdict(plan(goal))
    request = PlanDataRequest.model_validate(body)
    converted = request_to_engine_data(request)
    assert converted.milestones[0].conditions == goal.conditions
    assert run_simulation(converted).yearly_snapshots[0].expenses == 300
    body["milestones"][0]["conditions"]["items"][0]["account_id"] = "absent"
    with pytest.raises(ValidationError, match="Condition references must belong to this plan"):
        PlanDataRequest.model_validate(body)
