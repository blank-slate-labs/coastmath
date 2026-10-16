"""Country tax regime fields: plans, residency periods, accounts, duplication and /tax-regimes."""
import uuid

import pytest

from app.engine.plan_converter import plan_to_engine_data
from app.models.account import CurrentAccount
from app.models.plan import Plan
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from tests.api_support import create_plan
from tests.intl_support import intl_double_package  # noqa: F401

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("intl_double_package")]

BENEFIT = {"rule": "ZZ:pension", "owner": "self", "start_age": 66, "params": {"annual_amount": 12000}}


async def _plan(client, **fields):
    return await create_plan(client, **{"name": "Abroad", "birth_year": 1970, **fields})


async def test_us_defaults_and_existing_reads_unchanged(client):
    plan = await _plan(client)
    assert (plan["tax_country"], plan["tax_region"], plan["currency"]) == ("US", None, "USD")
    assert "intl_settings" not in plan
    account = await client.post(f"/api/accounts?plan_id={plan['id']}",
                                json={"name": "IRA", "account_type": "traditional_ira", "balance": 10})
    assert account.status_code == 201
    assert "intl_account_kind" not in account.json()


async def test_create_read_update_country_plan(client):
    plan = await _plan(client, tax_country="zz", tax_region="s", currency="tzs",
                       intl_settings={"benefits": [BENEFIT], "wealth_tax": {"rate": 0.01, "allowance": 100000}})
    assert (plan["tax_country"], plan["tax_region"], plan["currency"]) == ("ZZ", "S", "TZS")
    # Parameters are normalized by the rule's own model.
    assert plan["intl_settings"]["benefits"][0]["params"] == {
        "annual_amount": 12000.0, "default_start_age": 65, "survivor_fraction": 0.6}
    milestone = await client.post(f"/api/plans/{plan['id']}/milestones",
                                  json={"name": "Retire", "trigger_type": "age", "trigger_value": 65})
    assert milestone.status_code == 201, milestone.text
    benefit = {**BENEFIT, "start_age": None, "start_milestone_id": milestone.json()["id"]}
    updated = await client.put(f"/api/plans/{plan['id']}", json={
        "intl_settings": {"benefits": [benefit]},
        "residency_periods": [
            {"country": "US", "state_code": "WA", "start_year": 2026, "end_year": 2029},
            {"country": "ZZ", "region": "N", "state_code": "CA", "start_year": 2030},
        ],
    })
    assert updated.status_code == 200, updated.text
    data = updated.json()
    assert data["intl_settings"]["benefits"][0]["start_milestone_id"] == milestone.json()["id"]
    periods = data["residency_periods"]
    assert (periods[0]["country"], periods[0]["state_code"]) == ("US", "WA")
    # A period abroad never keeps a US state.
    assert (periods[1]["country"], periods[1]["region"], periods[1]["state_code"]) == ("ZZ", "N", None)
    # Switching country without a region clears the old region.
    switched = await client.put(f"/api/plans/{plan['id']}", json={"tax_country": "US"})
    assert switched.status_code == 200, switched.text
    assert (switched.json()["tax_country"], switched.json()["tax_region"]) == ("US", None)


@pytest.mark.parametrize("fields, field", [
    ({"tax_country": "QQ"}, "tax_country"),
    ({"tax_country": "ZZ", "tax_region": "E"}, "tax_region"),
    ({"tax_region": "S"}, "tax_region"),
    ({"currency": "ABC"}, "currency"),
    ({"tax_country": "XX"}, "custom_regime"),
    ({"tax_country": "ZZ", "intl_settings": {"benefits": [{"rule": "ZZ:none"}]}}, "rule"),
    ({"tax_country": "ZZ", "intl_settings": {"benefits": [{**BENEFIT, "params": {"annual_amount": -1}}]}}, "params"),
    ({"tax_country": "ZZ", "intl_settings": {"wealth_tax": {"rate": 2}}}, "wealth_tax"),
    ({"tax_country": "XX", "intl_settings": {"custom_regime": {"meta": {"country": "XX"}, "unknown": 1}}}, "custom_regime"),
])
async def test_invalid_regime_inputs_are_rejected(client, fields, field):
    response = await client.post("/api/plans", json={"name": "Bad", "birth_year": 1970, **fields})
    assert response.status_code == 422, (fields, response.text)


