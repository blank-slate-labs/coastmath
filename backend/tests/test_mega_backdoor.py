"""Mega backdoor Roth: after-tax 401(k) money converted at once to a Roth 401(k).

Section 415(c) annual additions (IRC 415(c)(1)) cover regular deferrals,
employer money and after-tax contributions; catch-up deferrals are excluded
(IRC 414(v)(3)(A)). https://www.irs.gov/pub/irs-drop/n-25-67.pdf
"""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.cash_flow_priority import CashFlowPriorityCreate
from coastmath.engine.roth import ledger
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import (
    allocate_payroll_contributions,
    allocate_surplus,
    contribution_room,
)

TOTAL = 72_000
DEFERRAL = 24_500


def state(**accounts):
    return SimState(2026, accounts={
        "trad": AccountInfo(0, "traditional_401k"),
        "roth": AccountInfo(0, "roth_401k", name="Roth 401(k)"),
        "cash": AccountInfo(0, "checking"),
        **accounts,
    })


def deferral(rank, target="trad", employee=0.0, employer=0.0):
    return PriorityData(rank, target, priority_type="income_percent", source_income_id="salary",
                        employee_rate=employee, employer_match_rate=employer)


def after_tax(rank, maximum=None, **kwargs):
    return PriorityData(rank, "roth", priority_type="after_tax_401k", source_income_id="salary",
                        max_annual_amount=maximum, **kwargs)


def run(rules, s, salary=300_000, age=40, **kwargs):
    return allocate_payroll_contributions(rules, {"salary": salary}, s, age, **kwargs)


def test_after_tax_fills_415c_room_left_by_deferrals_and_match():
    s = state()
    out = run([deferral(1, employee=DEFERRAL / 300_000, employer=10_000 / 300_000), after_tax(2)], s)
    mega = out[-1]
    assert mega.employee_amount == pytest.approx(TOTAL - DEFERRAL - 10_000)
    assert sum(c.employee_amount + c.employer_amount for c in out) == pytest.approx(TOTAL)
    assert s.ytd_after_tax_contributions == {"roth": pytest.approx(37_500)}
    # After-tax money does not use the 402(g) deferral limit.
    assert s.ytd_contributions == {"trad": pytest.approx(DEFERRAL)}
    assert mega.limited_by == ["contribution eligibility / annual limit"]
    assert mega.funding_reasons == []


def test_room_is_capped_at_compensation_and_explained():
    s = state()
    s.compensation_by_owner = {"self": 50_000}
    out = run([deferral(1, employee=DEFERRAL / 300_000), after_tax(2)], s)
    assert out[-1].employee_amount == pytest.approx(50_000 - DEFERRAL)
    s = state()
    s.compensation_by_owner = {"self": 20_000}
    out = run([deferral(1, employee=20_000 / 300_000), after_tax(2)], s)
    assert out[-1].employee_amount == 0
    assert out[-1].funding_reasons == ["compensation"]


def test_catchup_deferrals_are_excluded_from_415c():
    s = state()
    out = run([deferral(1, employee=1.0), after_tax(2)], s, age=50)
    assert out[0].employee_amount == pytest.approx(DEFERRAL + 8_000)
    assert out[-1].employee_amount == pytest.approx(TOTAL - DEFERRAL)


def test_opening_employer_history_and_list_order_share_the_total():
    s = state()
    s.ytd_employer_contributions = {"trad": 30_000}
    out = run([after_tax(1), deferral(2, employee=1.0, employer=1.0)], s)
    assert out[0].employee_amount == pytest.approx(TOTAL - 30_000)
    # Later rules see the after-tax money: no more room for deferrals or match.
    assert len(out) == 1
    assert contribution_room("trad", s, 40) == 0
    assert allocate_surplus(5_000, [PriorityData(3, "roth"), PriorityData(4, "cash")], s, 40) == {"cash": 5_000}


def test_annual_maximum_prorates_and_pay_limits_the_amount():
    s = state()
    out = run([after_tax(1, maximum=20_000)], s, contribution_fraction=0.5)
    assert out[0].employee_amount == pytest.approx(10_000)
    assert "annual maximum" in out[0].limited_by
    s = state()
    out = run([deferral(1, employee=0.5), after_tax(2)], s, salary=40_000)
    assert out[-1].employee_amount == pytest.approx(20_000)


@pytest.mark.parametrize("kind, expected", [
    ("limit", ["contribution_limit"]),
    ("cap", ["annual_maximum"]),
    ("inactive", ["inactive_rule"]),
])
def test_unfunded_rule_reports_why(kind, expected):
    s = state()
    rule = after_tax(1, maximum=0 if kind == "cap" else None,
                     start_milestone_id="retire" if kind == "inactive" else None)
    if kind == "limit":
        s.ytd_employer_contributions = {"trad": TOTAL}
    out = run([rule], s)
    assert out[0].employee_amount == 0
    assert out[0].funding_reasons == expected
    assert s.accounts["roth"].balance == 0


