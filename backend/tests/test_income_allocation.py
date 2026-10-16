"""Allocation contracts, real funding limits, cash conservation, and persistence."""

import uuid

import pytest
from pydantic import ValidationError

from app.models.cash_flow_priority import CashFlowPriority
from app.schemas.cash_flow_priority import CashFlowPriorityCreate
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import (
    allocate_payroll_contributions,
    allocate_surplus,
    contribution_room,
)
from coastmath.schemas.plan_data_request import (
    PlanDataRequest,
    PriorityRequest,
    request_to_engine_data,
)


def state():
    return SimState(
        2026,
        accounts={
            "a": AccountInfo(0, "taxable_brokerage", cost_basis=0, name="Vanguard"),
            "b": AccountInfo(0, "taxable_brokerage", cost_basis=0, name="Fidelity"),
            "c": AccountInfo(0, "checking", name="Chase"),
        },
    )


def rule(rank, target, mode="remaining", value=None, **kwargs):
    return PriorityData(
        rank, target, allocation_mode=mode, allocation_value=value, **kwargs
    )


def test_percentages_use_original_surplus_and_keep_same_type_accounts_separate():
    s = state()
    assert allocate_surplus(
        10_000, [rule(1, "a", "percentage", 60), rule(2, "b", "percentage", 40)], s
    ) == {"a": 6000, "b": 4000}
    assert [
        (f.account_id, f.account_name, f.priority_rank) for f in s.allocation_flows
    ] == [("a", "Vanguard", 1), ("b", "Fidelity", 2)]


def test_amount_percentage_remaining_caps_and_target_balance():
    s = state()
    s.accounts["a"].balance = 9000
    rules = [
        rule(1, "a", "amount", 4000, target_balance=10_000),
        rule(2, "b", "percentage", 60, max_annual_amount=2500),
        rule(3, "c"),
    ]
    assert allocate_surplus(10_000, rules, s) == {"a": 1000, "b": 2500, "c": 6500}
    assert s.allocation_flows[0].limited_by == ["target balance"]
    assert s.allocation_flows[1].limited_by == ["annual maximum"]
    assert sum(f.amount for f in s.allocation_flows) == 10_000


def test_excess_requests_are_ordered_not_normalized_and_missing_account_does_not_consume_cash():
    s = state()
    assert allocate_surplus(
        10_000,
        [
            rule(1, "missing"),
            rule(2, "a", "percentage", 80),
            rule(3, "b", "percentage", 80),
        ],
        s,
    ) == {"a": 8000, "b": 2000}
    assert "available surplus" in s.allocation_flows[-1].limited_by


def test_partial_year_prorates_dollars_but_not_reserve_or_legal_maximum():
    s = state()
    rules = [
        rule(1, "a", "amount", 12_000, max_annual_amount=5000),
        rule(2, "c", target_balance=5000),
    ]
    assert allocate_surplus(10_000, rules, s, target_balance_fraction=0.25) == {
        "a": 3000,
        "c": 5000,
    }


@pytest.mark.parametrize("amount", [0, -100])
def test_no_surplus_never_withdraws(amount):
    s = state()
    assert allocate_surplus(amount, [rule(1, "a", "amount", 1000)], s) == {}
    assert sum(a.balance for a in s.accounts.values()) == 0


def test_payroll_and_surplus_share_401k_limit_and_ytd():
    s = state()
    s.accounts.update(
        {
            "trad": AccountInfo(0, "traditional_401k"),
            "roth": AccountInfo(0, "roth_401k"),
        }
    )
    s.ytd_contributions = {"trad": 20_000}
    allocate_payroll_contributions(
        [
            PriorityData(
                1,
                "trad",
                priority_type="income_percent",
                source_income_id="salary",
                employee_rate=0.02,
            )
        ],
        {"salary": 100_000},
        s,
        40,
    )
    result = allocate_surplus(10_000, [rule(2, "roth"), rule(3, "c")], s, 40)
    assert result == {"roth": 2500, "c": 7500}
    assert s.ytd_contributions["trad"] + s.ytd_contributions["roth"] == 24_500


