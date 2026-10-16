"""PIA-basis Social Security fields persist, validate and drive projections."""

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from coastmath.schemas.plan_data_request import IncomeRequest
from tests.ss_household_support import PIA_INCOME, pia_plan

pytestmark = pytest.mark.anyio


async def test_pia_fields_round_trip_and_size_the_projection(client: AsyncClient):
    plan_id = await pia_plan(client)
    saved = await client.post(f"/api/plans/{plan_id}/incomes", json=PIA_INCOME)
    assert saved.status_code == 201
    body = saved.json()
    assert (body["ss_benefit_basis"], body["pia_monthly"], body["expected_benefit_percent"]) == ("pia", 2000, 90)

    income = (await client.get(f"/api/plans/{plan_id}")).json()["income_streams"][0]
    assert (income["ss_benefit_basis"], income["pia_monthly"], income["expected_benefit_percent"]) == ("pia", 2000, 90)

    snapshots = (await client.post(f"/api/plans/{plan_id}/simulate")).json()["yearly_snapshots"]
    row = next(s for s in snapshots if s["year"] == 2036)
    amount = sum(i["amount"] for i in row["cash_flow"]["income_sources"] if i["name"] == "Retirement benefit")
    assert amount == pytest.approx(2000 * 12 * 1.24 * 0.9)

    updated = await client.put(f"/api/plans/{plan_id}/incomes/{income['id']}", json={"claiming_age": 67})
    assert updated.status_code == 200
    snapshots = (await client.post(f"/api/plans/{plan_id}/simulate")).json()["yearly_snapshots"]
    row = next(s for s in snapshots if s["year"] == 2036)
    amount = sum(i["amount"] for i in row["cash_flow"]["income_sources"] if i["name"] == "Retirement benefit")
    assert amount == pytest.approx(2000 * 12 * 0.9)


async def test_legacy_income_reads_null_basis(client: AsyncClient):
    plan_id = await pia_plan(client)
    saved = await client.post(f"/api/plans/{plan_id}/incomes", json={
        "name": "SS", "annual_amount": 20000, "tax_category": "social_security", "claiming_age": 67,
    })
    assert saved.status_code == 201
    assert saved.json()["ss_benefit_basis"] is None
    assert saved.json()["pia_monthly"] is None


@pytest.mark.parametrize("change", [
    {"pia_monthly": None},
    {"pia_monthly": 0},
    {"claiming_age": None},
    {"tax_category": "qualified_pension"},
    {"expected_benefit_percent": 101},
    {"ss_benefit_basis": "estimate"},
])
async def test_invalid_pia_basis_is_rejected_on_create(client: AsyncClient, change):
    plan_id = await pia_plan(client)
    response = await client.post(f"/api/plans/{plan_id}/incomes", json={**PIA_INCOME, **change})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("change", [
    {"claiming_age": None},
    {"pia_monthly": 0},
    {"tax_category": "investment"},
])
async def test_invalid_pia_basis_is_rejected_on_partial_update(client: AsyncClient, change):
    plan_id = await pia_plan(client)
    income_id = (await client.post(f"/api/plans/{plan_id}/incomes", json=PIA_INCOME)).json()["id"]
    response = await client.put(f"/api/plans/{plan_id}/incomes/{income_id}", json=change)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    reloaded = (await client.get(f"/api/plans/{plan_id}")).json()["income_streams"][0]
    assert reloaded["pia_monthly"] == 2000 and reloaded["claiming_age"] == 70


async def test_switching_existing_amount_income_to_pia_requires_pia(client: AsyncClient):
    plan_id = await pia_plan(client)
    income_id = (await client.post(f"/api/plans/{plan_id}/incomes", json={
        "name": "SS", "annual_amount": 20000, "tax_category": "social_security", "claiming_age": 67,
    })).json()["id"]
    rejected = await client.put(f"/api/plans/{plan_id}/incomes/{income_id}", json={"ss_benefit_basis": "pia"})
    assert rejected.status_code == 422
    accepted = await client.put(f"/api/plans/{plan_id}/incomes/{income_id}",
                                json={"ss_benefit_basis": "pia", "pia_monthly": 1800})
    assert accepted.status_code == 200
    assert accepted.json()["ss_benefit_basis"] == "pia"


def test_stateless_request_validates_and_converts_pia_basis():
    request = IncomeRequest(id="a", **PIA_INCOME)
    assert request.pia_monthly == 2000
    with pytest.raises(ValidationError, match="positive monthly PIA"):
        IncomeRequest(id="a", **{**PIA_INCOME, "pia_monthly": None})
