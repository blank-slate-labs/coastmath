"""Independent payer accounting, shared owner limits and saved API boundaries."""
import uuid
from copy import deepcopy
from dataclasses import asdict

import pytest
from pydantic import ValidationError

from coastmath.engine.simulator import _process_qcds, run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    PlanData,
    SimState,
)
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data
from tests.scenario_support import post


def gift(source=None, amount=20000):
    return CharityData("q", "QCD", "qcd", amount, source_account_id=source)


def payer_state():
    return SimState(year=2026, owner_ages={"self": 72, "spouse": 69},
                    owner_birth_months={"self": 5, "spouse": 1}, accounts={
        "inherited": AccountInfo(900000, "traditional_ira", owner="self", inherited_year=2024),
        "own": AccountInfo(500000, "traditional_ira", owner="self"),
        "spouse": AccountInfo(300000, "traditional_ira", owner="spouse"),
    })


@pytest.mark.parametrize("source,own_end,inherited_end", [("own", 480000, 900000), ("inherited", 500000, 900000), (None, 500000, 900000)])
def test_payer_uses_selected_rmd_and_no_other_ira(source, own_end, inherited_end):
    state = payer_state()
    # The inherited RMD has already been distributed. Only an inherited-payer
    # QCD (or legacy auto-allocation) can redirect that distribution to charity.
    amount = _process_qcds(state, [gift(source)], 52941.17647058824, set(),
                          rmd_by_owner={"self": 52941.17647058824},
                          rmd_by_account={"inherited": 52941.17647058824})
    assert amount == 20000
    assert state.accounts["own"].balance == own_end
    assert state.accounts["inherited"].balance == inherited_end
    assert state.accounts["spouse"].balance == 300000


def test_bound_and_unbound_gifts_share_one_owner_cap_and_never_reuse_rmd():
    state = payer_state()
    amount = _process_qcds(state, [gift("inherited", 40000), gift("inherited", 40000), gift(None, 40000)],
                          50000, set(), qcd_cap=100000,
                          rmd_by_owner={"self": 50000}, rmd_by_account={"inherited": 50000})
    assert amount == 100000
    assert state.accounts["inherited"].balance == 850000
    assert state.accounts["own"].balance == 500000
    assert state.accounts["spouse"].balance == 300000


def test_empty_or_ineligible_payer_does_not_fall_back_to_another_ira():
    state = payer_state()
    state.accounts["own"].balance = 0
    assert _process_qcds(state, [gift("own")], 50000, set(), rmd_by_owner={"self": 50000}, rmd_by_account={"inherited": 50000}) == 0
    assert _process_qcds(state, [gift("spouse")], 50000, set(), rmd_by_owner={"self": 50000}, rmd_by_account={"inherited": 50000}) == 0
    assert state.accounts["inherited"].balance == 900000


def base_plan(source):
    return PlanData(plan_id="db06b786-12e2-4e9c-b2bf-f0428aafdb29", birth_year=1954, birth_month=5,
        life_expectancy=73, spouse_birth_year=1956, spouse_birth_month=1,
        spouse_life_expectancy=92, filing_status="married_filing_jointly", start_year=2026,
        accounts={"inherited": AccountInfo(900000, "traditional_ira", owner="self", inherited_year=2024,
            inheritance_settings={"distribution_method": "ten_year", "decedent_birth_year": 1935, "decedent_died_after_rbd": True}),
            "own": AccountInfo(500000, "traditional_ira", owner="self")},
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0, cash_yield_rate=0),
        charity_entities=[gift(source)], tax_settings={"mode": "flat", "ordinary_income_tax_rate": .12, "capital_gains_tax_rate": 0})


def test_independent_full_simulation_payer_tax_and_cash_accounting():
    unbound = run_simulation(base_plan(None)).yearly_snapshots[0]
    bound = run_simulation(base_plan("own")).yearly_snapshots[0]
    rmd = 900000 / 17.0  # Single Life age71=18.0 in2025, minus one in2026.
    assert bound.federal_tax == pytest.approx(rmd * .12)
    assert unbound.federal_tax == pytest.approx((rmd - 20000) * .12)
    assert bound.accounts["own"] == 480000
    assert unbound.accounts["own"] == 500000
    assert bound.accounts["inherited"] == unbound.accounts["inherited"] == pytest.approx(900000 - rmd)
    assert bound.net_worth == pytest.approx(1400000 - 20000 - rmd * .12)
    assert unbound.net_worth == pytest.approx(1400000 - 20000 - (rmd - 20000) * .12)
    assert sum(e.amount for e in bound.cash_flow.expenses if e.name == "QCD to charity") == 20000
    assert sum(x.amount for x in bound.cash_flow.income_sources if x.name == "RMD") == pytest.approx(rmd)