def test_rule_needs_owner_w2_wages_and_a_roth_401k():
    s = state(spouse_roth=AccountInfo(0, "roth_401k", owner="spouse"))
    rules = [PriorityData(1, "trad", priority_type="after_tax_401k", source_income_id="salary"),
             PriorityData(2, "spouse_roth", priority_type="after_tax_401k", source_income_id="salary")]
    assert run(rules, s, income_owners={"salary": "self"}) == []
    assert run([after_tax(1)], state(), w2_income_ids=set()) == []
    assert run([after_tax(1)], state(), salary=0) == []


def test_contribution_is_an_untaxed_in_plan_rollover_in_the_roth_ledger():
    s = state()
    run([after_tax(1, maximum=30_000)], s)
    group = ledger(s).groups[ledger(s).account_groups["roth"]]
    assert group["conversions"] == [{"year": 2026, "taxable_basis": 0.0, "nontaxable_basis": 30_000}]
    assert s.roth_conversions_this_year == 0
    # A full distribution of the converted dollars returns basis tax-free.
    income, penalty = ledger(s).distribution("roth", 30_000, 30_000, "roth_401k", True, False)
    assert (income, penalty) == (0.0, 0.0)


def _plan(priorities):
    return PlanData(
        str(uuid.uuid4()), 1986, "single", 50, 2026,
        accounts={"trad": AccountInfo(0, "traditional_401k", name="401(k)"),
                  "roth": AccountInfo(0, "roth_401k", name="Roth 401(k)"),
                  "cash": AccountInfo(0, "checking", name="Cash")},
        income_streams=[IncomeData("salary", "Salary", 250_000, growth_rate=0)],
        priorities=priorities,
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                                   stock_dividend_yield=0, cash_yield_rate=0),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0.2},
    )


def test_simulated_after_tax_dollars_are_not_deducted_or_payroll_taxed():
    base = [deferral(1, employee=0.1, employer=0.04)]
    without = run_simulation(_plan(base)).yearly_snapshots[0]
    with_mega = run_simulation(_plan([*base, after_tax(2)])).yearly_snapshots[0]
    expected = TOTAL - DEFERRAL - 10_000
    assert with_mega.accounts["roth"] == pytest.approx(expected)
    assert with_mega.federal_tax == pytest.approx(without.federal_tax)
    assert with_mega.fica_tax == pytest.approx(without.fica_tax)
    assert with_mega.taxes == pytest.approx(without.taxes)
    # The dollars come out of cash, not from nowhere.
    assert with_mega.accounts["cash"] == pytest.approx(without.accounts["cash"] - expected)
    row = next(c for c in with_mega.cash_flow.contributions if c.account_id == "roth")
    assert (row.source, row.category, row.priority_rank) == ("payroll", "aftertax", 2)
    assert with_mega.cash_flow.payroll_deductions == pytest.approx(without.cash_flow.payroll_deductions)


def test_simulated_unfunded_rule_surfaces_its_reason():
    plan = _plan([deferral(1, employee=0.1, employer=0.2), after_tax(2)])
    first = run_simulation(plan).yearly_snapshots[0]
    row = next(c for c in first.cash_flow.contributions if c.account_id == "roth")
    assert row.amount == 0
    assert row.funding_reasons == ["contribution_limit"]


def test_schema_requires_wages_and_accepts_the_type():
    rule = CashFlowPriorityCreate(priority_rank=1, priority_type="after_tax_401k",
                                  target_account_id=uuid.uuid4(), source_income_id=uuid.uuid4())
    assert rule.priority_type == "after_tax_401k"
    with pytest.raises(ValidationError, match="source_income_id"):
        CashFlowPriorityCreate(priority_rank=1, priority_type="after_tax_401k", target_account_id=uuid.uuid4())
    with pytest.raises(ValidationError):
        CashFlowPriorityCreate(priority_rank=1, priority_type="after_tax_401k", source_income_id=uuid.uuid4(),
                               allocation_mode="amount", allocation_value=1000)


@pytest.mark.anyio
async def test_router_accepts_owner_wages_into_a_roth_401k_only(client):
    plan = (await client.post("/api/plans", json={"name": "Mega backdoor", "birth_year": 1986})).json()
    roth = (await client.post("/api/accounts", json={"name": "Roth 401k", "account_type": "roth_401k", "balance": 0})).json()
    trad = (await client.post("/api/accounts", json={"name": "401k", "account_type": "traditional_401k", "balance": 0})).json()
    wages = (await client.post(f"/api/plans/{plan['id']}/incomes", json={"name": "Salary", "annual_amount": 250000})).json()
    business = (await client.post(f"/api/plans/{plan['id']}/incomes", json={
        "name": "Consulting", "annual_amount": 50000, "is_self_employed": True})).json()
    url = f"/api/plans/{plan['id']}/priorities"

    async def put(target, income):
        revision = (await client.get(url)).json()["revision"]
        return await client.put(url, json={"expected_revision": revision, "items": [{
            "priority_rank": 1, "priority_type": "after_tax_401k",
            "target_account_id": target["id"], "source_income_id": income["id"]}]})

    assert (await put(trad, wages)).status_code == 422
    assert (await put(roth, business)).status_code == 422
    saved = await put(roth, wages)
    assert saved.status_code == 200, saved.text
    assert saved.json()["items"][0]["priority_type"] == "after_tax_401k"
    simulated = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["yearly_snapshots"][0]["accounts"][roth["id"]] > 0
