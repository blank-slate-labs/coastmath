"""Local income tax selections: validation, persistence and residency resolution."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.schemas.plan import PlanCreate
from app.schemas.residency_period import ResidencyPeriodCreate, ResidencyPeriodRequest
from coastmath.engine.residency import (
    resolve_local_tax_for_year,
    resolve_state_for_year,
)
from coastmath.engine.types import MilestoneData, PlanData, ResidencyPeriodData
from coastmath.schemas.local_tax import LocalTaxSelection
from coastmath.schemas.plan_data_request import PlanDataRequest
from tests.api_support import create_plan

NYC = {"jurisdiction": "ny_new_york_city"}
CUSTOM = {"jurisdiction": "custom", "earned_income_rate": 0.01}


class TestSelectionSchema:
    def test_catalog_selection_is_compact(self):
        assert LocalTaxSelection.model_validate(NYC).model_dump() == NYC

    def test_custom_selection_keeps_only_given_rates(self):
        selection = LocalTaxSelection.model_validate(
            {"jurisdiction": "custom", "earned_income_rate": 0.01, "state_tax_surcharge_rate": 0.05})
        assert selection.model_dump() == {
            "jurisdiction": "custom", "earned_income_rate": 0.01, "state_tax_surcharge_rate": 0.05}

    @pytest.mark.parametrize("payload", [
        {"jurisdiction": "atlantis"},
        {"jurisdiction": "custom"},
        {"jurisdiction": "custom", "earned_income_rate": 0},
        {"jurisdiction": "custom", "earned_income_rate": 1.5},
        {"jurisdiction": "custom", "taxable_income_rate": 0.2},
        {"jurisdiction": "custom", "state_tax_surcharge_rate": 1.2},
        {"jurisdiction": "ny_new_york_city", "earned_income_rate": 0.01},
        {"jurisdiction": "ny_new_york_city", "unexpected": True},
    ])
    def test_rejects_invalid_selections(self, payload):
        with pytest.raises(ValidationError):
            LocalTaxSelection.model_validate(payload)

    def test_catalog_locality_must_match_state(self):
        with pytest.raises(ValidationError, match="is in NY"):
            PlanCreate(name="p", birth_year=1980, state_code="NJ", local_tax=NYC)
        with pytest.raises(ValidationError, match="is in NY"):
            PlanCreate(name="p", birth_year=1980, local_tax=NYC)
        assert PlanCreate(name="p", birth_year=1980, state_code="ny", local_tax=NYC).local_tax is not None
        # Custom rates carry no state.
        assert PlanCreate(name="p", birth_year=1980, state_code="OH", local_tax=CUSTOM).local_tax is not None

    @pytest.mark.parametrize("model", [ResidencyPeriodCreate, ResidencyPeriodRequest])
    def test_residency_period_locality_must_match_its_state(self, model):
        with pytest.raises(ValidationError, match="is in NY"):
            model(state_code="FL", start_year=2030, local_tax=NYC)
        assert model(state_code="NY", start_year=2030, local_tax=NYC).local_tax.jurisdiction == NYC["jurisdiction"]

    def test_stateless_request_checks_plan_level_state(self):
        base = {"plan_id": str(uuid.uuid4()), "birth_year": 1980, "start_year": 2026}
        with pytest.raises(ValidationError, match="is in NY"):
            PlanDataRequest.model_validate({**base, "state_code": "CA", "local_tax": NYC})
        request = PlanDataRequest.model_validate({**base, "state_code": "NY", "local_tax": NYC})
        assert request.local_tax.jurisdiction == NYC["jurisdiction"]


def _plan(**overrides) -> PlanData:
    values = dict(plan_id="p", birth_year=1980, filing_status="single", life_expectancy=90,
                  start_year=2026, state_code="NY", local_tax=NYC)
    values.update(overrides)
    return PlanData(**values)


class TestResidencyResolution:
    def test_plan_default_applies_without_periods(self):
        assert resolve_local_tax_for_year(2030, set(), _plan()) == NYC

    def test_period_locality_governs_its_years(self):
        plan = _plan(residency_periods=[
            ResidencyPeriodData(state_code="FL", start_year=2035, rank=0),
            ResidencyPeriodData(state_code="NY", start_year=2031, end_year=2034, rank=1, local_tax=CUSTOM),
        ])
        assert resolve_local_tax_for_year(2030, set(), plan) == NYC
        assert resolve_local_tax_for_year(2032, set(), plan) == CUSTOM
        assert resolve_state_for_year(2040, set(), plan) == "FL"
        # The plan-level locality describes the plan-level state only.
        assert resolve_local_tax_for_year(2040, set(), plan) is None

    def test_milestone_move_ends_the_locality(self):
        plan = _plan(
            milestones=[MilestoneData(id="move", name="Move", trigger_type="date", trigger_date="2031-06-01")],
            residency_periods=[ResidencyPeriodData(state_code="FL", start_milestone_id="move")],
        )
        assert resolve_local_tax_for_year(2031, set(), plan) == NYC
        assert resolve_local_tax_for_year(2031, {"move"}, plan) is None


class TestPlanApi:
    @pytest.mark.anyio
    async def test_create_read_and_update_plan_locality(self, client: AsyncClient):
        plan = await create_plan(client, birth_year=1985, state_code="NY", local_tax=NYC)
        assert plan["local_tax"] == NYC
        url = f"/api/plans/{plan['id']}"
        assert (await client.get(url)).json()["local_tax"] == NYC

        # Unrelated updates leave the locality alone.
        assert (await client.put(url, json={"name": "Renamed"})).json()["local_tax"] == NYC
        # A locality from another state is rejected with the error envelope.
        rejected = await client.put(url, json={"local_tax": {"jurisdiction": "ny_yonkers"}, "state_code": "NJ"})
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
        assert (await client.get(url)).json()["state_code"] == "NY"
        # Changing the state clears a locality that belongs to the old state.
        moved = await client.put(url, json={"state_code": "NJ"})
        assert moved.status_code == 200 and moved.json()["local_tax"] is None
        # Custom rates survive a state change.
        custom = await client.put(url, json={"local_tax": CUSTOM})
        assert custom.json()["local_tax"] == CUSTOM
        assert (await client.put(url, json={"state_code": "OH"})).json()["local_tax"] == CUSTOM
        cleared = await client.put(url, json={"local_tax": None})
        assert cleared.json()["local_tax"] is None

    @pytest.mark.anyio
    async def test_residency_period_locality_round_trips(self, client: AsyncClient):
        plan = await create_plan(client, birth_year=1985, state_code="FL")
        url = f"/api/plans/{plan['id']}"
        saved = await client.put(url, json={"residency_periods": [
            {"state_code": "NY", "start_year": 2026, "end_year": 2030, "local_tax": NYC},
            {"state_code": "FL", "start_year": 2031, "rank": 1},
        ]})
        assert saved.status_code == 200, saved.text
        periods = sorted((await client.get(url)).json()["residency_periods"], key=lambda p: p["rank"])
        assert [p["local_tax"] for p in periods] == [NYC, None]
        rejected = await client.put(url, json={"residency_periods": [
            {"state_code": "FL", "start_year": 2026, "local_tax": NYC}]})
        assert rejected.status_code == 422

    @pytest.mark.anyio
    async def test_duplicate_copies_localities(self, client: AsyncClient):
        plan = await create_plan(client, birth_year=1985, state_code="NY", local_tax=NYC)
        await client.put(f"/api/plans/{plan['id']}", json={"residency_periods": [
            {"state_code": "NY", "start_year": 2030, "local_tax": {"jurisdiction": "ny_yonkers"}}]})
        copy = await client.post(f"/api/plans/{plan['id']}/duplicate")
        assert copy.status_code == 201, copy.text
        assert copy.json()["local_tax"] == NYC
        assert copy.json()["residency_periods"][0]["local_tax"] == {"jurisdiction": "ny_yonkers"}

    @pytest.mark.anyio
    async def test_catalog_lists_jurisdictions_by_state(self, client: AsyncClient):
        catalog = (await client.get("/api/local-tax-jurisdictions", params={"state_code": "ny"})).json()
        assert catalog["tax_year"] == 2026
        ids = [entry["id"] for entry in catalog["jurisdictions"]]
        assert {"ny_new_york_city", "ny_yonkers"} <= set(ids)
        assert {entry["state_code"] for entry in catalog["jurisdictions"]} == {"NY"}
        everything = (await client.get("/api/local-tax-jurisdictions")).json()["jurisdictions"]
        assert len(everything) > len(ids)


class TestSimulationApi:
    @pytest.mark.anyio
    async def test_persisted_plan_residency_locality_reaches_the_engine(self, client: AsyncClient):
        plan = await create_plan(client, birth_year=1985, state_code="FL", plan_type="FIXED_DATE",
                                 start_date="2026-01-01", life_expectancy=50)
        url = f"/api/plans/{plan['id']}"
        income = await client.post(f"{url}/incomes", json={"name": "Salary", "annual_amount": 120000, "growth_rate": 0})
        assert income.status_code == 201, income.text
        await client.put(url, json={"residency_periods": [
            {"state_code": "NY", "start_year": 2026, "end_year": 2027, "local_tax": NYC}]})
        response = await client.post(f"{url}/simulate")
        assert response.status_code == 200, response.text
        by_year = {row["year"]: row for row in response.json()["yearly_snapshots"]}
        assert by_year[2026]["local_tax"] > 3000 and by_year[2027]["local_tax"] > 3000
        assert by_year[2028]["local_tax"] == 0 and by_year[2028]["state_tax"] == 0

    @pytest.mark.anyio
    async def test_stateless_request_carries_plan_and_period_localities(self, client: AsyncClient):
        body = {
            "plan_id": str(uuid.uuid4()), "birth_year": 1985, "start_year": 2026, "life_expectancy": 50,
            "income_streams": [{"id": "pay", "name": "Salary", "annual_amount": 100000, "growth_rate": 0}],
            "state_code": "PA", "local_tax": {"jurisdiction": "pa_philadelphia"},
            "residency_periods": [{"state_code": "OH", "start_year": 2028, "local_tax": CUSTOM}],
            "assumptions": {"inflation_rate": 0, "stock_growth_rate": 0, "bond_return_rate": 0},
        }
        response = await client.post("/api/simulate/stateless", json=body)
        assert response.status_code == 200, response.text
        by_year = {row["year"]: row for row in response.json()["yearly_snapshots"]}
        assert by_year[2026]["local_tax"] == pytest.approx(100000 * 0.037375)
        assert by_year[2028]["local_tax"] == pytest.approx(1000)