@pytest.mark.parametrize("source,kind", [("missing", "qcd"), ("own", "direct")])
def test_invalid_payer_rejected_by_request_and_engine(source, kind):
    plan = base_plan(source)
    plan.charity_entities[0].entity_type = kind
    with pytest.raises(ValidationError, match="QCD source"):
        PlanDataRequest.model_validate(asdict(plan))
    with pytest.raises(ValueError, match="QCD source"):
        run_simulation(plan)


def test_stateless_roundtrip_preserves_payer_and_input():
    plan = base_plan("own")
    original = deepcopy(plan)
    restored = request_to_engine_data(PlanDataRequest.model_validate(asdict(plan)))
    assert restored.charity_entities[0].source_account_id == "own"
    run_simulation(plan)
    assert plan == original


@pytest.mark.anyio
async def test_saved_payer_roundtrip_rejects_foreign_type_and_preserves_references(client):
    household = (await client.post("/api/clients/personal")).json()
    plan = await post(client, "/plans", {"name": "QCD", "birth_year": 1954, "life_expectancy": 73, "client_id": household["id"]})
    root = "/plans/" + plan["id"]
    own = await post(client, root + "/accounts", {"name": "Own IRA", "account_type": "traditional_ira", "balance": 500000})
    cash = await post(client, root + "/accounts", {"name": "Cash", "account_type": "checking", "balance": 10000})
    other = await post(client, "/plans", {"name": "Other", "birth_year": 1954, "client_id": household["id"]})
    foreign = await post(client, "/plans/" + other["id"] + "/accounts", {"name": "Other IRA", "account_type": "traditional_ira", "balance": 500000})
    payload = {"name": "QCD", "entity_type": "qcd", "annual_amount": 20000, "source_account_id": own["id"]}
    for invalid in [cash["id"], foreign["id"], str(uuid.uuid4())]:
        response = await client.post("/api" + root + "/charities", json={**payload, "source_account_id": invalid})
        assert response.status_code == 422, response.text
    saved = await post(client, root + "/charities", payload)
    assert saved["source_account_id"] == own["id"]
    assert (await client.get("/api" + root + "/charities/" + saved["id"])).json()["source_account_id"] == own["id"]
    duplicate = await client.post("/api" + root + "/duplicate")
    assert duplicate.status_code == 201, duplicate.text
    copied_root = "/api/plans/" + duplicate.json()["id"]
    copied_accounts = (await client.get(copied_root + "/accounts")).json()
    copied_ira = next(a for a in copied_accounts if a["name"] == "Own IRA")
    assert copied_ira["id"] != own["id"]
    copied_gift = (await client.get(copied_root + "/charities")).json()[0]
    assert copied_gift["source_account_id"] == copied_ira["id"]
    # The saved simulation route exercises ORM conversion of the payer.
    response = await client.post("/api" + root + "/simulate")
    assert response.status_code == 200, response.text
    assert (await client.delete("/api" + root + "/accounts/" + own["id"])).status_code == 409
    assert (await client.put("/api" + root + "/accounts/" + own["id"], json={"account_type": "checking"})).status_code == 409
    rejected = await client.patch("/api" + root + "/charities/" + saved["id"], json={"entity_type": "direct"})
    assert rejected.status_code == 422
    assert (await client.get("/api" + root + "/charities/" + saved["id"])).json()["entity_type"] == "qcd"
    updated = await client.patch("/api" + root + "/charities/" + saved["id"], json={"source_account_id": None})
    assert updated.status_code == 200 and updated.json()["source_account_id"] is None
    assert (await client.delete("/api" + root + "/accounts/" + own["id"])).status_code == 204


@pytest.mark.anyio
async def test_fixed_snapshot_payer_needs_no_live_account_row(client):
    aid = str(uuid.uuid4())
    plan = await post(client, "/plans", {"name": "Historical QCD", "birth_year": 1954,
        "plan_type": "FIXED_DATE", "start_date": "2026-01-01", "life_expectancy": 73,
        "snapshot_conditions": {aid: {"name": "Historical IRA", "account_type": "traditional_ira", "balance": 500000, "owner": "self"}}})
    saved = await post(client, "/plans/" + plan["id"] + "/charities", {"name": "QCD", "entity_type": "qcd", "annual_amount": 20000, "source_account_id": aid})
    assert saved["source_account_id"] == aid
    response = await client.post("/api/plans/" + plan["id"] + "/simulate")
    assert response.status_code == 200, response.text
    assert response.json()["yearly_snapshots"][0]["accounts"][aid] < 500000 * 1.1