@pytest.mark.parametrize(
    "age,expected", [(49, 24500), (50, 32500), (60, 35750), (63, 35750), (64, 32500)]
)
def test_catchup_uses_account_owners_age(age, expected):
    s = state()
    s.accounts["r"] = AccountInfo(0, "roth_401k", owner="spouse")
    s.owner_ages = {"self": 30, "spouse": age}
    assert contribution_room("r", s, 30) == expected


def test_high_earner_catchup_requires_roth_and_preserves_shared_room():
    s = state()
    s.accounts.update(
        {"t": AccountInfo(0, "traditional_401k"), "r": AccountInfo(0, "roth_401k")}
    )
    s.roth_catchup_owners = {"self"}
    result = allocate_surplus(50_000, [rule(1, "t"), rule(2, "r"), rule(3, "c")], s, 60)
    assert result == {"t": 24500, "r": 11250, "c": 14250}


def test_spousal_ira_limit_shared_with_compensation_and_roth_phaseout():
    s = state()
    s.accounts.update(
        {
            "t": AccountInfo(0, "traditional_ira"),
            "r": AccountInfo(0, "roth_ira"),
            "sp": AccountInfo(0, "roth_ira", owner="spouse"),
        }
    )
    s.compensation_by_owner = {"self": 10_000}
    s.ytd_contributions = {"t": 4000}
    assert allocate_surplus(
        20_000,
        [rule(1, "r"), rule(2, "sp"), rule(3, "c")],
        s,
        40,
        "married_filing_jointly",
        100_000,
    ) == {"r": 3500, "sp": 2500, "c": 14000}
    s = state()
    s.accounts["r"] = AccountInfo(0, "roth_ira")
    assert allocate_surplus(
        10_000, [rule(1, "r"), rule(2, "c")], s, 40, "single", 200_000
    ) == {"c": 10000}
    assert s.allocation_flows[0].amount == 0
    assert s.allocation_flows[0].limited_by == [
        "contribution eligibility / annual limit"
    ]


def test_payroll_cannot_reuse_same_income_or_another_owners_pay():
    s = state()
    s.accounts.update(
        {
            "t": AccountInfo(0, "traditional_401k"),
            "sp": AccountInfo(0, "roth_401k", owner="spouse"),
        }
    )
    rules = [
        PriorityData(
            i,
            target,
            priority_type="income_percent",
            source_income_id="salary",
            employee_rate=1,
        )
        for i, target in enumerate(["sp", "t", "t"], 1)
    ]
    out = allocate_payroll_contributions(
        rules,
        {"salary": 10_000, "other": 100_000},
        s,
        40,
        income_owners={"salary": "self", "other": "spouse"},
    )
    assert sum(c.employee_amount for c in out) == 10_000
    assert s.accounts["sp"].balance == 0


def test_employer_funding_cannot_exceed_combined_limit_in_either_order():
    for rates in [(1, 0), (0, 1)]:
        s = state()
        s.accounts["t"] = AccountInfo(0, "traditional_401k")
        rules = [
            PriorityData(
                i,
                "t",
                priority_type="income_percent",
                source_income_id="salary",
                employee_rate=rate,
                employer_match_rate=1 - rate,
            )
            for i, rate in enumerate(rates, 1)
        ]
        out = allocate_payroll_contributions(rules, {"salary": 200_000}, s, 40)
        assert sum(c.employee_amount + c.employer_amount for c in out) == 72000


@pytest.mark.parametrize("kind", ["traditional_ira", "roth_ira"])
def test_inherited_and_joint_retirement_accounts_cannot_receive_contributions(kind):
    s = state()
    s.accounts["r"] = AccountInfo(0, kind, inherited_year=2025)
    assert contribution_room("r", s, 40) == 0
    s.accounts["r"] = AccountInfo(0, kind, owner="joint")
    assert contribution_room("r", s, 40) == 0


