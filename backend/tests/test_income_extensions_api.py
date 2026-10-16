"""Growth schedules and former-spouse records persist, validate, copy and simulate."""

from dataclasses import asdict
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.engine.plan_converter import plan_to_engine_data
from app.models.account import CurrentAccount
from app.models.plan import Plan
from app.routers.helpers import plan_account_filter
from tests.api_support import create_plan

pytestmark = pytest.mark.anyio

SCHEDULE = [
    {"start_year": 2027, "end_year": 2028, "kind": "percent", "value": 3, "dollars": None},
    {"start_year": 2029, "end_year": None, "kind": "set_amount", "value": 120000, "dollars": "nominal"},
]
EX_SPOUSE = {
    "pia_monthly": 3000, "birth_year": 1958, "birth_month": 1, "marriage_years": 12,
    "marriage_lasted_10_years": False, "divorce_year": 2000, "divorce_month": None,
    "claim_age": 67, "death_year": None, "current_marriage_year": None, "survivor_claim_age": None,
}
SALARY = {"name": "Salary", "annual_amount": 100000, "growth_rate": 0, "tax_category": "employment",
          "growth_schedule": SCHEDULE}
BENEFIT = {"name": "Benefit", "annual_amount": 0, "growth_rate": 0, "tax_category": "social_security",
           "claiming_age": 67, "ss_benefit_basis": "pia", "pia_monthly": 1000, "ex_spouse": EX_SPOUSE}


async def _plan(client: AsyncClient) -> str:
    plan = await create_plan(client, name="Extensions", birth_year=1960, birth_month=1,
                             plan_type="FIXED_DATE", start_date="2026-01-01")
    return plan["id"]


def _amount(snapshots, year, name):
    row = next(s for s in snapshots if s["year"] == year)
    return sum(i["amount"] for i in row["cash_flow"]["income_sources"] if i["name"] == name)


async def test_round_trip_simulate_update_and_duplicate(client: AsyncClient):
    plan_id = await _plan(client)
    salary = await client.post(f"/api/plans/{plan_id}/incomes", json=SALARY)
    benefit = await client.post(f"/api/plans/{plan_id}/incomes", json=BENEFIT)
    assert salary.status_code == benefit.status_code == 201, (salary.text, benefit.text)
    assert salary.json()["growth_schedule"] == SCHEDULE
    assert benefit.json()["ex_spouse"] == EX_SPOUSE
    assert salary.json()["ex_spouse"] is None and benefit.json()["growth_schedule"] is None

    incomes = {i["name"]: i for i in (await client.get(f"/api/plans/{plan_id}")).json()["income_streams"]}
    assert incomes["Salary"]["growth_schedule"] == SCHEDULE
    assert incomes["Benefit"]["ex_spouse"] == EX_SPOUSE

    snapshots = (await client.post(f"/api/plans/{plan_id}/simulate")).json()["yearly_snapshots"]
    assert _amount(snapshots, 2027, "Salary") == pytest.approx(103000)
    assert _amount(snapshots, 2029, "Salary") == pytest.approx(120000)
    assert _amount(snapshots, 2028, "Benefit (divorced spouse)") == pytest.approx(6000)

    # An unrelated edit keeps both; an explicit null clears them.
    path = f"/api/plans/{plan_id}/incomes/{incomes['Salary']['id']}"
    renamed = await client.put(path, json={"name": "Pay"})
    assert renamed.status_code == 200 and renamed.json()["growth_schedule"] == SCHEDULE
    cleared = await client.put(path, json={"growth_schedule": None})
    assert cleared.status_code == 200 and cleared.json()["growth_schedule"] is None

    copied = await client.post(f"/api/plans/{plan_id}/duplicate")
    assert copied.status_code == 201, copied.text
    copies = {i["name"]: i for i in copied.json()["income_streams"]}
    assert copies["Benefit"]["ex_spouse"] == EX_SPOUSE
    assert copies["Benefit"]["id"] != incomes["Benefit"]["id"]


@pytest.mark.parametrize(("payload", "field"), [
    ({**SALARY, "growth_schedule": [SCHEDULE[1], SCHEDULE[0]]}, "growth_schedule"),
    ({**SALARY, "growth_schedule": [{**SCHEDULE[1], "dollars": None}]}, "growth_schedule"),
    ({**BENEFIT, "ex_spouse": {**EX_SPOUSE, "marriage_years": None}}, "ex_spouse"),
    ({**BENEFIT, "ss_benefit_basis": None, "pia_monthly": None}, "ex_spouse"),
    ({**BENEFIT, "ex_spouse": None, "growth_schedule": SCHEDULE}, "growth_schedule"),
])
async def test_invalid_inputs_are_rejected(client: AsyncClient, payload, field):
    plan_id = await _plan(client)
    response = await client.post(f"/api/plans/{plan_id}/incomes", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_update_validates_against_the_saved_row(client: AsyncClient):
    plan_id = await _plan(client)
    benefit = (await client.post(f"/api/plans/{plan_id}/incomes", json=BENEFIT)).json()
    path = f"/api/plans/{plan_id}/incomes/{benefit['id']}"
    # Switching away from PIA basis must also clear the former spouse's record.
    rejected = await client.put(path, json={"ss_benefit_basis": "amount", "pia_monthly": None})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"][0]["field"] == "ex_spouse"
    accepted = await client.put(path, json={"ss_benefit_basis": "amount", "ex_spouse": None})
    assert accepted.status_code == 200 and accepted.json()["ex_spouse"] is None
    salary = (await client.post(f"/api/plans/{plan_id}/incomes", json=SALARY)).json()
    switched = await client.put(f"/api/plans/{plan_id}/incomes/{salary['id']}",
                                json={"tax_category": "social_security"})
    assert switched.status_code == 422
    assert switched.json()["error"]["details"][0]["field"] == "growth_schedule"


async def test_stateless_matches_persisted(client: AsyncClient, db_session):
    plan_id = await _plan(client)
    for payload in (SALARY, BENEFIT):
        assert (await client.post(f"/api/plans/{plan_id}/incomes", json=payload)).status_code == 201
    persisted = await client.post(f"/api/plans/{plan_id}/simulate")
    assert persisted.status_code == 200
    db_session.expire_all()
    stored = db_session.get(Plan, UUID(plan_id))
    accounts = db_session.query(CurrentAccount).filter(
        CurrentAccount.user_id == stored.user_id,
        plan_account_filter(stored.id, stored.user_id, db_session),
    ).all()
    engine = plan_to_engine_data(stored, accounts)
    assert {i.name: (i.growth_schedule, i.ex_spouse) for i in engine.income_streams} == {
        "Salary": (SCHEDULE, None), "Benefit": (None, EX_SPOUSE),
    }
    stateless = await client.post("/api/simulate/stateless", json=asdict(engine))
    assert stateless.status_code == 200, stateless.text
    assert stateless.json() == persisted.json()
