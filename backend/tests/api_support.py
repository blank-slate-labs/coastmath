"""Shared helpers for API and persistence tests against the SQLite fixtures."""
from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.models.account import CurrentAccount
from app.models.plan import Plan


def new_id() -> str:
    """A random UUID string, for ids that match no saved record."""
    return str(uuid.uuid4())


def assert_error_shape(body: dict) -> None:
    """Assert the response body matches the shared error envelope."""
    assert "error" in body
    err = body["error"]
    assert "code" in err
    assert "message" in err
    assert "details" in err


async def create_plan(client: AsyncClient, **overrides) -> dict:
    """POST a plan ("Test Plan", born 1990, plan type NOW unless overridden),
    expect 201 and return the saved plan."""
    body = {"name": "Test Plan", "birth_year": 1990, "plan_type": "NOW", **overrides}
    response = await client.post("/api/plans", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def save_priorities(client: AsyncClient, plan_id: str, items: list[dict]):
    """PUT the plan's priority rules at its current revision; returns the response."""
    url = f"/api/plans/{plan_id}/priorities"
    revision = (await client.get(url)).json()["revision"]
    return await client.put(url, json={"expected_revision": revision, "items": items})


def assert_error(response, status: int, code: str, field: str | None = None) -> dict:
    """Assert the status, the error code, a non-empty message and a details list,
    and when `field` is given that some detail names it; return the error
    envelope's body."""
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], list)
    if field is not None:
        assert field in {detail.get("field") for detail in error["details"]}, error
    return error


async def contract_plan(client):
    response = await client.post('/api/plans', json={'name': 'Contract', 'birth_year': 1976, 'life_expectancy': 52, 'plan_type': 'FIXED_DATE', 'start_date': '2026-01-01'})
    assert response.status_code == 201, response.text
    return response.json()['id']


async def invested_plan(client: AsyncClient) -> str:
    plan = await client.post("/api/plans", json={"name": "Trials", "birth_year": 1964, "life_expectancy": 80, "plan_type": "NOW"})
    assert plan.status_code == 201, plan.text
    account = await client.post("/api/accounts", json={"name": "Invested", "account_type": "taxable_brokerage", "balance": 300_000})
    assert account.status_code == 201, account.text
    plan_id = plan.json()["id"]
    expense = await client.post(f"/api/plans/{plan_id}/expenses", json={"name": "Living", "annual_amount": 24_000})
    assert expense.status_code == 201, expense.text
    return plan_id


def blob(**changes):
    return {'plan_id': str(uuid.uuid4()), 'birth_year': 1976, 'start_year': 2026, 'life_expectancy': 52,
            'accounts': {'cash': {'account_type': 'checking', 'balance': 10000}},
            'assumptions': {'inflation_rate': 0, 'stock_growth_rate': 0}, **changes}


def make_plan(db_session, test_user) -> Plan:
    plan = Plan(
        user_id=test_user.id,
        name="CostBasis Test Plan",
        birth_year=1990,
        filing_status="single",
        plan_type="NOW",
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def make_account(db_session, test_user, *, balance: float, cost_basis: float | None) -> CurrentAccount:
    acct = CurrentAccount(
        user_id=test_user.id,
        name="Brokerage",
        account_type="taxable_brokerage",
        balance=balance,
        cost_basis=cost_basis,
    )
    db_session.add(acct)
    db_session.commit()
    db_session.refresh(acct)
    return acct
