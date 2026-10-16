"""Pytest tests for the core plan API endpoints."""

import uuid
from dataclasses import asdict
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.engine.plan_converter import plan_to_engine_data
from app.models.account import CurrentAccount
from app.models.plan import Plan
from app.routers.helpers import plan_account_filter
from app.seed import seed_demo_plan
from coastmath.engine.sepp import calculate_sepp, get_sepp_end_age
from tests.api_support import assert_error_shape, create_plan, new_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_account(client: AsyncClient, **overrides) -> dict:
    defaults = {
        "name": "Checking",
        "account_type": "checking",
        "balance": 10000,
    }
    defaults.update(overrides)
    r = await client.post("/api/accounts", json=defaults)
    assert r.status_code == 201
    return r.json()


async def _create_milestone(client: AsyncClient, plan_id: str, **overrides) -> dict:
    defaults = {
        "name": "Retirement",
        "trigger_type": "age",
        "trigger_value": 65,
        "sort_order": 0,
    }
    defaults.update(overrides)
    r = await client.post(f"/api/plans/{plan_id}/milestones", json=defaults)
    assert r.status_code == 201
    return r.json()


async def _create_income(client: AsyncClient, plan_id: str, **overrides) -> dict:
    defaults = {"name": "Salary", "annual_amount": 100000}
    defaults.update(overrides)
    r = await client.post(f"/api/plans/{plan_id}/incomes", json=defaults)
    assert r.status_code == 201
    return r.json()


async def _create_expense(client: AsyncClient, plan_id: str, **overrides) -> dict:
    defaults = {"name": "Rent", "annual_amount": 24000}
    defaults.update(overrides)
    r = await client.post(f"/api/plans/{plan_id}/expenses", json=defaults)
    assert r.status_code == 201
    return r.json()


# ===========================================================================
# Auth
# ===========================================================================


