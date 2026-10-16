"""Shared plan-scoped router helpers (app.routers.helpers) and the routes that use them."""
import datetime
import re
import uuid
from functools import partial
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect

from app.models.milestone import Milestone
from app.routers import helpers, liabilities, plans, priorities
from tests.conftest import test_engine

SERVER_TODAY = datetime.date(2028, 1, 1)
CLIENT_DATE = {"X-Client-Date": "2027-12-31"}


class _ServerDate(datetime.date):
    @classmethod
    def today(cls):
        return SERVER_TODAY


@pytest.fixture
def new_year_server(monkeypatch):
    """The server clock reads 1 January 2028 while the user is still on 31 December."""
    monkeypatch.setattr(helpers, "datetime", SimpleNamespace(date=_ServerDate))


def _columns(account) -> dict:
    return {column.key: getattr(account, column.key) for column in inspect(type(account)).column_attrs}


@pytest.mark.anyio
async def test_snapshot_accounts_match_between_loader_and_duplicate(client, db_session, test_user, monkeypatch):
    named, unnamed = str(uuid.uuid4()), str(uuid.uuid4())
    snapshot = {
        named: {
            "name": "Inherited IRA", "balance": 45000, "account_type": "traditional_ira", "owner": "self",
            "beneficiary_type": "non_edb", "cost_basis": 1000, "inherited_year": 2024,
            "investment_settings": {"stock_allocation": 0.6}, "include_in_liquid": True,
        },
        unnamed: {"balance": 1200, "account_type": "savings"},
    }
    created = await client.post("/api/plans", json={
        "name": "Historical", "birth_year": 1980, "plan_type": "FIXED_DATE", "start_date": "2026-01-01",
        "snapshot_conditions": snapshot,
    })
    assert created.status_code == 201, created.text
    plan_id = uuid.UUID(created.json()["id"])

    loaded: list = []
    real_convert = helpers.plan_to_engine_data

    def convert(plan, accounts, **kwargs):
        loaded.extend(accounts)
        return real_convert(plan, accounts, **kwargs)

    monkeypatch.setattr(helpers, "plan_to_engine_data", convert)
    helpers.load_plan_data(plan_id, test_user, db_session)
    # Loader accounts stay transient: loading a plan never saves them.
    assert all(inspect(account).transient for account in loaded)

    copied: list = []
    real_copy = plans.copy_plan

    def copy(db, source, accounts, **kwargs):
        copied.extend(accounts)
        return real_copy(db, source, accounts, **kwargs)

    monkeypatch.setattr(plans, "copy_plan", copy)
    workspace = (await client.post("/api/clients/personal")).json()
    duplicate = await client.post(f"/api/plans/{plan_id}/duplicate", json={"client_id": workspace["id"]})
    assert duplicate.status_code == 201, duplicate.text

    by_id = {str(account.id): _columns(account) for account in loaded}
    copies = {str(account.id): _columns(account) for account in copied}
    assert set(by_id) == set(copies) == {named, unnamed}
    assert by_id[named] == copies[named]
    assert by_id[named]["inherited_year"] == 2024
    # Each caller keeps its own name for an entry saved without one.
    assert by_id[unnamed].pop("name") == "" and copies[unnamed].pop("name") == "Imported account"
    assert by_id[unnamed] == copies[unnamed]


@pytest.mark.anyio
async def test_bulk_priority_save_loads_the_plan_at_most_twice(
    client, db_session, test_user, demo_plan, monkeypatch,
):
    current = (await client.get(f"/api/plans/{demo_plan.id}/priorities")).json()
    items = [{key: value for key, value in item.items() if key not in ("id", "plan_id")} for item in current["items"]]
    assert len(items) >= 4
    statements: list[str] = []
    in_route = False
    real_get_plan = priorities.get_plan_or_404

    def get_plan(*args, **kwargs):
        # The route's first call; the router's write guard (app.access) runs before it.
        nonlocal in_route
        in_route = True
        return real_get_plan(*args, **kwargs)

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        if in_route:
            statements.append(statement)

    monkeypatch.setattr(priorities, "get_plan_or_404", get_plan)
    event.listen(test_engine, "before_cursor_execute", record)
    try:
        saved = await client.put(f"/api/plans/{demo_plan.id}/priorities",
                                 json={"items": items, "expected_revision": current["revision"]})
    finally:
        event.remove(test_engine, "before_cursor_execute", record)
    assert saved.status_code == 200, saved.text
    # Validation runs before the old rules are deleted; the commit's scenario
    # sync (app.scenarios.hooks) reads plans afterwards on its own.
    validation = statements[:next(i for i, s in enumerate(statements) if re.match(r"\s*DELETE\b", s))]
    plan_loads = [s for s in validation if re.match(r"\s*SELECT\b", s) and re.search(r"\bFROM plans\b", s)]
    assert len(plan_loads) <= 2, plan_loads


