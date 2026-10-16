"""Incomes and expenses keep the unit their amount was entered in.

`amount_frequency` is a display/entry preference: `annual_amount` stays the
only value the engine reads, so projections must not change with it.
"""
import uuid
from typing import get_args

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.expense import Expense
from app.models.income import IncomeStream
from app.models.plan import Plan
from app.seed import seed_demo_plan
from coastmath.schemas.amount_frequency import AMOUNT_FREQUENCIES, AmountFrequency
from tests.api_support import create_plan

pytestmark = pytest.mark.anyio

RESOURCES = ("incomes", "expenses")


async def _plan(client) -> str:
    return (await create_plan(client, name="Units", birth_year=1980))["id"]


def test_units_and_periods_are_the_planned_set():
    assert get_args(AmountFrequency) == AMOUNT_FREQUENCIES
    assert AMOUNT_FREQUENCIES == ("annual", "quarterly", "monthly", "semimonthly", "biweekly", "weekly")


@pytest.mark.parametrize("resource", RESOURCES)
@pytest.mark.parametrize("frequency", AMOUNT_FREQUENCIES)
async def test_each_unit_round_trips_without_changing_the_annual_amount(client, resource, frequency):
    pid = await _plan(client)
    base = f"/api/plans/{pid}/{resource}"
    created = await client.post(base, json={"name": "Item", "annual_amount": 31200, "amount_frequency": frequency})
    assert created.status_code == 201, created.text
    assert created.json()["amount_frequency"] == frequency
    assert created.json()["annual_amount"] == 31200
    listed = (await client.get(base)).json()
    assert [(row["amount_frequency"], row["annual_amount"]) for row in listed] == [(frequency, 31200)]

    # Change to every other unit through an update; the plan read carries it too.
    path = f"{base}/{created.json()['id']}"
    for other in AMOUNT_FREQUENCIES:
        updated = await client.put(path, json={"amount_frequency": other})
        assert updated.status_code == 200, updated.text
        assert updated.json()["amount_frequency"] == other
        assert updated.json()["annual_amount"] == 31200
    plan = (await client.get(f"/api/plans/{pid}")).json()
    key = "income_streams" if resource == "incomes" else "expenses"
    assert plan[key][0]["amount_frequency"] == AMOUNT_FREQUENCIES[-1]


@pytest.mark.parametrize("model", [IncomeStream, Expense])
def test_database_rejects_an_unknown_unit(db_session, test_user, model):
    plan = Plan(user_id=test_user.id, name="Units", birth_year=1980)
    db_session.add(plan)
    db_session.flush()
    for frequency in (*AMOUNT_FREQUENCIES, None):
        db_session.add(model(plan_id=plan.id, name=str(frequency), annual_amount=1, amount_frequency=frequency))
    db_session.flush()
    db_session.add(model(plan_id=plan.id, name="Bad", annual_amount=1, amount_frequency="yearly"))
    with pytest.raises(IntegrityError, match="amount_frequency"):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("resource", RESOURCES)
async def test_omitted_unit_is_legacy_null(client, resource):
    pid = await _plan(client)
    created = await client.post(f"/api/plans/{pid}/{resource}", json={"name": "Legacy", "annual_amount": 1200})
    assert created.status_code == 201
    assert created.json()["amount_frequency"] is None


@pytest.mark.parametrize("resource", RESOURCES)
@pytest.mark.parametrize("value", ["yearly", "Monthly", "fortnightly", 12, ""])
async def test_invalid_unit_is_rejected_with_the_shared_envelope(client, resource, value):
    pid = await _plan(client)
    base = f"/api/plans/{pid}/{resource}"
    rejected = await client.post(base, json={"name": "Bad", "annual_amount": 1200, "amount_frequency": value})
    assert rejected.status_code == 422
    error = rejected.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [detail["field"] for detail in error["details"]] == ["amount_frequency"]
    assert (await client.get(base)).json() == []

    saved = await client.post(base, json={"name": "Good", "annual_amount": 1200, "amount_frequency": "monthly"})
    path = f"{base}/{saved.json()['id']}"
    rejected = await client.put(path, json={"amount_frequency": value})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
    assert rejected.json()["error"]["details"][0]["field"] == "amount_frequency"
    assert (await client.get(base)).json()[0]["amount_frequency"] == "monthly"


@pytest.mark.parametrize("resource", RESOURCES)
async def test_yearly_amount_past_one_trillion_is_refused(client, resource):
    # $99,999,999,999 a month saved as about $1.2 trillion a year.
    pid = await _plan(client)
    base = f"/api/plans/{pid}/{resource}"
    rejected = await client.post(base, json={"name": "Gym", "annual_amount": 1_199_999_999_988, "amount_frequency": "monthly"})
    assert rejected.status_code == 422
    assert [detail["field"] for detail in rejected.json()["error"]["details"]] == ["annual_amount"]
    assert (await client.get(base)).json() == []

    saved = await client.post(base, json={"name": "Gym", "annual_amount": 1e12})
    assert saved.status_code == 201, saved.text
    rejected = await client.put(f"{base}/{saved.json()['id']}", json={"annual_amount": 1e12 + 1})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"][0]["field"] == "annual_amount"
    assert (await client.get(base)).json()[0]["annual_amount"] == 1e12


