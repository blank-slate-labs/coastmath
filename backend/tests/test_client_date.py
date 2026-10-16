"""A "Now" plan starts on the user's local calendar day, not the server's UTC day."""

import calendar
import datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.models.financial_connection import utcnow
from app.routers import helpers
from app.routers.helpers import client_today
from app.routers.ledger import ledger_today


def test_client_today_uses_header_when_close_to_server_clock():
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    assert client_today(yesterday.isoformat()) == yesterday


def test_client_today_falls_back_on_garbage_or_far_dates():
    today = datetime.date.today()
    assert client_today(None) == today
    assert client_today("not-a-date") == today
    assert client_today((today - datetime.timedelta(days=30)).isoformat()) == today


def test_ledger_today_uses_the_header_and_keeps_the_utc_date_without_it():
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    assert ledger_today(yesterday.isoformat()) == yesterday
    assert ledger_today(None) == utcnow().date()


@pytest.mark.anyio
async def test_simulate_honours_client_date_header(client: AsyncClient):
    plan = (await client.post("/api/plans", json={"name": "Now", "birth_year": 1990, "plan_type": "NOW"})).json()
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    r = await client.post(f"/api/plans/{plan['id']}/simulate", headers={"X-Client-Date": yesterday.isoformat()})
    assert r.status_code == 200
    assert r.json()["metadata"]["start_date"] == yesterday.isoformat()


class _NewYearDay(datetime.date):
    """A server clock on 1 January 2028, a leap year."""

    @classmethod
    def today(cls):
        return cls(2028, 1, 1)


def _first_year_daily_interest(year: int, balance: float, rate: float, payment: float) -> float:
    """Interest paid in a loan's first year when each month accrues daily over its calendar days."""
    total = 0.0
    for month in range(1, 13):
        interest = balance * ((1 + rate / 365) ** calendar.monthrange(year, month)[1] - 1)
        balance -= payment - interest
        total += interest
    return total


@pytest.mark.anyio
async def test_amortization_schedule_starts_in_the_client_year(client: AsyncClient, monkeypatch):
    # The user is still on 31 December 2027 while the server has reached 2028.
    monkeypatch.setattr(helpers, "datetime", SimpleNamespace(date=_NewYearDay))
    plan = (await client.post("/api/plans", json={"name": "Now", "birth_year": 1980, "plan_type": "NOW"})).json()
    loan = await client.post(f"/api/plans/{plan['id']}/liabilities", json={
        "name": "Car", "principal_balance": 10000, "interest_rate": 6, "monthly_payment": 500,
        "term_months": 24, "interest_method": "daily",
    })
    assert loan.status_code == 201, loan.text
    path = f"/api/plans/{plan['id']}/liabilities/{loan.json()['id']}/amortization"

    local = await client.get(path, headers={"X-Client-Date": "2027-12-31"})
    server = await client.get(path)
    assert local.status_code == server.status_code == 200
    local_rows, server_rows = local.json()["schedule"], server.json()["schedule"]
    assert len(local_rows) == len(server_rows)
    assert [row.keys() for row in local_rows] == [row.keys() for row in server_rows]
    # February has 28 days in 2027 and 29 in 2028, so year one's interest shows which year it started in.
    assert local_rows[0]["interest_paid"] == pytest.approx(_first_year_daily_interest(2027, 10000, .06, 500), abs=.01)
    assert server_rows[0]["interest_paid"] == pytest.approx(_first_year_daily_interest(2028, 10000, .06, 500), abs=.01)
    assert local_rows[0]["interest_paid"] < server_rows[0]["interest_paid"]
