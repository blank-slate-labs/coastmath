"""/tax-regimes, plan persistence and simulation against the regime registry.

CoastMath ships only the custom regime (``XX``); packs are exercised with the
test-only ``QZ`` pack (tests/intl_fixture_pack.py). Plans saved in a retired
country still load and can switch, but cannot be created or run.
"""
import uuid

import pytest

from app.models.account import CurrentAccount
from app.models.plan import Plan
from coastmath.schemas.plan_data_request import PlanDataRequest
from tests.api_support import assert_error, create_plan

pytestmark = pytest.mark.anyio

CANADA_MESSAGE = ("This plan's country (Canada) is no longer supported. "
                  "Switch the plan to United States or Other (custom).")
CUSTOM = {"meta": {"country": "XX", "name": "Elsewhere", "base_year": 2026, "currency": "EUR"},
          "national": [{"id": "income", "label": "Income tax", "category": "income_national",
                        "brackets": [{"lower": 0, "rate": 0.2}]}]}
JOB = {"name": "Job", "annual_amount": 80_000, "owner": "self"}


async def test_route_lists_only_the_custom_regime(client):
    response = await client.get("/api/tax-regimes")
    assert response.status_code == 200, response.text
    (custom,) = response.json()["countries"]
    assert (custom["code"], custom["name"], custom["custom"], custom["currency"]) == (
        "XX", "Other (custom)", True, None)
    assert custom["account_kinds"] == [] and custom["benefit_rules"] == []


async def test_route_lists_installed_packs_and_custom(client, fixture_pack):
    response = await client.get("/api/tax-regimes")
    assert response.status_code == 200, response.text
    countries = {entry["code"]: entry for entry in response.json()["countries"]}
    assert list(countries) == ["QZ", "XX"]
    pack = countries["QZ"]
    assert (pack["currency"], pack["filing_unit"], pack["default_region"], pack["custom"]) == (
        "EUR", "individual", "N", False)
    assert pack["spec_years"] == [2026, 2027]
    assert pack["approximations"]


async def test_country_plans_validate_against_the_registry(client, fixture_pack):
    created = await client.post("/api/plans", json={"name": "North", "birth_year": 1970,
                                                     "tax_country": "QZ", "tax_region": "N", "currency": "EUR"})
    assert created.status_code == 201, created.text
    assert (created.json()["tax_country"], created.json()["tax_region"]) == ("QZ", "N")
    # A region of another country, and a country without a regime, are refused.
    assert (await client.post("/api/plans", json={"name": "x", "birth_year": 1970, "tax_country": "QZ",
                                                  "tax_region": "AUK"})).status_code == 422
    assert (await client.post("/api/plans", json={"name": "x", "birth_year": 1970,
                                                  "tax_country": "QQ"})).status_code == 422
    other = await client.post("/api/plans", json={"name": "Other", "birth_year": 1970, "tax_country": "XX",
                                                  "currency": "EUR", "intl_settings": {"custom_regime": CUSTOM}})
    assert other.status_code == 201, other.text
    bad = {**CUSTOM, "national": [{"id": "income", "label": "x", "category": "income_national",
                                   "brackets": [{"lower": 0, "rate": 2}]}]}
    assert (await client.post("/api/plans", json={"name": "Bad", "birth_year": 1970, "tax_country": "XX",
                                                  "intl_settings": {"custom_regime": bad}})).status_code == 422
    # Overrides are validated by the spec's own section models.
    wealth = await client.put(f"/api/plans/{created.json()['id']}", json={
        "intl_settings": {"wealth_tax": {"rate": 0.01, "allowance": 1_000_000}}})
    assert wealth.status_code == 200, wealth.text
    assert (await client.put(f"/api/plans/{created.json()['id']}", json={
        "intl_settings": {"wealth_tax": {"rate": 0.01, "unknown": 1}}})).status_code == 422


def test_stateless_request_rejects_us_only_settings_when_every_year_is_abroad(fixture_pack):
    base = {"plan_id": str(uuid.uuid4()), "birth_year": 1970, "start_year": 2026,
            "tax_settings": {"tax_target": {"kind": "irmaa_tier", "irmaa_tier": 1}}}
    with pytest.raises(ValueError, match="US-only settings"):
        PlanDataRequest.model_validate({**base, "tax_country": "QZ"})
    # A move from the US keeps them for the US years.
    PlanDataRequest.model_validate({**base, "tax_country": "QZ", "residency_periods": [
        {"country": "US", "state_code": "TX", "end_year": 2030}]})
    PlanDataRequest.model_validate(base)


async def test_persisted_simulation_reports_us_only_settings_as_validation_errors(client, fixture_pack):
    created = await client.post("/api/plans", json={
        "name": "Abroad", "birth_year": 1970, "tax_country": "QZ",
        "tax_settings": {"tax_target": {"kind": "irmaa_tier", "irmaa_tier": 1}}})
    assert created.status_code == 201, created.text
    response = await client.post(f"/api/plans/{created.json()['id']}/simulate")
    assert response.status_code == 422
    assert "US-only settings" in response.json()["error"]["message"]


async def test_custom_regime_plan_simulates(client):
    plan = await create_plan(client, birth_year=1970, tax_country="XX", currency="EUR",
                             intl_settings={"custom_regime": CUSTOM})
    assert (await client.post(f"/api/plans/{plan['id']}/incomes", json=JOB)).status_code == 201
    response = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert response.status_code == 200, response.text
    first = response.json()["yearly_snapshots"][0]
    assert first["tax_country"] == "XX"
    assert first["national_income_tax"] > 0 and first["federal_tax"] == 0