async def test_us_period_needs_a_state_and_regions_follow_their_country(client):
    plan = await _plan(client, tax_country="ZZ")
    for periods, field in [
        ([{"start_year": 2030, "country": "US"}], None),
        ([{"start_year": 2030, "country": "ZZ", "region": "WA"}], "residency_periods.0.country"),
    ]:
        response = await client.put(f"/api/plans/{plan['id']}", json={"residency_periods": periods})
        assert response.status_code == 422, response.text
        if field:
            assert response.json()["error"]["details"][0]["field"] == field
    us_plan = await _plan(client)
    response = await client.put(f"/api/plans/{us_plan['id']}", json={"residency_periods": [{"start_year": 2030}]})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "residency_periods.0.state_code"
    # A benefit milestone must belong to the plan.
    response = await client.put(f"/api/plans/{plan['id']}", json={"intl_settings": {"benefits": [
        {**BENEFIT, "start_age": None, "start_milestone_id": str(uuid.uuid4())}]}})
    assert response.status_code == 422


async def test_account_kind_sets_type_and_must_match_plan_countries(client, db_session):
    us_plan = await _plan(client)
    rejected = await client.post(f"/api/accounts?plan_id={us_plan['id']}",
                                 json={"name": "Saver", "account_type": "checking", "intl_account_kind": "ZZ:saver"})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["details"][0]["field"] == "intl_account_kind"
    unknown = await client.post(f"/api/accounts?plan_id={us_plan['id']}",
                                json={"name": "X", "account_type": "other", "intl_account_kind": "ZZ:nope"})
    assert unknown.status_code == 422
    plan = await _plan(client, tax_country="ZZ")
    created = await client.post(f"/api/accounts?plan_id={plan['id']}",
                                json={"name": "Saver", "account_type": "traditional_ira", "balance": 100,
                                      "intl_account_kind": "ZZ:saver"})
    assert created.status_code == 201, created.text
    assert (created.json()["account_type"], created.json()["intl_account_kind"]) == ("other", "ZZ:saver")
    broker = await client.post(f"/api/accounts?plan_id={plan['id']}",
                               json={"name": "Broker", "account_type": "checking", "balance": 100, "cost_basis": 50,
                                     "intl_account_kind": "ZZ:brokerage"})
    assert broker.json()["account_type"] == "taxable_brokerage"
    assert broker.json()["cost_basis"] == 50
    # Clearing the kind leaves an ordinary account.
    cleared = await client.put(f"/api/accounts/{created.json()['id']}?plan_id={plan['id']}",
                               json={"intl_account_kind": None, "account_type": "traditional_ira"})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["account_type"] == "traditional_ira"
    assert "intl_account_kind" not in cleared.json()


async def test_country_kinds_join_the_default_drawdown_order_by_category(client, db_session):
    plan = await _plan(client, tax_country="ZZ")
    names = {}
    for name, body in [
        ("free", {"account_type": "other", "intl_account_kind": "ZZ:free"}),
        ("roth", {"account_type": "roth_ira"}),
        ("saver", {"account_type": "other", "intl_account_kind": "ZZ:saver"}),
        ("cash", {"account_type": "savings"}),
        ("broker", {"account_type": "other", "intl_account_kind": "ZZ:brokerage"}),
    ]:
        response = await client.post(f"/api/accounts?plan_id={plan['id']}", json={"name": name, **body})
        assert response.status_code == 201, response.text
        names[response.json()["id"]] = name
    order = (await client.get(f"/api/plans/{plan['id']}")).json()["drawdown_order"]
    ranked = [names[entry["source_account_id"]] for entry in sorted(order, key=lambda e: e["rank"])]
    assert ranked == ["cash", "broker", "saver", "free", "roth"]


async def test_duplicate_carries_regime_fields_and_remaps_benefit_milestones(client, db_session, test_user):
    plan = await _plan(client, tax_country="ZZ", tax_region="N", currency="NZD")
    milestone = (await client.post(f"/api/plans/{plan['id']}/milestones",
                                   json={"name": "Retire", "trigger_type": "age", "trigger_value": 65})).json()
    update = await client.put(f"/api/plans/{plan['id']}", json={
        "intl_settings": {"benefits": [{**BENEFIT, "start_age": None, "start_milestone_id": milestone["id"]}]},
        "residency_periods": [{"country": "US", "state_code": "TX", "start_year": 2035}],
    })
    assert update.status_code == 200, update.text
    copied = await client.post(f"/api/plans/{plan['id']}/duplicate")
    assert copied.status_code == 201, copied.text
    data = copied.json()
    assert (data["tax_country"], data["tax_region"], data["currency"]) == ("ZZ", "N", "NZD")
    new_milestone = data["milestones"][0]["id"]
    assert new_milestone != milestone["id"]
    assert data["intl_settings"]["benefits"][0]["start_milestone_id"] == new_milestone
    assert (data["residency_periods"][0]["country"], data["residency_periods"][0]["state_code"]) == ("US", "TX")