@pytest.mark.anyio
async def test_create_plan_uses_the_client_year_for_the_retirement_milestone(client, new_year_server):
    body = {"name": "Now", "birth_year": 1968, "plan_type": "NOW", "retirement_milestone_age": 60}
    local = await client.post("/api/plans", json=body, headers=CLIENT_DATE)
    assert local.status_code == 201, local.text
    # Age 60 is reached in 2028: next year for the user, already this year by the server clock.
    assert [m["name"] for m in local.json()["milestones"]] == ["Retirement"]
    server = await client.post("/api/plans", json=body)
    assert server.status_code == 201, server.text
    assert server.json()["milestones"] == []


@pytest.mark.anyio
async def test_sale_year_accepts_the_client_year_for_a_now_plan(client, new_year_server):
    plan = (await client.post("/api/plans", json={"name": "Now", "birth_year": 1980, "plan_type": "NOW"})).json()
    asset = {"name": "Cabin", "current_value": 200000, "sale_year": 2027}
    accepted = await client.post(f"/api/plans/{plan['id']}/real-assets", json=asset, headers=CLIENT_DATE)
    assert accepted.status_code == 201, accepted.text
    rejected = await client.post(f"/api/plans/{plan['id']}/real-assets", json=asset)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"] == [{"field": "sale_year", "reason": "must be 2028 or later"}]
    unsold = await client.post(f"/api/plans/{plan['id']}/real-assets", json={**asset, "sale_year": None})
    path = f"/api/plans/{plan['id']}/real-assets/{unsold.json()['id']}"
    assert (await client.put(path, json={"sale_year": 2027})).status_code == 422
    updated = await client.put(path, json={"sale_year": 2027}, headers=CLIENT_DATE)
    assert updated.status_code == 200, updated.text
    assert updated.json()["sale_year"] == 2027


@pytest.mark.anyio
async def test_amortization_schedule_starts_in_the_client_year(client, new_year_server, monkeypatch):
    plan = (await client.post("/api/plans", json={"name": "Now", "birth_year": 1980, "plan_type": "NOW"})).json()
    loan = await client.post(f"/api/plans/{plan['id']}/liabilities", json={
        "name": "Car", "principal_balance": 10000, "interest_rate": 6, "term_months": 24, "interest_method": "daily",
    })
    assert loan.status_code == 201, loan.text
    start_years: list = []
    real_compute = liabilities._compute_amortization

    def compute(liability, start_year=None):
        start_years.append(start_year)
        return real_compute(liability, start_year)

    monkeypatch.setattr(liabilities, "_compute_amortization", compute)
    response = await client.get(f"/api/plans/{plan['id']}/liabilities/{loan.json()['id']}/amortization",
                                headers=CLIENT_DATE)
    assert response.status_code == 200, response.text
    assert start_years == [2027]


def _rejection(call) -> tuple[str, list]:
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == 422
    error = caught.value.detail["error"]
    assert error["code"] == "VALIDATION_ERROR"
    return error["message"], error["details"]


@pytest.mark.anyio
async def test_liability_milestone_fields_report_their_own_field(client, db_session, test_user):
    plan_id = uuid.UUID((await client.post(
        "/api/plans", json={"name": "Debts", "birth_year": 1980, "plan_type": "NOW"})).json()["id"])
    own = Milestone(id=uuid.uuid4(), plan_id=plan_id, name="Payoff", trigger_type="age", trigger_value=60)
    db_session.add(own)
    db_session.commit()
    foreign = uuid.uuid4()
    empty = {"linked_asset_id": None, "offset_account_id": None, "forgiveness": None,
             "recurrence_end_milestone_id": None, "payoff_milestone_id": None}
    cases = {
        "forgiveness.milestone_id": {"forgiveness": SimpleNamespace(milestone_id=foreign)},
        "recurrence_end_milestone_id": {"recurrence_end_milestone_id": foreign},
        "payoff_milestone_id": {"payoff_milestone_id": foreign},
    }
    for field, values in cases.items():
        body = SimpleNamespace(**{**empty, **values})
        message, details = _rejection(partial(helpers.validate_liability_fks, plan_id, test_user.id, body, db_session))
        assert message == f"Milestone {foreign} does not belong to this plan"
        assert details == [{"field": field, "reason": "not found in plan"}]
    # The plan's own milestone passes in every field; a forgiveness without one is skipped.
    helpers.validate_liability_fks(plan_id, test_user.id, SimpleNamespace(**{
        **empty, "forgiveness": SimpleNamespace(milestone_id=own.id),
        "recurrence_end_milestone_id": own.id, "payoff_milestone_id": own.id,
    }), db_session)
    helpers.validate_liability_fks(plan_id, test_user.id, SimpleNamespace(
        **{**empty, "forgiveness": SimpleNamespace(milestone_id=None)}), db_session)
    for field in ("start_milestone_id", "end_milestone_id"):
        body = SimpleNamespace(**{"start_milestone_id": own.id, "end_milestone_id": own.id, field: foreign})
        message, details = _rejection(partial(helpers.validate_milestone_fks, plan_id, body, db_session))
        assert message == f"Milestone {foreign} does not belong to this plan"
        assert details == [{"field": field, "reason": "not found in plan"}]