@pytest.mark.parametrize("schema", [CashFlowPriorityCreate, PriorityRequest])
@pytest.mark.parametrize(
    "fields",
    [
        {"allocation_mode": "percentage"},
        {"allocation_mode": "percentage", "allocation_value": 101},
        {"allocation_mode": "amount", "allocation_value": -1},
        {"allocation_mode": "amount", "allocation_value": float("inf")},
        {"allocation_mode": "remaining", "allocation_value": 50},
        {"max_annual_amount": -1},
    ],
)
def test_invalid_contract_is_rejected(schema, fields):
    with pytest.raises(ValidationError):
        schema(priority_rank=1, **fields)


def test_named_default_sink_warning_and_no_cash_leakage():
    p = PlanData(
        str(uuid.uuid4()),
        1990,
        "single",
        37,
        2026,
        accounts=state().accounts,
        income_streams=[IncomeData("salary", "Salary", 100_000)],
        assumptions=AssumptionData(
            inflation_rate=0,
            stock_growth_rate=0,
            bond_return_rate=0,
            stock_dividend_yield=0,
            cash_yield_rate=0,
        ),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0},
    )
    out = run_simulation(p)
    first = out.yearly_snapshots[0]
    assert first.cash_flow.contributions[0].account_name == "Chase"
    assert first.cash_flow.contributions[0].source == "default_sink"
    assert first.accounts["c"] == first.net_cash_flow
    assert any("Chase" in w for w in out.metadata.warnings)
    p.priorities = [rule(1, "a", "percentage", 60), rule(2, "b", "percentage", 40)]
    first = run_simulation(p).yearly_snapshots[0]
    assert first.accounts["a"] == first.net_cash_flow * 0.6
    assert first.accounts["b"] == first.net_cash_flow * 0.4
    assert sum(c.amount for c in first.cash_flow.contributions) == pytest.approx(
        first.net_cash_flow
    )


