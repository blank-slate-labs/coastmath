"""Withdraw-if-short and reduce-employer-contribution options over the API."""

from __future__ import annotations

import pytest

from app.schemas.cash_flow_priority import CashFlowPriorityCreate
from coastmath.schemas.plan_data_request import PriorityRequest
from tests.api_support import save_priorities

pytestmark = pytest.mark.anyio


async def _plan_with(client, *types: str):
    plan = (await client.post("/api/plans", json={"name": "Funding options", "birth_year": 1980, "plan_type": "NOW"})).json()
    accounts = {}
    for account_type in types:
        r = await client.post("/api/accounts", json={"name": account_type, "account_type": account_type, "balance": 0})
        assert r.status_code == 201, r.text
        accounts[account_type] = r.json()
    wage = await client.post(f"/api/plans/{plan['id']}/incomes", json={
        "name": "Salary", "annual_amount": 60_000, "is_earned_income": True})
    assert wage.status_code == 201, wage.text
    return plan, accounts, wage.json()


@pytest.mark.parametrize("priority_type", ["roth_conversion", "transfer", "gain_harvest"])
def test_withdraw_if_short_is_rejected_for_source_funded_types(priority_type):
    extra = {"conversion_mode": "fill_bracket", "bracket_ceiling_rate": 0.15} if priority_type == "gain_harvest" else {}
    for model in (CashFlowPriorityCreate, PriorityRequest):
        with pytest.raises(ValueError, match="Withdraw if surplus is short applies only"):
            model(priority_rank=1, priority_type=priority_type, target_account_id=None,
                  source_account_id="00000000-0000-4000-8000-000000000001", withdraw_if_short=True, **extra)


@pytest.mark.parametrize("priority_type", ["contribution", "income_percent", "pre_tax_contribution",
                                           "after_tax_401k", "debt_payment", None])
def test_withdraw_if_short_is_accepted_for_contribution_payroll_and_debt_rules(priority_type):
    extra = {"source_income_id": "00000000-0000-4000-8000-000000000002"} \
        if priority_type in ("income_percent", "after_tax_401k") else {}
    if priority_type == "debt_payment":
        extra = {"target_liability_id": "00000000-0000-4000-8000-000000000003"}
    rule = CashFlowPriorityCreate(priority_rank=1, priority_type=priority_type, withdraw_if_short=True, **extra)
    assert rule.withdraw_if_short


def test_reduce_employer_contribution_rules():
    base = {"priority_rank": 1, "priority_type": "income_percent",
            "source_income_id": "00000000-0000-4000-8000-000000000002"}
    assert CashFlowPriorityCreate(**base, reduce_employer_contribution=True).reduce_employer_contribution
    with pytest.raises(ValueError, match="funded with income"):
        CashFlowPriorityCreate(**base, reduce_employer_contribution=True, withdraw_if_short=True)
    with pytest.raises(ValueError, match="only to income_percent"):
        CashFlowPriorityCreate(priority_rank=1, priority_type="contribution", reduce_employer_contribution=True)


def test_request_dump_omits_unset_options():
    """Existing request bodies stay byte-identical."""
    rule = PriorityRequest(priority_rank=1, priority_type="contribution", target_account_id="a")
    dumped = rule.model_dump()
    assert "withdraw_if_short" not in dumped and "reduce_employer_contribution" not in dumped
    assert PriorityRequest(priority_rank=1, target_account_id="a", withdraw_if_short=True).model_dump()["withdraw_if_short"]


async def test_options_round_trip_simulate_and_duplicate(client):
    plan, accounts, wage = await _plan_with(client, "traditional_401k", "taxable_brokerage", "savings")
    payroll = {"priority_rank": 1, "priority_type": "income_percent", "target_account_id": accounts["traditional_401k"]["id"],
               "source_income_id": wage["id"], "employee_rate": 6, "employer_match_rate": 3,
               "reduce_employer_contribution": True}
    goal = {"priority_rank": 2, "priority_type": "contribution", "target_account_id": accounts["taxable_brokerage"]["id"],
            "allocation_mode": "amount", "allocation_value": 2000, "withdraw_if_short": True}
    rest = {"priority_rank": 3, "priority_type": "contribution", "target_account_id": accounts["savings"]["id"]}
    r = await save_priorities(client, plan["id"], [payroll, goal, rest])
    assert r.status_code == 200, r.text
    listed = (await client.get(f"/api/plans/{plan['id']}/priorities")).json()["items"]
    assert [(i["withdraw_if_short"], i["reduce_employer_contribution"]) for i in listed] == [
        (False, True), (True, False), (False, False)]
    sim = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert sim.status_code == 200, sim.text
    first = sim.json()["yearly_snapshots"][0]
    assert first["rule_funding_shortfall"] == 0
    flows = {c["priority_rank"]: c for c in first["cash_flow"]["contributions"] if c.get("source") == "priority"}
    assert flows[2]["amount"] > 0

    copy = await client.post(f"/api/plans/{plan['id']}/duplicate")
    assert copy.status_code == 201, copy.text
    copied = (await client.get(f"/api/plans/{copy.json()['id']}/priorities")).json()["items"]
    assert [(i["withdraw_if_short"], i["reduce_employer_contribution"]) for i in copied] == [
        (False, True), (True, False), (False, False)]


async def test_disallowed_type_uses_the_error_envelope(client):
    plan, accounts, _ = await _plan_with(client, "traditional_ira", "roth_ira")
    rule = {"priority_rank": 1, "priority_type": "roth_conversion", "source_account_id": accounts["traditional_ira"]["id"],
            "target_account_id": accounts["roth_ira"]["id"], "max_annual_amount": 1000, "withdraw_if_short": True}
    r = await save_priorities(client, plan["id"], [rule])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Withdraw if surplus is short applies only" in str(r.json())


async def test_stateless_request_matches_the_engine(client):
    body = {
        "plan_id": "00000000-0000-0000-0000-0000000000af", "birth_year": 1980, "start_year": 2026,
        "first_year_fraction": 1.0, "life_expectancy": 50, "state_code": "TX",
        "assumptions": {"inflation_rate": 0, "stock_growth_rate": 0, "bond_return_rate": 0},
        "tax_settings": {"cash_flow_frequency": "annual"},
        "accounts": {"sav": {"balance": 5_000, "account_type": "savings", "name": "Savings"},
                     "brok": {"balance": 0, "account_type": "taxable_brokerage", "name": "Brokerage", "cost_basis": 0}},
        "drawdown_order": [{"rank": 1, "source_account_id": "sav"}],
        "priorities": [{"priority_rank": 1, "priority_type": "contribution", "target_account_id": "brok",
                        "allocation_mode": "amount", "allocation_value": 3_000, "withdraw_if_short": True}],
    }
    r = await client.post("/api/simulate/stateless", json=body)
    assert r.status_code == 200, r.text
    first = r.json()["yearly_snapshots"][0]
    assert first["accounts"]["brok"] == pytest.approx(3_000)
    assert first["accounts"]["sav"] == pytest.approx(2_000)
    assert first["rule_funding_shortfall"] == 0
    body["priorities"][0]["withdraw_if_short"] = False
    plain = (await client.post("/api/simulate/stateless", json=body)).json()["yearly_snapshots"][0]
    assert plain["accounts"]["brok"] == 0