@pytest.mark.parametrize("resource", RESOURCES)
async def test_update_that_omits_the_unit_keeps_it_and_null_clears_it(client, resource):
    pid = await _plan(client)
    base = f"/api/plans/{pid}/{resource}"
    saved = await client.post(base, json={"name": "Pay", "annual_amount": 31200, "amount_frequency": "biweekly"})
    path = f"{base}/{saved.json()['id']}"
    # An older client (native) knows nothing about the field and omits it.
    for body in ({"name": "Renamed"}, {"annual_amount": 52000}, {"name": "Again", "annual_amount": 26000}):
        updated = await client.put(path, json=body)
        assert updated.status_code == 200, updated.text
        assert updated.json()["amount_frequency"] == "biweekly"
    assert (await client.get(base)).json()[0]["amount_frequency"] == "biweekly"
    # An explicit null is a deliberate return to the legacy default.
    cleared = await client.put(path, json={"amount_frequency": None})
    assert cleared.status_code == 200
    assert cleared.json()["amount_frequency"] is None
    assert cleared.json()["annual_amount"] == 26000


async def test_expense_unit_takes_part_in_opening_value_preconditions(client):
    pid = await _plan(client)
    base = f"/api/plans/{pid}/expenses"
    saved = (await client.post(base, json={"name": "Rent", "annual_amount": 24000})).json()
    path = f"{base}/{saved['id']}"
    # Another editor saves a unit after this one opened the legacy record.
    assert (await client.put(path, json={"amount_frequency": "monthly"})).status_code == 200
    stale = await client.put(path, json={"amount_frequency": "weekly", "expected_values": {"amount_frequency": None}})
    assert stale.status_code == 409
    assert stale.json()["error"]["details"][0]["field"] == "amount_frequency"
    assert (await client.get(base)).json()[0]["amount_frequency"] == "monthly"
    reviewed = await client.put(path, json={"amount_frequency": "weekly", "expected_values": {"amount_frequency": "monthly"}})
    assert reviewed.status_code == 200
    assert reviewed.json()["amount_frequency"] == "weekly"
    # An unrelated guarded edit merges without touching the unit.
    renamed = await client.put(path, json={"name": "Lease", "expected_values": {"name": "Rent"}})
    assert renamed.status_code == 200
    assert renamed.json()["amount_frequency"] == "weekly"


async def test_duplicate_copies_the_unit(client):
    pid = await _plan(client)
    await client.post(f"/api/plans/{pid}/incomes", json={"name": "Pay", "annual_amount": 31200, "amount_frequency": "biweekly"})
    await client.post(f"/api/plans/{pid}/incomes", json={"name": "Legacy", "annual_amount": 1000})
    await client.post(f"/api/plans/{pid}/expenses", json={"name": "Rent", "annual_amount": 24000, "amount_frequency": "monthly"})
    await client.post(f"/api/plans/{pid}/expenses", json={"name": "Groceries", "annual_amount": 5200, "amount_frequency": "weekly"})
    copied = await client.post(f"/api/plans/{pid}/duplicate")
    assert copied.status_code == 201, copied.text
    data = copied.json()
    assert data["id"] != pid
    assert sorted((row["name"], row["amount_frequency"]) for row in data["income_streams"]) == [
        ("Legacy", None), ("Pay", "biweekly"),
    ]
    assert sorted((row["name"], row["amount_frequency"]) for row in data["expenses"]) == [
        ("Groceries", "weekly"), ("Rent", "monthly"),
    ]


async def test_intake_creates_yearly_expenses_and_keeps_a_later_unit(client):
    pid = await _plan(client)
    answers = {"retirement_age": 65, "retirement_spending": 60000}
    assert (await client.post(f"/api/plans/{pid}/intake", json=answers)).status_code == 200
    (expense,) = (await client.get(f"/api/plans/{pid}/expenses")).json()
    assert expense["amount_frequency"] == "annual"
    await client.put(f"/api/plans/{pid}/expenses/{expense['id']}", json={"amount_frequency": "monthly"})
    answers["retirement_spending"] = 72000
    assert (await client.post(f"/api/plans/{pid}/intake", json=answers)).status_code == 200
    (expense,) = (await client.get(f"/api/plans/{pid}/expenses")).json()
    assert (expense["annual_amount"], expense["amount_frequency"]) == (72000, "monthly")


async def test_projection_ignores_the_unit(client, db_session, test_user):
    seed_demo_plan(test_user.id, db_session)
    db_session.commit()
    plan = db_session.query(Plan).filter_by(user_id=test_user.id).one()
    headers = {"X-Client-Date": "2026-10-09"}
    before = await client.post(f"/api/plans/{plan.id}/simulate", headers=headers)
    assert before.status_code == 200, before.text
    rows = [*db_session.query(IncomeStream).filter_by(plan_id=plan.id), *db_session.query(Expense).filter_by(plan_id=plan.id)]
    assert rows
    # The repeated frequency list is longer than the rows; cycling stops at the last row.
    for row, frequency in zip(rows, AMOUNT_FREQUENCIES * len(rows), strict=False):
        row.amount_frequency = frequency
    db_session.commit()
    after = await client.post(f"/api/plans/{plan.id}/simulate", headers=headers)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()


async def test_stateless_projection_accepts_and_ignores_the_unit(client):
    def body(frequency):
        income = {"id": str(uuid.UUID(int=1)), "name": "Pay", "annual_amount": 52000}
        expense = {"id": str(uuid.UUID(int=2)), "name": "Rent", "annual_amount": 24000}
        if frequency:
            income["amount_frequency"] = frequency
            expense["amount_frequency"] = frequency
        return {"plan_id": str(uuid.UUID(int=3)), "birth_year": 1980, "start_year": 2026,
                "income_streams": [income], "expenses": [expense]}

    responses = [await client.post("/api/simulate/stateless", json=body(f)) for f in (None, "biweekly")]
    assert [r.status_code for r in responses] == [200, 200], responses[0].text
    assert responses[0].json() == responses[1].json()
