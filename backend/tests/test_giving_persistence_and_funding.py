"""Giving persistence and real funding sources."""
import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo, AssumptionData, CharityData, PlanData


@pytest.mark.parametrize("kind", ["direct", "daf"])
def test_split_gift_withdrawals_charge_balances_once(kind):
    plan = PlanData(plan_id=str(uuid.uuid4()), birth_year=1990, filing_status="single", life_expectancy=37, start_year=2026,
        assumptions=AssumptionData(stock_growth_rate=0, bond_return_rate=0, inflation_rate=0),
        accounts={"cash": AccountInfo(400, "checking", name="Cash"),
                  "broker": AccountInfo(2000, "taxable_brokerage", cost_basis=2000, name="Broker")},
        charity_entities=[CharityData("gift", "Gift", kind, 1200)])
    row = run_simulation(plan).yearly_snapshots[0]
    assert row.net_worth == pytest.approx(1200)  # 2400 initial dollars less one 1200 gift
    assert {d.account_id: d.amount for d in row.cash_flow.drawdowns} == {"cash": 400, "broker": 800}
    assert row.expenses == 1200


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["age", "date", "relative"])
async def test_giving_window_create_partial_update_and_stateless(client, kind):
    plan = (await client.post("/api/plans", json={"name": "Giving", "birth_year": 1990})).json()
    url = f"/api/plans/{plan['id']}"
    early = (await client.post(url + "/milestones", json={"name": "Early", "trigger_type": "age", "trigger_value": 65})).json()
    fields = {"age": {"trigger_value": 67}, "date": {"trigger_date": "2057-01-01"},
              "relative": {"relative_to_id": early["id"], "offset_years": 2}}[kind]
    late = (await client.post(url + "/milestones", json={"name": "Late", "trigger_type": kind, **fields})).json()
    gift = {"name": "Gift", "entity_type": "direct", "annual_amount": 1200,
            "start_milestone_id": late["id"], "end_milestone_id": early["id"]}
    bad = await client.post(url + "/charities", json=gift)
    assert bad.status_code == 422, bad.text
    gift["start_milestone_id"], gift["end_milestone_id"] = early["id"], late["id"]
    created = await client.post(url + "/charities", json=gift)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert (await client.patch(url + "/charities/" + cid, json={"start_milestone_id": late["id"]})).status_code == 422
    assert (await client.get(url + "/charities/" + cid)).json()["start_milestone_id"] == early["id"]
    assert (await client.patch(url + "/charities/" + cid, json={"name": "Corrected", "start_milestone_id": None})).status_code == 200
    assert (await client.get(url + "/charities/" + cid)).json()["name"] == "Corrected"
    blob = {"plan_id": plan["id"], "birth_year": 1990, "start_year": 2026,
            "milestones": [early, late], "charity_entities": [gift | {"id": cid}]}
    assert (await client.post("/api/simulate/stateless", json=blob)).status_code == 200
    blob["charity_entities"][0]["start_milestone_id"] = late["id"]
    assert (await client.post("/api/simulate/stateless", json=blob)).status_code == 422
    assert (await client.post(url + "/charities", json=gift | {"start_milestone_id": str(uuid.uuid4())})).status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("kind,birth", [("direct", 1990), ("daf", 1990), ("qcd", 1955), ("qcd", 1950)])
async def test_gift_funding_reconciles_db_and_stateless(client, kind, birth):
    plan = (await client.post("/api/plans", json={"name": "Giving flows", "birth_year": birth,
            "plan_type": "FIXED_DATE", "start_date": "2026-01-01"})).json()
    url = f"/api/plans/{plan['id']}"
    account_type = "traditional_ira" if kind == "qcd" else "checking"
    account = (await client.post("/api/accounts", json={"name": "Gift source", "account_type": account_type, "balance": 100000})).json()
    gift = {"name": "Gift", "entity_type": kind, "annual_amount": 1200}
    created = await client.post(url + "/charities", json=gift)
    assert created.status_code == 201
    db_result = await client.post(url + "/simulate")
    blob = {"plan_id": plan["id"], "birth_year": birth, "start_year": 2026,
            "accounts": {account["id"]: {"name": "Gift source", "account_type": account_type, "balance": 100000}},
            "charity_entities": [gift | {"id": created.json()["id"]}]}
    stateless = await client.post("/api/simulate/stateless", json=blob)
    for response in (db_result, stateless):
        assert response.status_code == 200, response.text
        row = response.json()["yearly_snapshots"][0]
        cf = row["cash_flow"]
        incoming = cf["gross_income"] + sum(d["amount"] for d in cf["drawdowns"]) + max(0, cf["tax_delta"])
        outgoing = cf["tax_withheld"] + max(0, -cf["tax_delta"]) + sum(e["amount"] for e in cf["expenses"]) + sum(c["amount"] for c in cf["contributions"])
        assert incoming == pytest.approx(outgoing, abs=.01)
        assert sum(e["amount"] for e in cf["expenses"]) == 1200
        if birth == 1950:
            assert cf["drawdowns"] == []  # QCD funded by the already-reported RMD
        else:
            assert cf["drawdowns"] == [{"name": "Gift source", "amount": 1200, "category": None,
                "account_id": account["id"], "account_name": "Gift source", "source": None,
                "priority_rank": None, "requested_amount": None, "limited_by": [], "funding_reasons": []}]