async def test_client_plan_duplicate_copies_account_kinds(client, db_session):
    created = await client.post("/api/clients/personal")
    assert created.status_code == 200, created.text
    plan = await _plan(client, tax_country="ZZ", client_id=created.json()["id"])
    account = await client.post(f"/api/accounts?plan_id={plan['id']}",
                                json={"name": "Saver", "account_type": "other", "intl_account_kind": "ZZ:saver"})
    assert account.status_code == 201, account.text
    copied = await client.post(f"/api/plans/{plan['id']}/duplicate")
    assert copied.status_code == 201, copied.text
    kinds = {row.intl_account_kind for row in db_session.query(CurrentAccount).filter(
        CurrentAccount.plan_id == uuid.UUID(copied.json()["id"]))}
    assert kinds == {"ZZ:saver"}


async def test_converter_carries_fields(client, db_session):
    plan = await _plan(client, tax_country="ZZ", tax_region="S", currency="EUR",
                       intl_settings={"benefits": [BENEFIT]})
    await client.put(f"/api/plans/{plan['id']}", json={"residency_periods": [
        {"country": "US", "state_code": "OR", "start_year": 2040}]})
    await client.post(f"/api/accounts?plan_id={plan['id']}",
                      json={"name": "Saver", "account_type": "other", "intl_account_kind": "ZZ:saver"})
    row = db_session.get(Plan, uuid.UUID(plan["id"]))
    data = plan_to_engine_data(row, db_session.query(CurrentAccount).all())
    assert (data.tax_country, data.tax_region, data.currency) == ("ZZ", "S", "EUR")
    assert data.intl_settings["benefits"][0]["rule"] == "ZZ:pension"
    assert (data.residency_periods[0].country, data.residency_periods[0].state_code) == ("US", "OR")
    assert [a.intl_account_kind for a in data.accounts.values()] == ["ZZ:saver"]


def _request(**fields):
    return {"plan_id": str(uuid.uuid4()), "birth_year": 1970, "start_year": 2026, **fields}


def test_stateless_request_defaults_are_omitted_and_fields_convert():
    plain = PlanDataRequest.model_validate(_request())
    dumped = plain.model_dump()
    assert {"tax_country", "tax_region", "currency", "intl_settings"}.isdisjoint(dumped)
    request = PlanDataRequest.model_validate(_request(
        tax_country="ZZ", tax_region="N", currency="EUR", intl_settings={"benefits": [BENEFIT]},
        accounts={"a": {"balance": 1, "account_type": "traditional_ira", "intl_account_kind": "ZZ:saver"}},
        residency_periods=[{"country": "US", "state_code": "CA", "start_year": 2030}],
    ))
    data = request_to_engine_data(request)
    assert (data.tax_country, data.tax_region, data.currency) == ("ZZ", "N", "EUR")
    assert data.accounts["a"].account_type == "other"
    assert data.accounts["a"].intl_account_kind == "ZZ:saver"
    assert data.residency_periods[0].country == "US"
    assert data.intl_settings["benefits"][0]["params"]["annual_amount"] == 12000.0
    with pytest.raises(ValueError):
        PlanDataRequest.model_validate(_request(
            accounts={"a": {"balance": 1, "account_type": "other", "intl_account_kind": "ZZ:saver"}}))


async def test_tax_regimes_route(client):
    response = await client.get("/api/tax-regimes")
    assert response.status_code == 200, response.text
    countries = {entry["code"]: entry for entry in response.json()["countries"]}
    assert set(countries) == {"XX", "ZZ"}
    zz = countries["ZZ"]
    assert zz["regions"] == [{"code": "N", "name": "North"}, {"code": "S", "name": "South"}]
    saver = next(kind for kind in zz["account_kinds"] if kind["id"] == "ZZ:saver")
    assert (saver["label"], saver["category"]) == ("Saver", "tax_deferred")
    assert saver["rules"] == [
        "Contributions up to 10,000 a year, indexed with inflation (shared with the owner's other accounts of this group).",
        "Contributions only until age 70.",
        "Contributions are deductible.",
        "Withdrawals are taxed as income, except 25% of each withdrawal up to 20,000 in total.",
        "Withdrawals before age 60 pay a 20% penalty.",
        "Becomes a Retirement income at age 71.",
    ]
    assert (zz["default_region"], zz["custom"], countries["XX"]["custom"]) == (None, False, True)
    assert zz["benefit_rules"][0]["id"] == "ZZ:pension"
    assert "annual_amount" in zz["benefit_rules"][0]["params_schema"]["properties"]
    assert (zz["currency"], zz["filing_unit"], zz["spec_years"]) == ("TZS", "individual", [2026])
    assert zz["approximations"] == ["Test approximation."]


async def test_tax_regimes_route_requires_a_session(client):
    client.cookies.clear()
    assert (await client.get("/api/tax-regimes")).status_code == 401