class TestAuth:
    @pytest.mark.anyio
    async def test_get_me(self, client: AsyncClient, test_user):
        r = await client.get("/api/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == str(test_user.id)
        assert data["email"] == "test@localhost"
        assert "display_name" in data

    @pytest.mark.anyio
    async def test_logout(self, client: AsyncClient):
        r = await client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


# ===========================================================================
# Plans CRUD
# ===========================================================================


class TestPlansCRUD:
    @pytest.mark.anyio
    async def test_create_now_plan(self, client: AsyncClient, test_user):
        data = await create_plan(client, name="NOW Plan", plan_type="NOW")
        assert data["name"] == "NOW Plan"
        assert data["plan_type"] == "NOW"
        assert data["user_id"] == str(test_user.id)
        assert data["birth_year"] == 1990
        assert "id" in data
        assert "created_at" in data
        assert data["spouse"] is None

    @pytest.mark.anyio
    async def test_create_plan_with_spouse_round_trip_and_joint_filing_simulation(self, client: AsyncClient):
        r = await client.post(
            "/api/plans",
            json={
                "name": "Couple",
                "birth_year": 1990,
                "filing_status": "married_filing_jointly",
                "spouse": {
                    "name": "Partner",
                    "birth_year": 1991,
                    "birth_month": 4,
                    "life_expectancy": 95,
                },
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["spouse"]["name"] == "Partner"
        assert data["spouse"]["birth_year"] == 1991
        assert data["spouse"]["birth_month"] == 4
        assert data["spouse"]["life_expectancy"] == 95

        simulation = await client.post(f"/api/plans/{data['id']}/simulate")
        assert simulation.status_code == 200, simulation.text
        warnings = simulation.json()["metadata"]["warnings"]
        assert not any(
            warning.startswith("Household mismatch: joint filing requires a partner profile")
            for warning in warnings
        )

    @pytest.mark.anyio
    async def test_create_plan_seeds_retirement_milestone_only_when_requested(self, client: AsyncClient):
        seeded = await client.post("/api/plans", json={"name": "Seeded", "birth_year": 1990, "retirement_milestone_age": 65})
        assert seeded.status_code == 201, seeded.text
        milestones = (await client.get(f"/api/plans/{seeded.json()['id']}/milestones")).json()
        assert [(m["name"], m["trigger_type"], float(m["trigger_value"])) for m in milestones] == [("Retirement", "age", 65.0)]

        plain = await create_plan(client, name="Plain")
        assert (await client.get(f"/api/plans/{plain['id']}/milestones")).json() == []

        # Already past the age at plan start: nothing to seed.
        past = await client.post("/api/plans", json={"name": "Retired", "birth_year": 1940, "retirement_milestone_age": 65})
        assert past.status_code == 201, past.text
        assert (await client.get(f"/api/plans/{past.json()['id']}/milestones")).json() == []

    @pytest.mark.anyio
    async def test_create_plan_rejects_invalid_spouse_without_creating_plan(self, client: AsyncClient):
        before = await client.get("/api/plans")
        assert before.status_code == 200
        before_ids = {plan["id"] for plan in before.json()}

        r = await client.post(
            "/api/plans",
            json={
                "name": "Invalid Partner",
                "birth_year": 1990,
                "spouse": {"life_expectancy": 30},
            },
        )
        assert r.status_code == 422
        assert_error_shape(r.json())

        after = await client.get("/api/plans")
        assert after.status_code == 200
        assert {plan["id"] for plan in after.json()} == before_ids

    @pytest.mark.anyio
    async def test_create_fixed_date_plan(self, client: AsyncClient):
        data = await create_plan(
            client,
            name="Fixed Plan",
            plan_type="FIXED_DATE",
            start_date="2030-01-01",
            snapshot_conditions={"acct1": {"balance": 5000, "account_type": "checking"}},
        )
        assert data["plan_type"] == "FIXED_DATE"
        assert data["start_date"] == "2030-01-01"
        assert data["snapshot_conditions"] == {
            "acct1": {"balance": 5000, "account_type": "checking"}
        }

    @pytest.mark.anyio
    async def test_list_plans(self, client: AsyncClient):
        await create_plan(client, name="Plan A")
        await create_plan(client, name="Plan B")
        r = await client.get("/api/plans")
        assert r.status_code == 200
        plans = r.json()
        assert len(plans) >= 2
        names = {p["name"] for p in plans}
        assert "Plan A" in names
        assert "Plan B" in names

    @pytest.mark.anyio
    async def test_get_plan_with_relationships(self, client: AsyncClient):
        plan = await create_plan(client)
        plan_id = plan["id"]
        # Add sub-resources
        await _create_milestone(client, plan_id)
        await _create_income(client, plan_id)
        await _create_expense(client, plan_id)

        r = await client.get(f"/api/plans/{plan_id}")
        assert r.status_code == 200
        data = r.json()
        assert len(data["milestones"]) == 1
        assert len(data["income_streams"]) == 1
        assert len(data["expenses"]) == 1
        assert "priorities" in data
        assert "drawdown_order" in data

    @pytest.mark.anyio
    async def test_update_plan(self, client: AsyncClient):
        plan = await create_plan(client, name="Original")
        r = await client.put(
            f"/api/plans/{plan['id']}",
            json={"name": "Updated", "life_expectancy": 100},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Updated"
        assert data["life_expectancy"] == 100
        # A blank name would leave the plan unnamed in every list.
        for blank in ("", "   "):
            r = await client.put(f"/api/plans/{plan['id']}", json={"name": blank})
            assert r.status_code == 422
            assert_error_shape(r.json())
        assert (await client.get(f"/api/plans/{plan['id']}")).json()["name"] == "Updated"
        # A state is a US postal code or nothing: a form placeholder is refused.
        for bad in ("__choose", "ZZ"):
            r = await client.put(f"/api/plans/{plan['id']}", json={"state_code": bad})
            assert r.status_code == 422
        r = await client.post("/api/plans", json={"name": "P", "birth_year": 1985, "state_code": "__choose"})
        assert r.status_code == 422
        assert (await client.put(f"/api/plans/{plan['id']}", json={"state_code": "ny"})).json()["state_code"] == "NY"
        assert (await client.put(f"/api/plans/{plan['id']}", json={"state_code": ""})).json()["state_code"] is None

    @pytest.mark.anyio
    async def test_balances_stop_at_one_trillion(self, client: AsyncClient):
        """A balance, like a yearly amount, stops at $1 trillion: past it is a typo."""
        r = await client.post("/api/accounts", json={"name": "Typo", "account_type": "checking", "balance": 99999999999999999})
        assert r.status_code == 422
        account = await _create_account(client, balance=1e12)
        r = await client.put(f"/api/accounts/{account['id']}", json={"balance": 1e12 + 1})
        assert r.status_code == 422

    @pytest.mark.anyio
    async def test_partner_removal_keeps_partner_items_runnable(self, client: AsyncClient, db_session, test_user):
        """Removing a partner who still owns incomes or accounts is refused with
        their names; a plan already saved that way answers 422 naming the
        partner's Social Security, which needs the partner's birth year, instead
        of failing the projection."""
        seed_demo_plan(test_user.id, db_session)
        db_session.commit()
        plan = db_session.query(Plan).filter_by(user_id=test_user.id).one()
        partner_items = "Partner salary, Social Security (Partner), Roth IRA (partner)"

        r = await client.put(f"/api/plans/{plan.id}", json={"spouse": None})
        assert r.status_code == 422
        assert_error_shape(r.json())
        assert partner_items in r.json()["error"]["message"]
        assert (await client.get(f"/api/plans/{plan.id}")).json()["spouse"] is not None

        plan.spouse = None
        db_session.commit()
        r = await client.post(f"/api/plans/{plan.id}/simulate")
        assert r.status_code == 422
        assert "Social Security (Partner) is the partner's" in r.json()["error"]["message"]

    @pytest.mark.anyio
    async def test_update_plan_estate_settings_and_spouse_round_trip(self, client: AsyncClient):
        """Estate assumptions and the partner profile persist through PUT and
        drive the engine-reported estate breakdown."""
        plan = await create_plan(
            client, name="Estate Plan", birth_year=1960, life_expectancy=80,
            filing_status="married_filing_jointly",
        )
        pid = plan["id"]
        await _create_account(client, name="Brokerage", account_type="taxable_brokerage", balance=25_000_000)
        estate = {
            "step_up_basis_on_death": False,
            "filing_status_after_death": "head_of_household",
            "federal_estate_exemption": 7_000_000,
            "custom_federal_exemption_enabled": True,
            "portability_election": False,
            "state_estate_tax_enabled": True,
            "state_estate_exemption": 2_000_000,
            "state_estate_tax_rate": 0.16,
            "settlement_cost_fixed": 15_000,
            "settlement_cost_rate": 0.02,
            "heir_income_tax_rate": 0.22,
        }
        r = await client.put(
            f"/api/plans/{pid}",
            json={"estate_settings": estate, "spouse": {"name": "Partner", "birth_year": 1962, "life_expectancy": 70}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["estate_settings"] == estate
        assert body["spouse"]["birth_year"] == 1962
        assert body["spouse"]["life_expectancy"] == 70

        r = await client.get(f"/api/plans/{pid}")
        assert r.json()["estate_settings"] == estate
        assert r.json()["spouse"]["name"] == "Partner"

        # Partner dies 2032, holder dies 2040 → no marital deduction, custom
        # exemption applied, state and federal reported separately.
        r = await client.post(f"/api/plans/{pid}/simulate")
        assert r.status_code == 200
        legacy = r.json()["metadata"]["net_legacy"]
        assert legacy["marital_deduction_applied"] is False
        assert legacy["custom_federal_exemption"] is True
        assert legacy["federal_exemption"] == 7_000_000
        assert legacy["dsue_amount"] == 0
        assert legacy["federal_estate_tax"] > 0
        assert legacy["state_estate_tax"] > 0
        assert legacy["estate_tax"] == pytest.approx(
            legacy["federal_estate_tax"] + legacy["state_estate_tax"]
        )
        assert legacy["settlement_costs"] == pytest.approx(15_000 + 0.02 * legacy["gross_estate"])
        assert legacy["net_legacy"] == pytest.approx(legacy["gross_estate"] - legacy["settlement_costs"] - legacy["estate_tax"])
        assert legacy["heir_income_tax"] == 0  # brokerage only, no pre-tax balances
        assert legacy["net_to_heirs_after_income_tax"] == pytest.approx(legacy["net_legacy"])
        assert legacy["exclusions"]

        # Partner outlives the holder → marital deduction defers all estate tax.
        r = await client.put(f"/api/plans/{pid}", json={"spouse": {"life_expectancy": 95}})
        assert r.status_code == 200
        assert r.json()["spouse"]["birth_year"] == 1962  # partial update keeps other fields
        legacy = (await client.post(f"/api/plans/{pid}/simulate")).json()["metadata"]["net_legacy"]
        assert legacy["marital_deduction_applied"] is True
        assert legacy["estate_tax"] == 0

        # Explicit null removes the partner; omitted key leaves it alone.
        r = await client.put(f"/api/plans/{pid}", json={"name": "Renamed"})
        assert r.json()["spouse"]["name"] == "Partner"
        r = await client.put(f"/api/plans/{pid}", json={"spouse": None})
        assert r.status_code == 200
        assert r.json()["spouse"] is None

        # Validation: rates are decimals, filing status is constrained.
        r = await client.put(f"/api/plans/{pid}", json={"estate_settings": {**estate, "state_estate_tax_rate": 16}})
        assert r.status_code == 422
        assert_error_shape(r.json())
        r = await client.put(f"/api/plans/{pid}", json={"estate_settings": {**estate, "filing_status_after_death": "widow"}})
        assert r.status_code == 422

    @pytest.mark.anyio
    async def test_income_advanced_fields_round_trip_and_partial_update(self, client: AsyncClient):
        """Growth cap, withholding, owner and employment flags persist and a
        partial update leaves untouched fields alone."""
        plan = await create_plan(client, name="Income Plan", birth_year=1980)
        pid = plan["id"]
        body = {
            "name": "Consulting", "annual_amount": 120_000, "growth_rate": 4.5,
            "growth_cap": 200_000, "growth_cap_inflation_linked": True,
            "withholding_percent": 22.5, "owner": "spouse",
            "is_earned_income": True, "is_self_employed": True, "start_month": 3,
        }
        r = await client.post(f"/api/plans/{pid}/incomes", json=body)
        assert r.status_code == 201, r.text
        income = r.json()
        for key, value in body.items():
            assert income[key] == value, key
        iid = income["id"]

        r = await client.put(f"/api/plans/{pid}/incomes/{iid}", json={"annual_amount": 130_000})
        assert r.status_code == 200
        updated = r.json()
        assert updated["annual_amount"] == 130_000
        for key in ("growth_cap", "growth_cap_inflation_linked", "withholding_percent", "owner", "is_self_employed", "start_month"):
            assert updated[key] == body[key], key

        r = await client.put(f"/api/plans/{pid}/incomes/{iid}", json={"growth_cap": None, "withholding_percent": None})
        assert r.status_code == 200
        assert r.json()["growth_cap"] is None and r.json()["withholding_percent"] is None

        # Percent units: 0.225 would be a decimal fraction, 225 is out of range.
        r = await client.put(f"/api/plans/{pid}/incomes/{iid}", json={"withholding_percent": 225})
        assert r.status_code == 422
        assert_error_shape(r.json())
        r = await client.put(f"/api/plans/{pid}/incomes/{iid}", json={"growth_cap": -1})
        assert r.status_code == 422
        r = await client.put(f"/api/plans/{pid}/incomes/{iid}", json={"owner": "child"})
        assert r.status_code == 422

    @pytest.mark.anyio
    async def test_milestone_relative_and_expense_multiple_rules(self, client: AsyncClient):
        """Relative milestones must reference a plan milestone without cycles;
        financial-independence milestones need a positive multiple; the
        simulation reports when each milestone fired."""
        plan = await create_plan(client, name="Milestones", birth_year=1990)
        pid = plan["id"]
        await _create_account(client, name="Cash", account_type="checking", balance=1_000_000)
        r = await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living", "annual_amount": 30_000})
        assert r.status_code == 201
        fi = await _create_milestone(client, pid, name="FI", trigger_type="expense_multiple",
                                     trigger_value=None, expense_multiple=25, metric="liquid_net_worth")
        retire = await _create_milestone(client, pid, name="Retire", trigger_type="relative",
                                         trigger_value=None, relative_to_id=fi["id"], offset_years=2)
        assert retire["relative_to_id"] == fi["id"] and retire["offset_years"] == 2

        # Cycle: FI -> Retire -> FI
        r = await client.put(f"/api/plans/{pid}/milestones/{fi['id']}",
                             json={"trigger_type": "relative", "relative_to_id": retire["id"]})
        assert r.status_code == 422
        assert_error_shape(r.json())
        assert r.json()["error"]["details"][0]["field"] == "relative_to_id"
        # Self-reference and cross-plan references are rejected too.
        r = await client.put(f"/api/plans/{pid}/milestones/{retire['id']}", json={"relative_to_id": retire["id"]})
        assert r.status_code == 422
        other = await create_plan(client, name="Other")
        foreign = await _create_milestone(client, other["id"], name="Foreign")
        r = await client.put(f"/api/plans/{pid}/milestones/{retire['id']}", json={"relative_to_id": foreign["id"]})
        assert r.status_code == 422
        # Required fields per trigger type.
        r = await client.post(f"/api/plans/{pid}/milestones", json={"name": "Bad", "trigger_type": "relative"})
        assert r.status_code == 422
        r = await client.post(f"/api/plans/{pid}/milestones", json={"name": "Bad", "trigger_type": "expense_multiple"})
        assert r.status_code == 422
        r = await client.post(f"/api/plans/{pid}/milestones", json={"name": "Bad", "trigger_type": "age"})
        assert r.status_code == 422

        sim = await client.post(f"/api/plans/{pid}/simulate")
        assert sim.status_code == 200
        outcomes = {o["name"]: o for o in sim.json()["metadata"]["milestone_outcomes"]}
        assert outcomes["FI"]["trigger_type"] == "expense_multiple"
        assert outcomes["FI"]["year"] is not None  # $1M liquid > 25 x $30k
        assert outcomes["Retire"]["year"] == outcomes["FI"]["year"] + 2

    @pytest.mark.anyio
    async def test_plan_notes_round_trip(self, client: AsyncClient):
        """Plain-text notes persist through create, update and reload and are
        bounded in length."""
        plan = await create_plan(client, name="Noted", notes="Assumes 3% inflation.\nReview in 2027.")
        pid = plan["id"]
        assert plan["notes"] == "Assumes 3% inflation.\nReview in 2027."
        r = await client.put(f"/api/plans/{pid}", json={"name": "Renamed"})
        assert r.json()["notes"] == "Assumes 3% inflation.\nReview in 2027."  # untouched by other updates
        r = await client.put(f"/api/plans/{pid}", json={"notes": "<b>kept as text</b>"})
        assert r.status_code == 200 and r.json()["notes"] == "<b>kept as text</b>"
        r = await client.get(f"/api/plans/{pid}")
        assert r.json()["notes"] == "<b>kept as text</b>"
        r = await client.put(f"/api/plans/{pid}", json={"notes": None})
        assert r.json()["notes"] is None
        r = await client.put(f"/api/plans/{pid}", json={"notes": "x" * 20_001})
        assert r.status_code == 422
        assert_error_shape(r.json())

    @pytest.mark.anyio
    async def test_sepp_preview_matches_engine_and_settings_validate_source(self, client: AsyncClient):
        """The preview uses the engine's SEPP functions; saving settings
        requires an eligible pre-tax account."""
        r = await client.post("/api/plans/sepp-preview", json={"balance": 500_000, "start_age": 50, "interest_rate": 0.05, "birth_year": 1980})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["single_life_divisor"] == 36.2
        assert body["end_age"] == get_sepp_end_age(50)
        assert body["payment_years"] == 10  # ages50-58 full; age59 half
        by_method = {m["method"]: m for m in body["methods"]}
        assert set(by_method) == {"rmd_method", "fixed_amortization"}  # annuitization withheld
        for name in ("rmd_method", "fixed_amortization"):
            assert by_method[name]["first_year_amount"] == pytest.approx(calculate_sepp(500_000, 50, name, 0.05))
            assert by_method[name]["schedule"][0]["year"] == 2030
        # IRS Notice 2022-6 example: $400k, age 50, 5% -> RMD $11,050, amortization $24,125
        ex = await client.post("/api/plans/sepp-preview", json={"balance": 400_000, "start_age": 50, "interest_rate": 0.05})
        ex_methods = {m["method"]: m["first_year_amount"] for m in ex.json()["methods"]}
        assert ex_methods["rmd_method"] == pytest.approx(11_050, abs=1)
        assert ex_methods["fixed_amortization"] == pytest.approx(24_125, abs=1)
        amort = by_method["fixed_amortization"]["schedule"]
        assert amort[0]["withdrawal"] == pytest.approx(amort[3]["withdrawal"])  # fixed
        assert body["notes"]
        assert body["rate_ceiling"] == pytest.approx(0.05)  # January 2030: no bundled rates
        # A November 2026 start allows up to 120% of October 2026's mid-term rate.
        approved = calculate_sepp(500_000, 50, "fixed_amortization", 0.055)
        above = await client.post("/api/plans/sepp-preview", json={
            "balance": 500_000, "start_age": 50, "interest_rate": 0.055, "birth_year": 1976, "birth_month": 11,
            "annual_amount": round(approved)})
        assert above.json()["rate_ceiling"] == pytest.approx(0.0554)
        assert above.json()["custom"]["qualifies"] is True
        too_high = await client.post("/api/plans/sepp-preview", json={
            "balance": 500_000, "start_age": 50, "interest_rate": 0.06, "birth_year": 1976, "birth_month": 11,
            "annual_amount": 30_000})
        assert too_high.json()["custom"]["qualifies"] is False
        assert "5.54%" in too_high.json()["custom"]["message"]
        r = await client.post("/api/plans/sepp-preview", json={"balance": 500_000, "start_age": 60})
        assert r.status_code == 422

        plan = await create_plan(client, name="SEPP", birth_year=1980)
        pid = plan["id"]
        roth = await _create_account(client, name="Roth", account_type="roth_ira", balance=100_000)
        ira = await _create_account(client, name="IRA", account_type="traditional_ira", balance=400_000)
        settings = {"enabled": True, "source_account_id": roth["id"], "method": "fixed_amortization", "start_age": 52, "interest_rate": 0.05}
        r = await client.put(f"/api/plans/{pid}", json={"sepp_settings": settings})
        assert r.status_code == 422
        assert r.json()["error"]["details"][0]["field"] == "sepp_settings.source_account_id"
        r = await client.put(f"/api/plans/{pid}", json={"sepp_settings": {**settings, "source_account_id": ira["id"]}})
        assert r.status_code == 200
        assert r.json()["sepp_settings"]["source_account_id"] == ira["id"]
        r = await client.put(f"/api/plans/{pid}", json={"sepp_settings": {**settings, "source_account_id": ira["id"], "start_age": 59.5}})
        assert r.status_code == 422
        r = await client.put(f"/api/plans/{pid}", json={"sepp_settings": {**settings, "source_account_id": ira["id"], "method": "fixed_annuitization"}})
        assert r.status_code == 422

    @pytest.mark.anyio
    async def test_healthcare_settings_round_trip(self, client: AsyncClient, db_session):
        """Health coverage settings persist and drive per-year premiums and
        credits in the simulation."""
        plan = await create_plan(client, name="Health", birth_year=1966, filing_status="married_filing_jointly", life_expectancy=70)
        pid = plan["id"]
        await _create_account(client, name="Cash", account_type="checking", balance=2_000_000)
        r = await client.post(f"/api/plans/{pid}/incomes", json={"name": "Pension", "annual_amount": 60_000, "is_earned_income": False})
        assert r.status_code == 201
        ms = await _create_milestone(client, pid, name="Retire", trigger_type="age", trigger_value=60)
        settings = {
            "enabled": True, "medical_inflation_rate": 0.04, "aca_enabled": True,
            "aca_start_milestone_id": ms["id"], "aca_end_milestone_id": None,
            "aca_benchmark_premium_annual": 24_000, "aca_plan_premium_annual": 22_000,
            "aca_advance_credit_fraction": 0.5,
            "aca_cover_spouse": True, "aca_dependents": 1, "aca_apply_age_curve": True, "aca_state_group": "contiguous",
            "medicare_enabled": True, "medicare_part_b": True, "medicare_part_d": True,
            "medicare_part_d_plan_premium_monthly": 35, "medicare_supplement_premium_monthly": 180,
            "medicare_apply_irmaa": True, "magi_prior_year": 90_000, "magi_two_years_prior": 95_000,
        }
        r = await client.put(f"/api/plans/{pid}", json={"healthcare_settings": settings})
        assert r.status_code == 200, r.text
        expected = {**settings, "persons": [], "magi_prior_year_filing_status": None, "magi_two_years_prior_filing_status": None}
        assert r.json()["healthcare_settings"] == expected
        r = await client.get(f"/api/plans/{pid}")
        assert r.json()["healthcare_settings"] == expected
        sim = await client.post(f"/api/plans/{pid}/simulate")
        assert sim.status_code == 200
        first = sim.json()["yearly_snapshots"][0]["healthcare"]
        assert first["aca_covered_adults"] == 1 and first["aca_household_size"] == 1 + 1  # self + one dependent, no partner record
        assert first["aca_gross_premium"] > 0 and first["total"] == pytest.approx(first["aca_net_premium"])
        assert first["aca_cash_premium"] >= first["aca_net_premium"]
        # Persisted and stateless simulations must consume the same JSONB
        # setting, including the new fraction and cash/final premium split.
        db_session.expire_all()
        stored_plan = db_session.get(Plan, UUID(pid))
        accounts = db_session.query(CurrentAccount).filter(
            CurrentAccount.user_id == stored_plan.user_id,
            plan_account_filter(stored_plan.id, stored_plan.user_id, db_session),
        ).all()
        engine = plan_to_engine_data(stored_plan, accounts)
        stateless = await client.post("/api/simulate/stateless", json=asdict(engine))
        assert stateless.status_code == 200, stateless.text
        assert stateless.json() == sim.json()
        # Validation: ACA needs premiums; rates are decimals.
        r = await client.put(f"/api/plans/{pid}", json={"healthcare_settings": {**settings, "aca_plan_premium_annual": 0}})
        assert r.status_code == 422
        assert_error_shape(r.json())
        r = await client.put(f"/api/plans/{pid}", json={"healthcare_settings": {**settings, "medical_inflation_rate": 4}})
        assert r.status_code == 422

    @pytest.mark.anyio
    async def test_tax_strategy_comparison_runs_candidates_and_validates_accounts(self, client: AsyncClient):
        """Bounded bracket-fill strategies are simulated in full and compared
        against the baseline."""
        plan = await create_plan(client, name="Optimizer", birth_year=1966, life_expectancy=90, filing_status="single")
        pid = plan["id"]
        ira = await _create_account(client, name="IRA", account_type="traditional_ira", balance=1_500_000)
        roth = await _create_account(client, name="Roth", account_type="roth_ira", balance=50_000)
        cash = await _create_account(client, name="Cash", account_type="checking", balance=800_000)
        r = await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living", "annual_amount": 60_000})
        assert r.status_code == 201
        r = await client.put(f"/api/plans/{pid}/drawdown-order", json={"items": [{"rank": 1, "source_account_id": cash["id"]}, {"rank": 2, "source_account_id": ira["id"]}]})
        assert r.status_code in (200, 201), r.text
        retire = await _create_milestone(client, pid, name="Retire", trigger_type="age", trigger_value=61)
        body = {"source_account_id": ira["id"], "target_account_id": roth["id"], "bracket_ceilings": [0.12, 0.22, 0.24, 0.99],
                "start_milestone_id": retire["id"], "objective": "net_legacy"}
        r = await client.post(f"/api/plans/{pid}/tax-strategies/compare", json=body)
        assert r.status_code == 200, r.text
        out = r.json()
        keys = [c["key"] for c in out["candidates"]]
        assert keys == ["baseline", "fill_1200", "fill_2200", "fill_2400"]  # 0.99 is not a bracket
        baseline = out["candidates"][0]
        assert baseline["total_converted"] == 0 and baseline["delta_vs_baseline"] == 0
        fills = out["candidates"][1:]
        assert all(c["total_converted"] > 0 and c["conversion_years"] > 0 for c in fills)
        assert fills[0]["total_converted"] < fills[1]["total_converted"]  # 12% bracket has far less headroom than 22%
        assert sum(1 for c in out["candidates"] if c["is_best"]) == 1
        assert out["best_key"] in keys and out["caveats"]
        assert out["proposed_priority"] is None or out["proposed_priority"]["conversion_mode"] == "fill_bracket"
        # Net legacy ranks with pre-tax balances after income tax (no heir rate set: 24%).
        assert out["pre_tax_discount_rate"] == 0.24
        plain = (await client.post(f"/api/plans/{pid}/simulate")).json()["metadata"]["net_legacy"]
        assert baseline["net_legacy"] == pytest.approx(plain["net_legacy"])
        assert baseline["objective_value"] == pytest.approx(plain["net_legacy"] - 0.24 * plain["pretax_balance"])
        # Lifetime-tax objective picks the lowest tax candidate.
        r = await client.post(f"/api/plans/{pid}/tax-strategies/compare", json={**body, "objective": "lifetime_taxes"})
        low = r.json()
        best = next(c for c in low["candidates"] if c["is_best"])
        assert best["objective_value"] == min(c["objective_value"] for c in low["candidates"] if c["success"])
        # Validation: Roth source, unknown objective, foreign milestone.
        r = await client.post(f"/api/plans/{pid}/tax-strategies/compare", json={**body, "source_account_id": roth["id"]})
        assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "source_account_id"
        r = await client.post(f"/api/plans/{pid}/tax-strategies/compare", json={**body, "objective": "vibes"})
        assert r.status_code == 422
        r = await client.post(f"/api/plans/{pid}/tax-strategies/compare", json={**body, "start_milestone_id": new_id()})
        assert r.status_code == 422
        # Applying the proposal persists the new fields and the simulation honours them.
        proposal = {"priority_rank": 1,
                    "priority_type": "roth_conversion", "source_account_id": ira["id"], "target_account_id": roth["id"],
                    "conversion_mode": "fill_bracket", "bracket_ceiling_rate": 0.22, "start_milestone_id": retire["id"]}
        r = await client.put(f"/api/plans/{pid}/priorities", json={"expected_revision": (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"], "items": [proposal]})
        assert r.status_code == 200, r.text
        saved = r.json()["items"][0]
        assert saved["conversion_mode"] == "fill_bracket" and saved["bracket_ceiling_rate"] == 0.22
        assert saved["start_milestone_id"] == retire["id"]
        sim = (await client.post(f"/api/plans/{pid}/simulate")).json()
        converted = sum(t["amount"] for s in sim["yearly_snapshots"] for t in s["transfers"] if t["target_account_id"] == roth["id"])
        assert converted == pytest.approx(next(c for c in out["candidates"] if c["key"] == "fill_2200")["total_converted"], rel=1e-6)
        r = await client.put(f"/api/plans/{pid}/priorities", json={"expected_revision": (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"], "items": [{**proposal, "bracket_ceiling_rate": None}]})
        assert r.status_code == 422

    @pytest.mark.anyio
    async def test_gain_harvest_strategy_comparison_and_apply(self, client: AsyncClient):
        """Gain-harvesting candidates fill capital-gains brackets and can be
        applied as a priority."""
        plan = await create_plan(client, name="Harvest", birth_year=1966, life_expectancy=75, filing_status="single")
        pid = plan["id"]
        brok = await _create_account(client, name="Brokerage", account_type="taxable_brokerage", balance=600_000, cost_basis=200_000)
        cash = await _create_account(client, name="Cash", account_type="checking", balance=400_000)
        r = await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living", "annual_amount": 40_000})
        assert r.status_code == 201
        r = await client.put(f"/api/plans/{pid}/drawdown-order", json={"items": [{"rank": 1, "source_account_id": cash["id"]}, {"rank": 2, "source_account_id": brok["id"]}]})
        assert r.status_code in (200, 201)
        body = {"strategy_type": "gain_harvest", "source_account_id": brok["id"], "bracket_ceilings": [0.0, 0.15], "objective": "lifetime_taxes"}
        r = await client.post(f"/api/plans/{pid}/tax-strategies/compare", json=body)
        assert r.status_code == 200, r.text
        out = r.json()
        assert [c["key"] for c in out["candidates"]] == ["baseline", "fill_0", "fill_1500"]
        zero = out["candidates"][1]
        assert zero["total_converted"] > 0 and zero["lifetime_taxes"] <= out["candidates"][0]["lifetime_taxes"] + 1
        assert out["proposed_priority"] is None or out["proposed_priority"]["priority_type"] == "gain_harvest"
        # Validation: IRA source, missing basis.
        ira = await _create_account(client, name="IRA", account_type="traditional_ira", balance=100_000)
        r = await client.post(f"/api/plans/{pid}/tax-strategies/compare", json={**body, "source_account_id": ira["id"]})
        assert r.status_code == 422
        nobasis = await _create_account(client, name="NoBasis", account_type="taxable_brokerage", balance=100_000)
        r = await client.post(f"/api/plans/{pid}/tax-strategies/compare", json={**body, "source_account_id": nobasis["id"]})
        assert r.status_code == 422 and "basis" in r.json()["error"]["message"]
        # Apply as a priority; simulation reports harvested gains.
        r = await client.put(f"/api/plans/{pid}/priorities", json={"expected_revision": (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"], "items": [{"priority_rank": 1, "priority_type": "gain_harvest", "source_account_id": brok["id"], "conversion_mode": "fill_bracket", "bracket_ceiling_rate": 0.0}]})
        assert r.status_code == 200, r.text
        assert r.json()["items"][0]["priority_type"] == "gain_harvest"
        sim = (await client.post(f"/api/plans/{pid}/simulate")).json()
        assert sum(s["harvested_gains"] for s in sim["yearly_snapshots"]) == pytest.approx(zero["total_converted"], rel=1e-6)
        r = await client.put(f"/api/plans/{pid}/priorities", json={"expected_revision": (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"], "items": [{"priority_rank": 1, "priority_type": "gain_harvest", "source_account_id": brok["id"]}]})
        assert r.status_code == 422  # harvest requires fill_bracket + rate

    @pytest.mark.anyio
    async def test_withdrawal_strategy_comparison_endpoint(self, client: AsyncClient):
        """Textbook withdrawal rules run through the full plan with planned
        spending reported separately."""
        plan = await create_plan(client, name="Withdrawals", birth_year=1965, life_expectancy=80, filing_status="single")
        pid = plan["id"]
        await _create_account(client, name="Brokerage", account_type="taxable_brokerage", balance=1_200_000, cost_basis=900_000)
        r = await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living", "annual_amount": 45_000})
        assert r.status_code == 201
        retire = await _create_milestone(client, pid, name="Retire", trigger_type="age", trigger_value=62)
        body = {"methods": ["constant_dollar", "vanguard_dynamic"], "initial_rate": 0.04, "start_milestone_id": retire["id"], "monte_carlo_trials": 4, "seed": 3}
        r = await client.post(f"/api/plans/{pid}/withdrawal-strategies/compare", json=body)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["planned"]["method"] == "planned"
        # Both rows begin at retirement, following the prorated opening year.
        assert out["planned"]["start_year"] == 2027
        assert out["planned"]["spending_path"][0]["year"] == 2027
        assert out["planned"]["spending_path"][0]["nominal"] == pytest.approx(45_000 * 1.03)
        assert out["planned"]["spending_path"][1]["nominal"] == pytest.approx(out["planned"]["first_year_spending"] * 1.03)
        assert [s["method"] for s in out["strategies"]] == ["constant_dollar", "vanguard_dynamic"]
        for s in out["strategies"]:
            assert s["start_year"] == 2027 and s["first_year_spending"] > 0
            assert 0 <= s["monte_carlo_success_rate"] <= 1
            assert s["spending_path"][0]["planned_nominal"] is not None
        assert set(out["method_labels"]) >= {"constant_dollar", "guyton_klinger", "rmd_table"}
        r = await client.post(f"/api/plans/{pid}/withdrawal-strategies/compare", json={**body, "methods": ["nope"]})
        assert r.status_code == 422
        r = await client.post(f"/api/plans/{pid}/withdrawal-strategies/compare", json={**body, "start_milestone_id": new_id()})
        assert r.status_code == 422
        r = await client.post(f"/api/plans/{pid}/withdrawal-strategies/compare", json={**body, "initial_rate": 0.5})
        assert r.status_code == 422

    @pytest.mark.anyio
    async def test_update_plan_residency_periods_replaces_list(
        self, client: AsyncClient
    ):
        """PATCH with a new residency_periods list fully replaces the old one.

        Regression guard for 22.1.1b: accidental merge instead of replace would
        leak stale periods into the simulation and drive wrong state tax.
        """
        plan = await create_plan(client, name="Residency Plan", state_code="CA")
        plan_id = plan["id"]

        r = await client.put(
            f"/api/plans/{plan_id}",
            json={
                "residency_periods": [
                    {"state_code": "CA", "start_year": 2026, "end_year": 2029, "rank": 0},
                    {"state_code": "NV", "start_year": 2030, "rank": 1},
                ]
            },
        )
        assert r.status_code == 200
        got = await client.get(f"/api/plans/{plan_id}")
        periods = got.json()["residency_periods"]
        assert len(periods) == 2
        states_after_first = sorted(p["state_code"] for p in periods)
        assert states_after_first == ["CA", "NV"]

        r = await client.put(
            f"/api/plans/{plan_id}",
            json={
                "residency_periods": [
                    {"state_code": "TX", "start_year": 2026, "rank": 0},
                ]
            },
        )
        assert r.status_code == 200
        got = await client.get(f"/api/plans/{plan_id}")
        periods = got.json()["residency_periods"]
        assert len(periods) == 1
        assert periods[0]["state_code"] == "TX"
        assert periods[0]["start_year"] == 2026

        r = await client.put(
            f"/api/plans/{plan_id}",
            json={"name": "Renamed only"},
        )
        assert r.status_code == 200
        got = await client.get(f"/api/plans/{plan_id}")
        assert got.json()["name"] == "Renamed only"
        assert len(got.json()["residency_periods"]) == 1

        r = await client.put(
            f"/api/plans/{plan_id}",
            json={"residency_periods": []},
        )
        assert r.status_code == 200
        got = await client.get(f"/api/plans/{plan_id}")
        assert got.json()["residency_periods"] == []

    @pytest.mark.anyio
    async def test_delete_plan(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.delete(f"/api/plans/{plan['id']}")
        assert r.status_code == 204

        # Verify gone
        r = await client.get(f"/api/plans/{plan['id']}")
        assert r.status_code == 404

    @pytest.mark.anyio
    async def test_get_nonexistent_plan_404(self, client: AsyncClient):
        fake_id = new_id()
        r = await client.get(f"/api/plans/{fake_id}")
        assert r.status_code == 404
        assert_error_shape(r.json())
        assert r.json()["error"]["code"] == "NOT_FOUND"


# ===========================================================================
# Milestones
# ===========================================================================


class TestMilestones:
    @pytest.mark.anyio
    async def test_create_milestone(self, client: AsyncClient):
        plan = await create_plan(client)
        ms = await _create_milestone(
            client, plan["id"], name="Retire", trigger_type="age", trigger_value=65
        )
        assert ms["name"] == "Retire"
        assert ms["trigger_type"] == "age"
        assert ms["plan_id"] == plan["id"]

    @pytest.mark.anyio
    async def test_list_milestones_sorted(self, client: AsyncClient):
        plan = await create_plan(client)
        pid = plan["id"]
        await _create_milestone(client, pid, name="B", sort_order=2)
        await _create_milestone(client, pid, name="A", sort_order=1)

        r = await client.get(f"/api/plans/{pid}/milestones")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 2
        assert items[0]["name"] == "A"
        assert items[1]["name"] == "B"

    @pytest.mark.anyio
    async def test_update_milestone(self, client: AsyncClient):
        plan = await create_plan(client)
        ms = await _create_milestone(client, plan["id"], name="Old")
        r = await client.put(
            f"/api/plans/{plan['id']}/milestones/{ms['id']}",
            json={"name": "New"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "New"

    @pytest.mark.anyio
    async def test_delete_milestone(self, client: AsyncClient):
        plan = await create_plan(client)
        ms = await _create_milestone(client, plan["id"])
        r = await client.delete(f"/api/plans/{plan['id']}/milestones/{ms['id']}")
        assert r.status_code == 204


# ===========================================================================
# Incomes
# ===========================================================================


class TestIncomes:
    @pytest.mark.anyio
    async def test_create_income(self, client: AsyncClient):
        plan = await create_plan(client)
        inc = await _create_income(client, plan["id"], name="Job", annual_amount=80000)
        assert inc["name"] == "Job"
        assert inc["annual_amount"] == 80000
        assert inc["plan_id"] == plan["id"]

    @pytest.mark.anyio
    async def test_create_income_with_milestone_refs(self, client: AsyncClient):
        plan = await create_plan(client)
        ms = await _create_milestone(client, plan["id"], name="Retire")
        inc = await _create_income(
            client, plan["id"], end_milestone_id=ms["id"]
        )
        assert inc["end_milestone_id"] == ms["id"]

    @pytest.mark.anyio
    async def test_list_incomes(self, client: AsyncClient):
        plan = await create_plan(client)
        await _create_income(client, plan["id"], name="A")
        await _create_income(client, plan["id"], name="B")
        r = await client.get(f"/api/plans/{plan['id']}/incomes")
        assert r.status_code == 200
        assert len(r.json()) == 2

    @pytest.mark.anyio
    async def test_update_income(self, client: AsyncClient):
        plan = await create_plan(client)
        inc = await _create_income(client, plan["id"])
        r = await client.put(
            f"/api/plans/{plan['id']}/incomes/{inc['id']}",
            json={"annual_amount": 120000},
        )
        assert r.status_code == 200
        assert r.json()["annual_amount"] == 120000

    @pytest.mark.anyio
    async def test_delete_income(self, client: AsyncClient):
        plan = await create_plan(client)
        inc = await _create_income(client, plan["id"])
        r = await client.delete(f"/api/plans/{plan['id']}/incomes/{inc['id']}")
        assert r.status_code == 204


# ===========================================================================
# Expenses
# ===========================================================================


class TestExpenses:
    @pytest.mark.anyio
    async def test_create_expense(self, client: AsyncClient):
        plan = await create_plan(client)
        exp = await _create_expense(client, plan["id"])
        assert exp["name"] == "Rent"
        assert exp["annual_amount"] == 24000
        assert exp["plan_id"] == plan["id"]

    @pytest.mark.anyio
    async def test_payroll_deduction_with_income(self, client: AsyncClient):
        plan = await create_plan(client)
        inc = await _create_income(client, plan["id"])
        exp = await _create_expense(
            client,
            plan["id"],
            name="401k",
            annual_amount=10000,
            is_payroll_deduction=True,
            tied_income_id=inc["id"],
        )
        assert exp["is_payroll_deduction"] is True
        assert exp["tied_income_id"] == inc["id"]

    @pytest.mark.anyio
    async def test_payroll_deduction_without_income_422(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.post(
            f"/api/plans/{plan['id']}/expenses",
            json={
                "name": "Bad payroll",
                "annual_amount": 5000,
                "is_payroll_deduction": True,
                # no tied_income_id
            },
        )
        assert r.status_code == 422
        assert_error_shape(r.json())

    @pytest.mark.anyio
    async def test_list_expenses(self, client: AsyncClient):
        plan = await create_plan(client)
        await _create_expense(client, plan["id"], name="A")
        await _create_expense(client, plan["id"], name="B")
        r = await client.get(f"/api/plans/{plan['id']}/expenses")
        assert r.status_code == 200
        assert len(r.json()) == 2

    @pytest.mark.anyio
    async def test_update_expense(self, client: AsyncClient):
        plan = await create_plan(client)
        exp = await _create_expense(client, plan["id"])
        r = await client.put(
            f"/api/plans/{plan['id']}/expenses/{exp['id']}",
            json={"annual_amount": 30000},
        )
        assert r.status_code == 200
        assert r.json()["annual_amount"] == 30000

    @pytest.mark.anyio
    async def test_delete_expense(self, client: AsyncClient):
        plan = await create_plan(client)
        exp = await _create_expense(client, plan["id"])
        r = await client.delete(f"/api/plans/{plan['id']}/expenses/{exp['id']}")
        assert r.status_code == 204


# ===========================================================================
# Accounts
# ===========================================================================


class TestAccounts:
    @pytest.mark.anyio
    async def test_create_account(self, client: AsyncClient, test_user):
        acct = await _create_account(client, name="My 401k", account_type="traditional_401k")
        assert acct["name"] == "My 401k"
        assert acct["account_type"] == "traditional_401k"
        assert acct["user_id"] == str(test_user.id)

    @pytest.mark.anyio
    async def test_list_accounts(self, client: AsyncClient):
        await _create_account(client, name="A")
        await _create_account(client, name="B")
        r = await client.get("/api/accounts")
        assert r.status_code == 200
        assert len(r.json()) >= 2

    @pytest.mark.anyio
    async def test_delete_account(self, client: AsyncClient):
        acct = await _create_account(client)
        r = await client.delete(f"/api/accounts/{acct['id']}")
        assert r.status_code == 204

    @pytest.mark.anyio
    async def test_create_account_auto_adds_drawdown_entry(self, client: AsyncClient):
        plan = await create_plan(client)
        acct = await _create_account(client)

        r = await client.get(f"/api/plans/{plan['id']}/drawdown-order")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["source_account_id"] == acct["id"]
        assert items[0]["rank"] == 1

    @pytest.mark.anyio
    async def test_auto_drawdown_ordered_by_type_priority(self, client: AsyncClient):
        plan = await create_plan(client)
        # Create in reverse priority order — insertion should sort them:
        # cash → taxable → traditional → roth
        roth = await _create_account(client, name="Roth", account_type="roth_ira")
        trad = await _create_account(client, name="401k", account_type="traditional_401k")
        brokerage = await _create_account(
            client, name="Brokerage", account_type="taxable_brokerage"
        )
        cash = await _create_account(client, name="Cash", account_type="savings")

        r = await client.get(f"/api/plans/{plan['id']}/drawdown-order")
        assert r.status_code == 200
        items = sorted(r.json(), key=lambda x: x["rank"])
        assert [i["source_account_id"] for i in items] == [
            cash["id"],
            brokerage["id"],
            trad["id"],
            roth["id"],
        ]
        assert [i["rank"] for i in items] == [1, 2, 3, 4]

    @pytest.mark.anyio
    async def test_529_excluded_from_auto_drawdown(self, client: AsyncClient):
        plan = await create_plan(client)
        await _create_account(
            client, name="College Fund", account_type="five_twenty_nine"
        )

        r = await client.get(f"/api/plans/{plan['id']}/drawdown-order")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.anyio
    async def test_delete_account_removes_drawdown_entry_and_compacts(
        self, client: AsyncClient
    ):
        plan = await create_plan(client)
        first = await _create_account(client, name="Cash", account_type="savings")
        second = await _create_account(
            client, name="Brokerage", account_type="taxable_brokerage"
        )

        r = await client.delete(f"/api/accounts/{first['id']}")
        assert r.status_code == 204

        r = await client.get(f"/api/plans/{plan['id']}/drawdown-order")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["source_account_id"] == second["id"]
        assert items[0]["rank"] == 1

    @pytest.mark.anyio
    async def test_delete_account_referenced_by_priority_409(self, client: AsyncClient):
        plan = await create_plan(client)
        acct = await _create_account(client)

        # Create a priority referencing this account
        await client.put(
            f"/api/plans/{plan['id']}/priorities",
            json={"expected_revision": (await client.get(f"/api/plans/{plan['id']}/priorities")).json()["revision"],
                "items": [
                    {
                        "priority_rank": 1,
                        "target_account_id": acct["id"],
                    }
                ]
            },
        )

        # Try to delete the referenced account
        r = await client.delete(f"/api/accounts/{acct['id']}")
        assert r.status_code == 409
        assert_error_shape(r.json())
        # The refusal names the screen that holds the rules and what to do there.
        message = r.json()["error"]["message"]
        assert "Income allocation" in message
        assert "remove" in message.lower() and "rules" in message.lower()
        assert acct["id"] in {row["id"] for row in (await client.get("/api/accounts")).json()}

    @pytest.mark.anyio
    async def test_cost_basis_roundtrip_taxable_brokerage(self, client: AsyncClient):
        acct = await _create_account(
            client,
            name="Brokerage",
            account_type="taxable_brokerage",
            balance=200000,
            cost_basis=150000,
        )
        assert acct["cost_basis"] == 150000

        r = await client.get("/api/accounts")
        assert r.status_code == 200
        fetched = next(a for a in r.json() if a["id"] == acct["id"])
        assert fetched["cost_basis"] == 150000

        r = await client.put(
            f"/api/accounts/{acct['id']}",
            json={
                "name": "Brokerage",
                "account_type": "taxable_brokerage",
                "balance": 200000,
                "owner": "self",
                "beneficiary_type": "non_edb",
                "cost_basis": 175000,
            },
        )
        assert r.status_code == 200
        assert r.json()["cost_basis"] == 175000

        r = await client.get("/api/accounts")
        fetched = next(a for a in r.json() if a["id"] == acct["id"])
        assert fetched["cost_basis"] == 175000

    @pytest.mark.anyio
    async def test_cost_basis_nulled_for_non_taxable(self, client: AsyncClient):
        acct = await _create_account(
            client,
            name="Checking",
            account_type="checking",
            balance=5000,
            cost_basis=50000,
        )
        assert acct["cost_basis"] is None

        r = await client.get("/api/accounts")
        fetched = next(a for a in r.json() if a["id"] == acct["id"])
        assert fetched["cost_basis"] is None

    @pytest.mark.anyio
    async def test_cost_basis_negative_rejected(self, client: AsyncClient):
        r = await client.post(
            "/api/accounts",
            json={
                "name": "Brokerage",
                "account_type": "taxable_brokerage",
                "balance": 200000,
                "cost_basis": -100,
            },
        )
        assert r.status_code == 422


# ===========================================================================
# Priorities (bulk update)
# ===========================================================================


class TestPriorities:
    @pytest.mark.anyio
    async def test_invalid_source_does_not_replace_existing(self, client: AsyncClient):
        plan = await create_plan(client)
        acct = await _create_account(client)
        url = f"/api/plans/{plan['id']}/priorities"
        original = {"priority_rank": 1, "target_account_id": acct["id"], "target_balance": 50000}
        assert (await client.put(url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": [original]})).status_code == 200
        invalid = {**original, "priority_type": "transfer", "source_account_id": str(uuid.uuid4())}
        assert (await client.put(url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": [invalid]})).status_code == 422
        saved = (await client.get(url)).json()["items"]
        assert len(saved) == 1 and saved[0]["target_balance"] == 50000

    @pytest.mark.anyio
    async def test_bulk_update_replaces_all(self, client: AsyncClient):
        plan = await create_plan(client)
        pid = plan["id"]
        acct = await _create_account(client)

        # First bulk update
        r = await client.put(
            f"/api/plans/{pid}/priorities",
            json={"expected_revision": (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"],
                "items": [
                    {"priority_rank": 1, "target_account_id": acct["id"], "max_annual_amount": 6500},
                    {"priority_rank": 2, "target_account_id": acct["id"]},
                ]
            },
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        assert items[0]["priority_rank"] == 1
        assert items[1]["priority_rank"] == 2

        # Replace with a single item
        r = await client.put(
            f"/api/plans/{pid}/priorities",
            json={"expected_revision": (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"], "items": [{"priority_rank": 1, "target_account_id": acct["id"]}]},
        )
        assert r.status_code == 200
        assert len(r.json()["items"]) == 1

    @pytest.mark.anyio
    async def test_duplicate_rank_422(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.put(
            f"/api/plans/{plan['id']}/priorities",
            json={"expected_revision": (await client.get(f"/api/plans/{plan['id']}/priorities")).json()["revision"],
                "items": [
                    {"priority_rank": 1},
                    {"priority_rank": 1},
                ]
            },
        )
        assert r.status_code == 422
        assert_error_shape(r.json())

    @pytest.mark.anyio
    async def test_list_priorities(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.get(f"/api/plans/{plan['id']}/priorities")
        assert r.status_code == 200
        assert isinstance(r.json()["items"], list)


# ===========================================================================
# Drawdown Order (bulk update)
# ===========================================================================


class TestDrawdownOrder:
    @pytest.mark.anyio
    async def test_bulk_update_replaces_all(self, client: AsyncClient):
        plan = await create_plan(client)
        pid = plan["id"]
        acct = await _create_account(client)

        r = await client.put(
            f"/api/plans/{pid}/drawdown-order",
            json={
                "items": [
                    {"rank": 1, "source_account_id": acct["id"]},
                    {"rank": 2, "source_account_id": acct["id"]},
                ]
            },
        )
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 2
        assert items[0]["rank"] == 1
        assert items[1]["rank"] == 2

    @pytest.mark.anyio
    async def test_empty_list_clears(self, client: AsyncClient):
        plan = await create_plan(client)
        pid = plan["id"]
        acct = await _create_account(client)

        # Add items first
        await client.put(
            f"/api/plans/{pid}/drawdown-order",
            json={"items": [{"rank": 1, "source_account_id": acct["id"]}]},
        )

        # Clear with empty list
        r = await client.put(
            f"/api/plans/{pid}/drawdown-order",
            json={"items": []},
        )
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.anyio
    async def test_duplicate_rank_422(self, client: AsyncClient):
        plan = await create_plan(client)
        r = await client.put(
            f"/api/plans/{plan['id']}/drawdown-order",
            json={"items": [{"rank": 1}, {"rank": 1}]},
        )
        assert r.status_code == 422
        assert_error_shape(r.json())


# ===========================================================================
# Simulation
# ===========================================================================


class TestSimulation:
    @pytest.mark.anyio
    async def test_simulate_simple_plan(self, client: AsyncClient):
        plan = await create_plan(client, birth_year=1990, life_expectancy=95)
        pid = plan["id"]

        # Create account, income, expense, priority
        acct = await _create_account(
            client, name="Brokerage", account_type="taxable_brokerage", balance=50000
        )
        await _create_income(client, pid, name="Salary", annual_amount=100000)
        await _create_expense(client, pid, name="Rent", annual_amount=24000)
        await client.put(
            f"/api/plans/{pid}/priorities",
            json={"expected_revision": (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"], "items": [{"priority_rank": 1, "target_account_id": acct["id"]}]},
        )

        r = await client.post(f"/api/plans/{pid}/simulate")
        assert r.status_code == 200
        data = r.json()
        # Validate response shape
        assert "metadata" in data
        assert "yearly_snapshots" in data
        meta = data["metadata"]
        assert meta["plan_id"] == pid
        assert "start_year" in meta
        assert "end_year" in meta
        assert "success" in meta
        assert len(data["yearly_snapshots"]) > 0

        snap = data["yearly_snapshots"][0]
        assert "year" in snap
        assert "age" in snap
        assert "gross_income" in snap
        assert "taxes" in snap
        assert "expenses" in snap
        assert "net_worth" in snap
        assert "accounts" in snap

    @pytest.mark.anyio
    async def test_simulate_nonexistent_plan_404(self, client: AsyncClient):
        r = await client.post(f"/api/plans/{new_id()}/simulate")
        assert r.status_code == 404


# ===========================================================================
# Error Contract
# ===========================================================================


class TestErrorContract:
    @pytest.mark.anyio
    async def test_404_error_shape(self, client: AsyncClient):
        """404 responses match {"error": {"code": "NOT_FOUND", "message": "...", "details": [...]}}"""
        r = await client.get(f"/api/plans/{new_id()}")
        assert r.status_code == 404
        body = r.json()
        assert_error_shape(body)
        assert body["error"]["code"] == "NOT_FOUND"

    @pytest.mark.anyio
    async def test_422_validation_error_shape(self, client: AsyncClient):
        """422 responses match {"error": {"code": "VALIDATION_ERROR", ...}}"""
        # Send invalid plan (missing required birth_year)
        r = await client.post("/api/plans", json={"name": "bad"})
        assert r.status_code == 422
        body = r.json()
        assert_error_shape(body)
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert len(body["error"]["details"]) > 0

    @pytest.mark.anyio
    async def test_409_error_shape(self, client: AsyncClient):
        """409 responses still have the error envelope."""
        plan = await create_plan(client)
        acct = await _create_account(client)
        await client.put(
            f"/api/plans/{plan['id']}/priorities",
            json={"expected_revision": (await client.get(f"/api/plans/{plan['id']}/priorities")).json()["revision"], "items": [{"priority_rank": 1, "target_account_id": acct["id"]}]},
        )
        r = await client.delete(f"/api/accounts/{acct['id']}")
        assert r.status_code == 409
        body = r.json()
        assert_error_shape(body)