@pytest.mark.anyio
async def test_api_persists_modes_and_rejects_bad_update_atomically(client):
    p = (
        await client.post(
            "/api/plans", json={"name": "Allocation test", "birth_year": 1990}
        )
    ).json()
    a = (
        await client.post(
            "/api/accounts",
            json={
                "name": "Named destination",
                "account_type": "taxable_brokerage",
                "balance": 0,
            },
        )
    ).json()
    url = f"/api/plans/{p['id']}/priorities"
    items = [
        {
            "priority_rank": 1,
            "target_account_id": a["id"],
            "allocation_mode": "percentage",
            "allocation_value": 60,
            "max_annual_amount": 5000,
        },
        {
            "priority_rank": 2,
            "target_account_id": a["id"],
            "allocation_mode": "amount",
            "allocation_value": 1200,
        },
    ]
    response = await client.put(url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": items})
    assert response.status_code == 200, response.text
    saved = (await client.get(url)).json()
    assert [(p["allocation_mode"], p["allocation_value"]) for p in saved["items"]] == [
        ("percentage", 60),
        ("amount", 1200),
    ]
    assert (
        await client.put(url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": [{**items[0], "allocation_value": 200}]})
    ).status_code == 422
    assert (await client.get(url)).json() == saved
    assert (
        await client.put(
            url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": [{**items[0], "target_account_id": str(uuid.uuid4())}]}
        )
    ).status_code == 422
    assert (await client.get(url)).json() == saved


@pytest.mark.anyio
async def test_api_enforces_payroll_source_and_preserves_saved_rules(client):
    p = (
        await client.post(
            "/api/plans", json={"name": "Payroll test", "birth_year": 1990}
        )
    ).json()
    a = (
        await client.post(
            "/api/accounts",
            json={
                "name": "Work plan",
                "account_type": "traditional_401k",
                "balance": 0,
            },
        )
    ).json()
    income = (
        await client.post(
            f"/api/plans/{p['id']}/incomes",
            json={"name": "Salary", "annual_amount": 100000},
        )
    ).json()
    url = f"/api/plans/{p['id']}/priorities"
    valid = {
        "priority_rank": 1,
        "priority_type": "income_percent",
        "source_income_id": income["id"],
        "target_account_id": a["id"],
        "employee_rate": 100,
    }
    result = await client.put(url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": [valid]})
    assert result.status_code == 200, result.text
    saved = result.json()
    for invalid in [
        {**valid, "priority_type": "contribution"},
        {**valid, "source_income_id": None},
    ]:
        assert (await client.put(url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": [invalid]})).status_code == 422
        assert (await client.get(url)).json() == saved


def test_hsa_catchup_does_not_inflate_and_employer_funding_shares_limit():
    s = state()
    s.accounts["hsa"] = AccountInfo(0, "hsa")
    s.coverage_inflation_factor = 2
    assert contribution_room("hsa", s, 55) == 9800
    result = allocate_payroll_contributions(
        [
            PriorityData(
                1,
                "hsa",
                priority_type="income_percent",
                source_income_id="salary",
                employee_rate=1,
                employer_match_rate=1,
            )
        ],
        {"salary": 100000},
        s,
        55,
    )
    assert sum(c.employee_amount + c.employer_amount for c in result) == 9800


def test_stateless_converter_preserves_modes_and_account_names():
    request = PlanDataRequest(
        plan_id=uuid.uuid4(),
        birth_year=1990,
        filing_status="single",
        life_expectancy=90,
        start_year=2026,
        accounts={
            "a": {"balance": 0, "account_type": "checking", "name": "Named cash"}
        },
        priorities=[
            {
                "priority_rank": 1,
                "target_account_id": "a",
                "allocation_mode": "percentage",
                "allocation_value": 75,
            }
        ],
    )
    data = request_to_engine_data(request)
    assert data.accounts["a"].name == "Named cash"
    assert data.priorities[0].allocation_mode == "percentage"
    assert data.priorities[0].allocation_value == 75


def test_exhausted_and_milestone_disabled_rules_are_explained():
    s = state()
    result = allocate_surplus(
        100,
        [
            rule(1, "a", start_milestone_id="retire"),
            rule(2, "b"),
            rule(3, "c", "amount", 1000),
        ],
        s,
    )
    assert result == {"b": 100}
    assert s.allocation_flows[-1].amount == 0
    assert s.allocation_flows[-1].limited_by == ["available surplus"]


def test_combined_employer_and_employee_limit_cannot_exceed_compensation():
    s = state()
    s.accounts["t"] = AccountInfo(0, "traditional_401k")
    s.compensation_by_owner = {"self": 10000}
    rules = [
        PriorityData(
            1,
            "t",
            priority_type="income_percent",
            source_income_id="salary",
            employer_match_rate=1,
        ),
        PriorityData(
            2,
            "t",
            priority_type="income_percent",
            source_income_id="salary",
            employee_rate=1,
        ),
    ]
    result = allocate_payroll_contributions(rules, {"salary": 10000}, s, 40)
    assert sum(c.employee_amount + c.employer_amount for c in result) == 10000


def test_opening_employer_history_reduces_room_without_adding_cash():
    p = PlanData(
        str(uuid.uuid4()),
        1990,
        "single",
        37,
        2026,
        accounts={
            "work": AccountInfo(0, "traditional_401k"),
            "cash": AccountInfo(0, "checking"),
        },
        income_streams=[IncomeData("salary", "Salary", 100000)],
        priorities=[
            PriorityData(
                1,
                "work",
                priority_type="income_percent",
                source_income_id="salary",
                employee_rate=1,
            )
        ],
        assumptions=AssumptionData(
            inflation_rate=0,
            stock_growth_rate=0,
            bond_return_rate=0,
            stock_dividend_yield=0,
            cash_yield_rate=0,
        ),
        tax_settings={
            "mode": "flat",
            "ordinary_income_tax_rate": 0,
            "year_to_date": {
                "tax_year": 2026,
                "employer_contributions_by_account": {"work": 60000},
            },
        },
    )
    first = run_simulation(p).yearly_snapshots[0]
    assert first.accounts["work"] == 12000
    assert sum(first.accounts.values()) == 100000


def test_remaining_payroll_room_is_not_prorated_but_fixed_amount_is():
    for maximum, expected in [(None, 24500), (12000, 3000)]:
        s = state()
        s.accounts["work"] = AccountInfo(0, "traditional_401k")
        result = allocate_payroll_contributions(
            [
                PriorityData(
                    1,
                    "work",
                    priority_type="pre_tax_contribution",
                    source_income_id="salary",
                    max_annual_amount=maximum,
                )
            ],
            {"salary": 50000},
            s,
            40,
            contribution_fraction=0.25,
        )
        assert result[0].employee_amount == expected


@pytest.mark.parametrize("payroll_type", ["income_percent", "pre_tax_contribution"])
@pytest.mark.parametrize("bound", ["start", "end"])
def test_payroll_rules_honor_milestone_window(payroll_type, bound):
    window = {f"{bound}_milestone_id": "switch"}
    rules = [PriorityData(1, "trad", priority_type=payroll_type, source_income_id="salary",
                          employee_rate=0.1, employer_match_rate=0.04, max_annual_amount=10_000, **window)]
    plan = PlanData(
        str(uuid.uuid4()), 1986, "single", 44, 2026,
        accounts={"trad": AccountInfo(0, "traditional_401k", name="401(k)"),
                  "cash": AccountInfo(0, "checking", name="Cash")},
        income_streams=[IncomeData("salary", "Salary", 100_000, growth_rate=0)],
        milestones=[MilestoneData("switch", "Switch", "date", trigger_date="2028-01-01")],
        priorities=rules,
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                                   stock_dividend_yield=0, cash_yield_rate=0),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0.2},
    )
    funded = {}
    for snap in run_simulation(plan).yearly_snapshots:
        rows = [c for c in snap.cash_flow.contributions if c.account_id == "trad" and c.source in ("payroll", "employer")]
        funded[snap.year] = sum(c.amount for c in rows)
    before, after = (0.0, 10_000.0) if bound == "start" else (10_000.0, 0.0)
    employer = 4_000.0 if payroll_type == "income_percent" else 0.0
    assert funded[2026] == funded[2027] == pytest.approx(before + (employer if before else 0.0))
    assert funded[2028] == funded[2029] == pytest.approx(after + (employer if after else 0.0))


@pytest.mark.anyio
async def test_legacy_401k_allows_unrelated_edits_but_not_changed_or_duplicate_funding(client, db_session):
    plan = (await client.post("/api/plans", json={"name": "Legacy allocation QA", "birth_year": 1990})).json()
    work = (await client.post("/api/accounts", json={"name": "Existing 401k", "account_type": "traditional_401k", "balance": 10000})).json()
    cash = (await client.post("/api/accounts", json={"name": "Cash", "account_type": "savings", "balance": 0})).json()
    # This stored rule predates the requirement to use payroll for new rules.
    db_session.add(CashFlowPriority(plan_id=uuid.UUID(plan["id"]), priority_rank=1, target_account_id=uuid.UUID(work["id"]), max_annual_amount=23500))
    db_session.commit()
    url = f"/api/plans/{plan['id']}/priorities"
    original = (await client.get(url)).json()["items"][0]
    legacy = {k: v for k, v in original.items() if k not in {"id", "plan_id"}}
    legacy["priority_rank"] = 2
    other = {"priority_rank": 1, "target_account_id": cash["id"], "allocation_mode": "percentage", "allocation_value": 30}
    result = await client.put(url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": [other, legacy]})
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["items"][0]["allocation_value"] == 30
    assert saved["items"][1]["max_annual_amount"] == 23500
    for invalid in (
        [other, {**legacy, "max_annual_amount": 24500}],
        [other, legacy, {**legacy, "priority_rank": 3}],
    ):
        rejected = await client.put(url, json={"expected_revision": (await client.get(url)).json()["revision"], "items": invalid})
        assert rejected.status_code == 422, rejected.text
        assert (await client.get(url)).json() == saved

    second_plan = (await client.post("/api/plans", json={"name": "Other plan", "birth_year": 1990})).json()
    assert (await client.put(f"/api/plans/{second_plan['id']}/priorities", json={"expected_revision": (await client.get(f"/api/plans/{second_plan['id']}/priorities")).json()["revision"], "items": [legacy]})).status_code == 422


@pytest.mark.parametrize("kind, expected", [
    ("no_surplus", "insufficient_surplus"),
    ("earlier", "earlier_rules"),
    ("owner", "ownership"),
    ("income", "income_eligibility"),
    ("compensation", "compensation"),
    ("limit", "contribution_limit"),
    ("cap", "annual_maximum"),
    ("target", "target_balance"),
    ("request", "zero_request"),
    ("inactive", "inactive_rule"),
])
def test_zero_funding_reasons_are_captured_at_execution(kind, expected):
    s = state()
    s.accounts["ira"] = AccountInfo(0, "roth_ira", name="IRA")
    s.accounts["cash"] = AccountInfo(0, "savings", name="Cash")
    p = PriorityData(2, "ira")
    priorities = [p]
    surplus, magi = 10000, 50000
    if kind == "no_surplus":
        surplus = 0
    elif kind == "earlier":
        priorities.insert(0, PriorityData(1, "cash"))
    elif kind == "owner":
        s.accounts["ira"].owner = "joint"
    elif kind == "income":
        magi = 1000000
    elif kind == "compensation":
        s.compensation_by_owner = {"self": 0}
    elif kind == "limit":
        s.ytd_contributions["ira"] = 7500
    elif kind == "cap":
        p.max_annual_amount = 0
    elif kind == "target":
        p.target_balance = 0
    elif kind == "request":
        p.allocation_mode, p.allocation_value = "amount", 0
    elif kind == "inactive":
        p.start_milestone_id = "future"
    allocate_surplus(surplus, priorities, s, age=36, filing_status="single", modified_agi=magi)
    flow = s.allocation_flows[-1]
    assert flow.amount == 0
    assert expected in flow.funding_reasons
    assert s.accounts["ira"].balance == 0


@pytest.mark.anyio
async def test_zero_surplus_reasons_survive_simulation_api(client):
    plan = (await client.post("/api/plans", json={"name": "Zero funding", "birth_year": 1990})).json()
    account = (await client.post("/api/accounts", json={"name": "Brokerage", "account_type": "taxable_brokerage", "balance": 0})).json()
    url = f"/api/plans/{plan['id']}"
    saved = await client.put(url + "/priorities", json={"expected_revision": 0, "items": [{"priority_rank": 1, "target_account_id": account["id"]}]})
    assert saved.status_code == 200
    response = await client.post(url + "/simulate")
    assert response.status_code == 200, response.text
    flow = response.json()["yearly_snapshots"][0]["cash_flow"]["contributions"][0]
    assert flow["amount"] == 0
    assert flow["funding_reasons"] == ["insufficient_surplus"]
    assert flow["priority_rank"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize(("account_type", "birth_year", "expected"), [
    ("traditional_401k", 1990, 24500),  # age 36: base 2026 deferral limit
    ("roth_401k", 1974, 32500),  # age 52: plus the age-50 catch-up
    ("roth_401k", 1964, 35750),  # age 62: plus the age 60-63 catch-up
])
async def test_max_401k_rule_fills_the_full_2026_deferral_limit(client, account_type, birth_year, expected):
    """The clients' "Max 401(k)" rule: payroll funded, no annual maximum."""
    plan = (await client.post("/api/plans", json={
        "name": "Max 401k", "birth_year": birth_year, "plan_type": "FIXED_DATE", "start_date": "2026-01-01",
    })).json()
    work = (await client.post("/api/accounts", json={"name": "Work", "account_type": account_type, "balance": 0})).json()
    salary = (await client.post(f"/api/plans/{plan['id']}/incomes", json={"name": "Salary", "annual_amount": 200000})).json()
    url = f"/api/plans/{plan['id']}"
    rule = {
        "priority_rank": 1, "priority_type": "pre_tax_contribution", "target_account_id": work["id"],
        "source_income_id": salary["id"], "allocation_mode": "remaining", "allocation_value": None,
        "max_annual_amount": None,
    }
    saved = await client.put(url + "/priorities", json={"expected_revision": 0, "items": [rule]})
    assert saved.status_code == 200, saved.text
    response = await client.post(url + "/simulate")
    assert response.status_code == 200, response.text
    first = response.json()["yearly_snapshots"][0]
    assert first["year"] == 2026
    funded = [flow for flow in first["cash_flow"]["contributions"] if flow["account_id"] == work["id"]]
    assert [(flow["source"], flow["amount"]) for flow in funded] == [("payroll", expected)]


def _compensation_limit_plan(salary, employee_rate, employer_rate, first_year_fraction=1.0, target_type="traditional_401k"):
    return PlanData(
        str(uuid.uuid4()),
        1981,
        "single",
        90,
        2026,
        first_year_fraction=first_year_fraction,
        accounts={
            "work": AccountInfo(0, target_type, name="Work plan"),
            "cash": AccountInfo(0, "checking", name="Cash"),
        },
        income_streams=[IncomeData("salary", "Salary", salary, growth_rate=0)],
        priorities=[
            PriorityData(
                1,
                "work",
                priority_type="income_percent",
                source_income_id="salary",
                employee_rate=employee_rate,
                employer_match_rate=employer_rate,
            )
        ],
        assumptions=AssumptionData(
            inflation_rate=0,
            stock_growth_rate=0,
            bond_return_rate=0,
            stock_dividend_yield=0,
            cash_yield_rate=0,
        ),
    )


def _work_contributions(plan):
    snap = run_simulation(plan).yearly_snapshots[0]
    return {c.source: c.amount for c in snap.cash_flow.contributions if c.account_id == "work"}


@pytest.mark.parametrize(
    ("salary", "employee_rate", "employer_rate", "employee", "employer"),
    [
        # IRC 401(a)(17): 2026 limit $360,000 (Notice 2025-67).
        (500_000, 0.04, 0.06, 360_000 * 0.04, 360_000 * 0.06),  # 14,400 / 21,600
        (1_000_000, 0.02, 0.04, 360_000 * 0.02, 360_000 * 0.04),  # 7,200 / 14,400
        (300_000, 0.04, 0.06, 12_000, 18_000),  # below the limit: unchanged
    ],
)
def test_401k_percent_of_pay_uses_at_most_the_401a17_compensation_limit(
    salary, employee_rate, employer_rate, employee, employer
):
    rows = _work_contributions(_compensation_limit_plan(salary, employee_rate, employer_rate))
    assert rows["payroll"] == pytest.approx(employee)
    assert rows["employer"] == pytest.approx(employer)


def test_401a17_limit_is_used_up_by_pay_earned_before_a_mid_year_start():
    # $600,000 salary, plan starts mid-year: $300,000 earned before the start
    # leaves $60,000 of the $360,000 limit for the projected $300,000.
    rows = _work_contributions(_compensation_limit_plan(600_000, 0.04, 0.06, first_year_fraction=0.5))
    assert rows["payroll"] == pytest.approx(60_000 * 0.04)  # 2,400
    assert rows["employer"] == pytest.approx(60_000 * 0.06)  # 3,600


def test_401a17_limit_is_shared_per_stream_and_skips_hsa():
    s = state()
    s.accounts["trad"] = AccountInfo(0, "traditional_401k")
    s.accounts["roth"] = AccountInfo(0, "roth_401k")
    s.accounts["hsa"] = AccountInfo(0, "hsa")
    rules = [
        PriorityData(1, "trad", priority_type="income_percent", source_income_id="salary", employee_rate=0.02),
        PriorityData(2, "roth", priority_type="income_percent", source_income_id="salary", employee_rate=0.02),
        PriorityData(3, "hsa", priority_type="income_percent", source_income_id="salary", employer_match_rate=0.005),
    ]
    result = allocate_payroll_contributions(rules, {"salary": 500_000}, s, 40)
    by_account = {c.target_account_id: c for c in result}
    # Each 401(k) rule applies its rate to the same capped $360,000.
    assert by_account["trad"].employee_amount == pytest.approx(7_200)
    assert by_account["roth"].employee_amount == pytest.approx(7_200)
    # Section 401(a)(17) governs qualified plans, not HSAs: 0.5% of $500,000.
    assert by_account["hsa"].employer_amount == pytest.approx(2_500)
