"""Partially discretionary expenses: a 0-100 percent that flexible spending may cut.

`discretionary_percent` wins over `category` when set; `category` mirrors it
(>= 50 discretionary) for clients that only read the category. A null percent
keeps the category's all-or-nothing meaning, so old plans project unchanged.
"""
import dataclasses
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.expense import Expense
from app.models.plan import Plan
from app.schemas.expense import (
    category_for_discretionary_percent,
    sync_expense_category,
)
from app.seed import seed_demo_plan
from coastmath.engine.flex_spending import apply_flex_rules, discretionary_share
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    ExpenseData,
    IncomeData,
    PlanData,
    SimState,
    SpendingRulesData,
)
from coastmath.schemas.simulation import NamedAmountSchema
from tests.api_support import create_plan

# --- Share resolution and the category rule ---------------------------------

@pytest.mark.parametrize(("fraction", "category", "share"), [
    (0.4, "essential", 0.4),        # an explicit percent wins over a conflicting category
    (0.0, "discretionary", 0.0),
    (1.0, None, 1.0),
    (None, "discretionary", 1.0),
    (None, "essential", 0.0),
    (None, None, None),             # uncategorized: never cut, as before
    (None, "other", None),          # stateless input allows any string; only "discretionary" was ever cut
])
def test_share_resolves_percent_then_category(fraction, category, share):
    expense = ExpenseData(id="e", name="E", annual_amount=1000, category=category, discretionary_fraction=fraction)
    assert discretionary_share(expense) == share


@pytest.mark.parametrize(("percent", "category"), [
    (0, "essential"), (49.99, "essential"), (50, "discretionary"), (100, "discretionary"),
])
def test_category_mirrors_the_larger_share(percent, category):
    assert category_for_discretionary_percent(percent) == category


def test_sync_rule_for_writes():
    # A percent in the write wins over a category sent with it.
    assert sync_expense_category({"discretionary_percent": 70, "category": "essential"}) == {
        "discretionary_percent": 70, "category": "discretionary"}
    # A category-only write that disagrees with the saved percent clears it.
    assert sync_expense_category({"category": "essential"}, 70) == {"category": "essential", "discretionary_percent": None}
    assert sync_expense_category({"category": None}, 70) == {"category": None, "discretionary_percent": None}
    # One that agrees, or an unrelated write, keeps it.
    assert sync_expense_category({"category": "discretionary"}, 70) == {"category": "discretionary"}
    assert sync_expense_category({"name": "Food"}, 70) == {"name": "Food"}
    # Explicitly clearing the percent leaves the category as it is.
    assert sync_expense_category({"discretionary_percent": None}, 70) == {"discretionary_percent": None}


# --- Flex rules ---------------------------------------------------------------

def _flex_plan(**rules) -> PlanData:
    return PlanData(plan_id="p", birth_year=1990, filing_status="single", life_expectancy=95, start_year=2024,
                    spending_rules=SpendingRulesData(**{"flex_threshold": -0.05, "flex_reduction": 0.20, **rules}))


def _down_year() -> SimState:
    state = SimState(year=2026)
    state.return_history = [-0.10, 0.0]  # one weak completed year, then the current year
    return state


def test_flex_cut_reduces_only_the_discretionary_part():
    expenses = [
        ExpenseData(id="g", name="Groceries", annual_amount=10_000, category="essential", discretionary_fraction=0.4),
        ExpenseData(id="t", name="Travel", annual_amount=5_000, category="discretionary"),
        ExpenseData(id="r", name="Rent", annual_amount=20_000, category="essential"),
        ExpenseData(id="i", name="Insurance", annual_amount=1_000),
    ]
    result = apply_flex_rules(expenses, _flex_plan(), _down_year(), 2026)
    # 60% essential paid in full + 40% cut by 20%: 6,000 + 3,200.
    assert result[0].annual_amount == pytest.approx(9_200)
    assert result[0].annual_amount == pytest.approx(10_000 - 0.4 * 10_000 * 0.20)
    assert result[1].annual_amount == 5_000 * 0.8
    assert result[2] is expenses[2] and result[3] is expenses[3]
    assert expenses[0].annual_amount == 10_000  # inputs are never mutated


def test_spending_floor_limits_the_cut_of_the_discretionary_part():
    expense = ExpenseData(id="g", name="Groceries", annual_amount=10_000, discretionary_fraction=0.4)
    (result,) = apply_flex_rules([expense], _flex_plan(flex_reduction=0.9, spending_floor=0.75), _down_year(), 2026)
    assert result.annual_amount == pytest.approx(6_000 + 4_000 * 0.75)