# ---------------------------------------------------------------------------
# Retired countries
# ---------------------------------------------------------------------------


async def test_a_retired_country_cannot_be_chosen(client):
    created = await client.post("/api/plans", json={"name": "x", "birth_year": 1970, "tax_country": "CA"})
    error = assert_error(created, 422, "VALIDATION_ERROR", "tax_country")
    assert CANADA_MESSAGE in error["details"][0]["reason"]
    plan = await create_plan(client, birth_year=1970)
    assert_error(await client.put(f"/api/plans/{plan['id']}", json={"tax_country": "CA"}),
                 422, "VALIDATION_ERROR", "tax_country")
    moved = await client.put(f"/api/plans/{plan['id']}", json={"residency_periods": [
        {"country": "GB", "start_year": 2030}]})
    error = assert_error(moved, 422, "VALIDATION_ERROR", "residency_periods.0.country")
    assert "(United Kingdom) is no longer supported" in error["details"][0]["reason"]


async def _retired_plan(client, db_session) -> tuple[str, str]:
    """A plan saved in Canada before the packs were removed, with its benefits, room and an RRSP."""
    plan = await create_plan(client, birth_year=1970)
    assert (await client.post(f"/api/plans/{plan['id']}/incomes", json=JOB)).status_code == 201
    account = await client.post(f"/api/accounts?plan_id={plan['id']}",
                                json={"name": "RRSP", "account_type": "other", "balance": 50_000})
    assert account.status_code == 201, account.text
    row = db_session.get(Plan, uuid.UUID(plan["id"]))
    row.tax_country, row.tax_region, row.currency = "CA", "ON", "CAD"
    row.intl_settings = {
        "benefits": [{"rule": "CA:cpp", "owner": "self", "start_age": 65, "params": {"monthly_amount_at_65": 1000}}],
        "starting_room": [{"kind": "CA:tfsa", "owner": "self", "amount": 25_000}],
    }
    db_session.get(CurrentAccount, uuid.UUID(account.json()["id"])).intl_account_kind = "CA:rrsp"
    db_session.commit()
    return plan["id"], account.json()["id"]


async def test_a_saved_retired_country_plan_loads_but_does_not_run(client, db_session):
    plan_id, account_id = await _retired_plan(client, db_session)
    loaded = await client.get(f"/api/plans/{plan_id}")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["tax_country"] == "CA"
    assert any(p["id"] == plan_id for p in (await client.get("/api/plans")).json())
    for path in ("simulate", "monte-carlo"):
        response = await client.post(f"/api/plans/{plan_id}/{path}", json={} if path == "monte-carlo" else None)
        error = assert_error(response, 422, "VALIDATION_ERROR", "tax_country")
        assert error["message"] == CANADA_MESSAGE
    # Edits that leave the country alone still save, including the account's leftover kind.
    renamed = await client.put(f"/api/plans/{plan_id}", json={"name": "Renamed"})
    assert renamed.status_code == 200, renamed.text
    # A client that resends the whole plan, saved country and leftovers included, still saves.
    stored = renamed.json()
    resent = await client.put(f"/api/plans/{plan_id}", json={
        "name": "Resent", "tax_country": "CA", "tax_region": "ON", "currency": "CAD",
        "intl_settings": stored["intl_settings"]})
    assert resent.status_code == 200, resent.text
    assert resent.json()["tax_country"] == "CA" and resent.json()["intl_settings"]["benefits"] == []
    account = await client.put(f"/api/accounts/{account_id}?plan_id={plan_id}",
                               json={"name": "Old RRSP", "account_type": "other", "balance": 50_000,
                                     "intl_account_kind": "CA:rrsp"})
    assert account.status_code == 200, account.text
    assert account.json()["intl_account_kind"] == "CA:rrsp"
    # A new account cannot take a retired kind.
    assert (await client.post(f"/api/accounts?plan_id={plan_id}", json={
        "name": "TFSA", "account_type": "other", "intl_account_kind": "CA:tfsa"})).status_code == 422


async def test_switching_a_retired_country_plan_to_the_us_runs(client, db_session):
    plan_id, _ = await _retired_plan(client, db_session)
    switched = await client.put(f"/api/plans/{plan_id}", json={"tax_country": "US", "currency": "USD"})
    assert switched.status_code == 200, switched.text
    data = switched.json()
    assert (data["tax_country"], data["tax_region"]) == ("US", None)
    # The retired country's benefits and room are dropped; nothing could apply them.
    assert data["intl_settings"]["benefits"] == [] and "starting_room" not in data["intl_settings"]
    response = await client.post(f"/api/plans/{plan_id}/simulate")
    assert response.status_code == 200, response.text
    assert response.json()["yearly_snapshots"][0]["federal_tax"] > 0


async def test_switching_to_custom_accepts_whole_settings_with_leftovers(client, db_session):
    """A client sends intl_settings whole: leftovers of the retired country are dropped, not refused."""
    plan_id, _ = await _retired_plan(client, db_session)
    stored = (await client.get(f"/api/plans/{plan_id}")).json()["intl_settings"]
    switched = await client.put(f"/api/plans/{plan_id}", json={
        "tax_country": "XX", "currency": "EUR", "intl_settings": {**stored, "custom_regime": CUSTOM}})
    assert switched.status_code == 200, switched.text
    settings = switched.json()["intl_settings"]
    assert settings["benefits"] == [] and "starting_room" not in settings
    assert settings["custom_regime"]["meta"]["name"] == "Elsewhere"
    response = await client.post(f"/api/plans/{plan_id}/simulate")
    assert response.status_code == 200, response.text
    assert response.json()["yearly_snapshots"][0]["tax_country"] == "XX"