def test_category_only_expenses_flex_exactly_as_before():
    """A null percent takes the category path byte for byte; explicit 0/100 match it."""
    plan, state = _flex_plan(flex_reduction=0.137), _down_year()
    legacy = [ExpenseData(id="d", name="D", annual_amount=7_321.17, category="discretionary"),
              ExpenseData(id="e", name="E", annual_amount=4_000.01, category="essential")]
    explicit = [dataclasses.replace(legacy[0], discretionary_fraction=1.0),
                dataclasses.replace(legacy[1], discretionary_fraction=0.0)]
    old = apply_flex_rules(legacy, plan, state, 2026)
    assert old[0].annual_amount == 7_321.17 * (1 - 0.137)
    assert old[1] is legacy[1]
    assert [e.annual_amount for e in apply_flex_rules(explicit, plan, state, 2026)] == [e.annual_amount for e in old]


# --- Simulator outputs --------------------------------------------------------

def _sim_plan(expenses, **overrides) -> PlanData:
    values = dict(
        plan_id="00000000-0000-0000-0000-000000000001", birth_year=1990, filing_status="single",
        life_expectancy=3, start_year=1990,
        income_streams=[IncomeData(id="inc", name="Salary", annual_amount=60_000)],
        expenses=expenses,
        # A zero-return checking account: every completed year returns 0%, below the threshold.
        spending_rules=SpendingRulesData(flex_threshold=0.10, flex_reduction=0.20, lookback_years=1),
        accounts={"chk": AccountInfo(balance=100_000, account_type="checking")},
    )
    values.update(overrides)
    return PlanData(**values)


def _rows(snapshot):
    return {row.name: row for row in snapshot.cash_flow.expenses}


def test_simulation_splits_paid_spending_by_the_share():
    groceries = ExpenseData(id="g", name="Groceries", annual_amount=10_000, inflation_linked=False,
                            category="essential", discretionary_fraction=0.4)
    rent = ExpenseData(id="r", name="Rent", annual_amount=12_000, inflation_linked=False, category="essential")
    first, second = run_simulation(_sim_plan([groceries, rent])).yearly_snapshots[:2]

    # No completed year yet: paid in full, 40% of it discretionary.
    assert first.flex_spending_reduction == 0
    assert _rows(first)["Groceries"].amount == pytest.approx(10_000)
    assert _rows(first)["Groceries"].discretionary_amount == pytest.approx(4_000)
    # After a weak year only the discretionary 4,000 is cut by 20%.
    row = _rows(second)["Groceries"]
    assert row.amount == pytest.approx(9_200)
    assert row.discretionary_amount == pytest.approx(3_200)
    assert row.amount - row.discretionary_amount == pytest.approx(6_000)  # essential part untouched
    assert row.category == "essential"
    assert second.flex_spending_reduction == pytest.approx(800)
    # Category-only rows report no split.
    assert _rows(second)["Rent"].discretionary_amount is None
    assert _rows(second)["Rent"].amount == pytest.approx(12_000)


def test_specifically_funded_expense_reports_its_split():
    expense = ExpenseData(id="g", name="Groceries", annual_amount=10_000, inflation_linked=False,
                          specific_funding_source_id="chk", discretionary_fraction=0.25)
    first = run_simulation(_sim_plan([expense])).yearly_snapshots[0]
    row = _rows(first)["Groceries"]
    assert row.discretionary_amount == pytest.approx(row.amount * 0.25)


@pytest.mark.parametrize(("category", "fraction"), [("discretionary", 1.0), ("essential", 0.0)])
def test_explicit_extremes_project_like_their_category(category, fraction):
    def run(value):
        expense = ExpenseData(id="x", name="X", annual_amount=9_000, category=category, discretionary_fraction=value)
        return run_simulation(_sim_plan([expense], life_expectancy=6)).yearly_snapshots

    legacy, explicit = run(None), run(fraction)
    assert [s.net_worth for s in explicit] == [s.net_worth for s in legacy]
    assert [s.flex_spending_reduction for s in explicit] == [s.flex_spending_reduction for s in legacy]
    assert [_rows(s)["X"].amount for s in explicit] == [_rows(s)["X"].amount for s in legacy]
    assert all(_rows(s)["X"].discretionary_amount is None for s in legacy)


def test_split_is_omitted_from_rows_without_one():
    assert "discretionary_amount" not in NamedAmountSchema(name="Rent", amount=1.0, category="essential").model_dump()
    assert "discretionary_amount" not in NamedAmountSchema(name="Rent", amount=1.0).model_dump_json()
    split = NamedAmountSchema(name="Food", amount=10.0, category="essential", discretionary_amount=4.0)
    assert split.model_dump()["discretionary_amount"] == 4.0


# --- API ----------------------------------------------------------------------

async def _plan(client) -> str:
    return (await create_plan(client, name="Shares", birth_year=1980))["id"]


@pytest.mark.anyio
async def test_percent_round_trips_and_mirrors_category(client):
    pid = await _plan(client)
    base = f"/api/plans/{pid}/expenses"
    created = await client.post(base, json={"name": "Groceries", "annual_amount": 9000,
                                            "category": "discretionary", "discretionary_percent": 30})
    assert created.status_code == 201, created.text
    # The percent wins over the conflicting category sent with it.
    assert (created.json()["discretionary_percent"], created.json()["category"]) == (30, "essential")
    path = f"{base}/{created.json()['id']}"
    for percent, category in ((50, "discretionary"), (49.5, "essential"), (100, "discretionary"), (0, "essential")):
        updated = await client.put(path, json={"discretionary_percent": percent})
        assert updated.status_code == 200, updated.text
        assert (updated.json()["discretionary_percent"], updated.json()["category"]) == (percent, category)
    await client.put(path, json={"discretionary_percent": 62.5})
    assert [(r["discretionary_percent"], r["category"]) for r in (await client.get(base)).json()] == [(62.5, "discretionary")]
    plan = (await client.get(f"/api/plans/{pid}")).json()
    assert plan["expenses"][0]["discretionary_percent"] == 62.5
    legacy = await client.post(base, json={"name": "Rent", "annual_amount": 24000, "category": "essential"})
    assert (legacy.json()["discretionary_percent"], legacy.json()["category"]) == (None, "essential")


@pytest.mark.anyio
@pytest.mark.parametrize("value", [-1, 100.01, 1e9, "half"])
async def test_out_of_range_percent_is_rejected_with_the_shared_envelope(client, value):
    pid = await _plan(client)
    base = f"/api/plans/{pid}/expenses"
    rejected = await client.post(base, json={"name": "Bad", "annual_amount": 100, "discretionary_percent": value})
    assert rejected.status_code == 422
    error = rejected.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [detail["field"] for detail in error["details"]] == ["discretionary_percent"]
    assert (await client.get(base)).json() == []

    saved = await client.post(base, json={"name": "Food", "annual_amount": 100, "discretionary_percent": 40})
    rejected = await client.put(f"{base}/{saved.json()['id']}", json={"discretionary_percent": value})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"][0]["field"] == "discretionary_percent"
    assert (await client.get(base)).json()[0]["discretionary_percent"] == 40


@pytest.mark.anyio
async def test_update_that_omits_the_percent_keeps_it(client):
    pid = await _plan(client)
    base = f"/api/plans/{pid}/expenses"
    saved = await client.post(base, json={"name": "Food", "annual_amount": 9000, "discretionary_percent": 70})
    path = f"{base}/{saved.json()['id']}"
    # Older clients (native) send only the fields they changed, or an agreeing category.
    for body in ({"name": "Groceries"}, {"annual_amount": 9600}, {"category": "discretionary"}):
        updated = await client.put(path, json=body)
        assert updated.status_code == 200, updated.text
        assert (updated.json()["discretionary_percent"], updated.json()["category"]) == (70, "discretionary")
    # Switching the category alone returns to its all-or-nothing meaning.
    switched = await client.put(path, json={"category": "essential"})
    assert (switched.json()["discretionary_percent"], switched.json()["category"]) == (None, "essential")
    # An explicit null clears the percent and keeps the category it last mirrored.
    await client.put(path, json={"discretionary_percent": 20})
    cleared = await client.put(path, json={"discretionary_percent": None})
    assert (cleared.json()["discretionary_percent"], cleared.json()["category"]) == (None, "essential")


@pytest.mark.anyio
async def test_percent_takes_part_in_opening_value_preconditions(client):
    pid = await _plan(client)
    base = f"/api/plans/{pid}/expenses"
    saved = (await client.post(base, json={"name": "Food", "annual_amount": 9000, "category": "essential"})).json()
    path = f"{base}/{saved['id']}"
    # The web editor sends the opening value of each changed field, category included.
    edit = {"discretionary_percent": 60, "category": "discretionary",
            "expected_values": {"discretionary_percent": None, "category": "essential"}}
    assert (await client.put(path, json=edit)).status_code == 200
    stale = await client.put(path, json=edit)
    assert stale.status_code == 409
    assert {d["field"] for d in stale.json()["error"]["details"]} == {"discretionary_percent", "category"}
    reviewed = await client.put(path, json={"discretionary_percent": 30,
                                            "expected_values": {"discretionary_percent": 60}})
    assert reviewed.status_code == 200, reviewed.text
    assert (reviewed.json()["discretionary_percent"], reviewed.json()["category"]) == (30, "essential")


@pytest.mark.anyio
async def test_duplicate_copies_the_percent(client):
    pid = await _plan(client)
    await client.post(f"/api/plans/{pid}/expenses", json={"name": "Food", "annual_amount": 9000, "discretionary_percent": 35})
    await client.post(f"/api/plans/{pid}/expenses", json={"name": "Rent", "annual_amount": 24000, "category": "essential"})
    copied = await client.post(f"/api/plans/{pid}/duplicate")
    assert copied.status_code == 201, copied.text
    assert sorted((r["name"], r["discretionary_percent"], r["category"]) for r in copied.json()["expenses"]) == [
        ("Food", 35, "essential"), ("Rent", None, "essential"),
    ]


@pytest.mark.anyio
async def test_intake_resubmission_keeps_a_split_expense(client):
    pid = await _plan(client)
    answers = {"retirement_age": 65, "retirement_spending": 60000}
    assert (await client.post(f"/api/plans/{pid}/intake", json=answers)).status_code == 200
    (expense,) = (await client.get(f"/api/plans/{pid}/expenses")).json()
    assert (expense["discretionary_percent"], expense["category"]) == (None, "essential")
    await client.put(f"/api/plans/{pid}/expenses/{expense['id']}", json={"discretionary_percent": 75})
    answers["retirement_spending"] = 72000
    assert (await client.post(f"/api/plans/{pid}/intake", json=answers)).status_code == 200
    (expense,) = (await client.get(f"/api/plans/{pid}/expenses")).json()
    assert (expense["annual_amount"], expense["discretionary_percent"], expense["category"]) == (72000, 75, "discretionary")


def test_database_rejects_an_out_of_range_percent(db_session, test_user):
    plan = Plan(user_id=test_user.id, name="Shares", birth_year=1980)
    db_session.add(plan)
    db_session.flush()
    for percent in (None, 0, 42.5, 100):
        db_session.add(Expense(plan_id=plan.id, name=str(percent), annual_amount=1, discretionary_percent=percent))
    db_session.flush()
    db_session.add(Expense(plan_id=plan.id, name="Bad", annual_amount=1, discretionary_percent=100.5))
    with pytest.raises(IntegrityError, match="discretionary_percent"):
        db_session.flush()
    db_session.rollback()


@pytest.mark.anyio
async def test_saved_projection_reports_the_split(client, db_session, test_user):
    seed_demo_plan(test_user.id, db_session)
    db_session.commit()
    plan = db_session.query(Plan).filter_by(user_id=test_user.id).one()
    headers = {"X-Client-Date": "2026-10-09"}
    before = await client.post(f"/api/plans/{plan.id}/simulate", headers=headers)
    assert before.status_code == 200, before.text
    assert "discretionary_amount" not in before.text
    expense = db_session.query(Expense).filter_by(plan_id=plan.id, category="essential").first()
    updated = await client.put(f"/api/plans/{plan.id}/expenses/{expense.id}", json={"discretionary_percent": 40})
    assert updated.status_code == 200, updated.text
    after = await client.post(f"/api/plans/{plan.id}/simulate", headers=headers)
    assert after.status_code == 200, after.text
    rows = [row for year in after.json()["yearly_snapshots"] for row in (year["cash_flow"] or {}).get("expenses", [])
            if row["name"] == expense.name]
    assert rows
    for row in rows:
        assert row["discretionary_amount"] == pytest.approx(row["amount"] * 0.4)
        assert row["category"] == "essential"


@pytest.mark.anyio
async def test_stateless_projection_accepts_the_percent(client):
    def body(percent):
        expense = {"id": str(uuid.UUID(int=2)), "name": "Food", "annual_amount": 24000, "category": "discretionary"}
        if percent is not None:
            expense["discretionary_percent"] = percent
        return {"plan_id": str(uuid.UUID(int=3)), "birth_year": 1980, "start_year": 2026,
                "income_streams": [{"id": str(uuid.UUID(int=1)), "name": "Pay", "annual_amount": 52000}],
                "expenses": [expense]}

    legacy, split = [await client.post("/api/simulate/stateless", json=body(p)) for p in (None, 25)]
    assert [legacy.status_code, split.status_code] == [200, 200], split.text
    assert "discretionary_amount" not in legacy.text
    row = split.json()["yearly_snapshots"][0]["cash_flow"]["expenses"][0]
    assert row["category"] == "essential"
    assert row["discretionary_amount"] == pytest.approx(row["amount"] * 0.25)
    rejected = await client.post("/api/simulate/stateless", json=body(101))
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
