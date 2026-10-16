"""403(b), 457(b) and 401(a) account types.

2026 figures (IRS Notice 2025-67): 402(g) and 457(e)(15) limits $24,500 each,
age-50 catch-up $8,000, age 60-63 catch-up $11,250, 415(c) $72,000, 401(a)(17)
compensation $360,000. Sources are in coastmath/engine/account_types.py.
"""

from typing import get_args

import pytest

from app.models.account import CurrentAccount
from app.schemas.account import AccountType
from coastmath.engine.account_types import (
    EARLY_WITHDRAWAL_PENALTY_TYPES,
    EMPLOYER_PLAN_TYPES,
    INDIVIDUAL_ONLY_ACCOUNT_TYPES,
    RMD_TYPES,
    SEPP_ELIGIBLE_TYPES,
)
from coastmath.engine.plan_validation import conversion_error
from coastmath.engine.roth import RothLedger
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import (
    after_tax_401k_room,
    allocate_payroll_contributions,
    execute_drawdown,
)
from tests.api_support import save_priorities

pytestmark = pytest.mark.anyio

LIMIT = 24_500
CATCH_UP_50 = 8_000
CATCH_UP_60 = 11_250
NEW_TYPES = ("traditional_403b", "roth_403b", "traditional_457b", "roth_457b", "traditional_401a")


# --- Contribution limits ------------------------------------------------------

def _state(types: dict[str, str], age: int = 40, wages: float = 140_000) -> SimState:
    return SimState(
        year=2026,
        accounts={aid: AccountInfo(0.0, account_type) for aid, account_type in types.items()},
        owner_ages={"self": age},
        compensation_by_owner={"self": wages},
    )


def _payroll(state: SimState, rules: list[PriorityData], wages: float = 140_000, age: int = 40):
    return allocate_payroll_contributions(
        rules, {"w": wages}, state, age, income_owners={"w": "self"}, w2_income_ids={"w"})


def _fill(aid: str, rank: int) -> PriorityData:
    return PriorityData(rank, aid, priority_type="pre_tax_contribution", source_income_id="w")


def _employee(results) -> dict[str, float]:
    return {c.target_account_id: c.employee_amount for c in results}


@pytest.mark.parametrize("second", ["traditional_403b", "roth_403b"])
def test_403b_and_401k_share_one_402g_limit(second):
    state = _state({"k": "traditional_401k", "b": second})
    deposits = _employee(_payroll(state, [_fill("k", 1), _fill("b", 2)]))
    assert deposits == {"k": LIMIT}
    # Filling the 403(b) first leaves nothing for the 401(k) either.
    state = _state({"k": "traditional_401k", "b": second})
    assert _employee(_payroll(state, [_fill("b", 1), _fill("k", 2)])) == {"b": LIMIT}


@pytest.mark.parametrize("plan_457", ["traditional_457b", "roth_457b"])
def test_457b_and_401k_allow_a_double_deferral(plan_457):
    state = _state({"k": "traditional_401k", "g": plan_457})
    assert _employee(_payroll(state, [_fill("k", 1), _fill("g", 2)])) == {"k": LIMIT, "g": LIMIT}


@pytest.mark.parametrize("age,catch_up", [(55, CATCH_UP_50), (61, CATCH_UP_60)])
def test_catch_up_applies_to_each_bucket(age, catch_up):
    state = _state({"b": "traditional_403b", "g": "traditional_457b"}, age=age)
    deposits = _employee(_payroll(state, [_fill("b", 1), _fill("g", 2)], age=age))
    assert deposits == {"b": LIMIT + catch_up, "g": LIMIT + catch_up}


@pytest.mark.parametrize("traditional,roth", [("traditional_403b", "roth_403b"), ("traditional_457b", "roth_457b")])
def test_high_earner_catch_up_must_be_roth_in_403b_and_457b(traditional, roth):
    # SECURE 2.0 s.603: prior-year wages above $150,000 allow catch-up only as Roth.
    state = _state({"t": traditional, "r": roth}, age=55, wages=200_000)
    state.roth_catchup_owners = {"self"}
    deposits = _employee(_payroll(state, [_fill("t", 1), _fill("r", 2)], wages=200_000, age=55))
    assert deposits == {"t": LIMIT, "r": CATCH_UP_50}


def test_401a_takes_employer_money_and_no_employee_deferral():
    state = _state({"a": "traditional_401a"}, wages=100_000)
    rule = PriorityData(1, "a", priority_type="income_percent", source_income_id="w",
                        employee_rate=0.06, employer_match_rate=0.10)
    (result,) = _payroll(state, [rule], wages=100_000)
    assert result.employee_amount == 0
    assert result.employer_amount == pytest.approx(10_000)
    assert state.ytd_contributions.get("a", 0.0) == 0
    assert state.ytd_employer_contributions["a"] == pytest.approx(10_000)
    assert _payroll(_state({"a": "traditional_401a"}, wages=100_000), [_fill("a", 1)], wages=100_000) == []


def test_415c_aggregates_401a_with_401k_but_not_with_403b():
    # $300,000 pay; 401(a) employer money of 20% ($60,000) leaves $12,000 of
    # 415(c) room for 401(k) deferrals. A 403(b) is the participant's own
    # 415(c) plan (Treas. Reg. 1.415(f)-1(f)), so its deferral is unaffected.
    employer = PriorityData(1, "a", priority_type="income_percent", source_income_id="w", employer_match_rate=0.20)
    with_401k = _state({"a": "traditional_401a", "k": "traditional_401k"}, wages=300_000)
    assert _employee(_payroll(with_401k, [employer, _fill("k", 2)], wages=300_000))["k"] == pytest.approx(12_000)
    with_403b = _state({"a": "traditional_401a", "b": "traditional_403b"}, wages=300_000)
    assert _employee(_payroll(with_403b, [employer, _fill("b", 2)], wages=300_000))["b"] == pytest.approx(LIMIT)


def test_457b_employer_money_counts_toward_the_457b_limit_but_not_catch_up():
    state = _state({"g": "traditional_457b"}, age=55, wages=140_000)
    employer = PriorityData(1, "g", priority_type="income_percent", source_income_id="w", employer_match_rate=0.10)
    deposits = _payroll(state, [employer, _fill("g", 2)], age=55)
    assert deposits[0].employer_amount == pytest.approx(14_000)
    # 457(b)(2): base limit less employer money, plus the elective catch-up.
    assert deposits[1].employee_amount == pytest.approx(LIMIT - 14_000 + CATCH_UP_50)
    # Employer money cannot use the catch-up: at most the $24,500 base.
    state = _state({"g": "traditional_457b"}, age=55, wages=400_000)
    big = PriorityData(1, "g", priority_type="income_percent", source_income_id="w", employer_match_rate=0.20)
    assert _payroll(state, [big], wages=400_000, age=55)[0].employer_amount == pytest.approx(LIMIT)


def test_after_tax_401k_room_counts_401a_employer_money():
    state = _state({"a": "traditional_401a", "r": "roth_401k"}, wages=300_000)
    state.ytd_employer_contributions["a"] = 30_000
    room, _ = after_tax_401k_room("self", state)
    assert room == pytest.approx(72_000 - 30_000)


# --- Withdrawals, RMDs, conversions --------------------------------------------

def _drawdown_penalty(account_type: str, age: int = 50) -> float:
    state = SimState(year=2026, accounts={"x": AccountInfo(100_000.0, account_type)}, owner_ages={"self": age})
    _, penalty = execute_drawdown(10_000, [DrawdownEntryData(1, "x")], state, age=age, birth_month=1)
    return penalty


@pytest.mark.parametrize("account_type", ["traditional_403b", "traditional_401a", "traditional_401k"])
def test_early_withdrawal_from_403b_and_401a_carries_the_10_percent_tax(account_type):
    assert _drawdown_penalty(account_type) == pytest.approx(10_000 / 0.9 * 0.1)


def test_457b_withdrawal_before_59_and_a_half_carries_no_10_percent_tax():
    assert _drawdown_penalty("traditional_457b") == 0.0
    assert "traditional_457b" not in EARLY_WITHDRAWAL_PENALTY_TYPES
    assert "roth_457b" not in EARLY_WITHDRAWAL_PENALTY_TYPES


@pytest.mark.parametrize("account_type,penalized", [("roth_403b", True), ("roth_457b", False)])
def test_nonqualified_designated_roth_earnings_are_taxed_and_only_403b_is_penalized(account_type, penalized):
    # $40,000 basis in a $100,000 account: a $10,000 withdrawal is 60% earnings.
    accounts = {"r": AccountInfo(100_000.0, account_type, roth_settings={
        "contribution_basis": 40_000.0, "first_contribution_year": 2024})}
    taxable, penalty = RothLedger(accounts, 2026).distribution("r", 10_000, 100_000, account_type, True, False)
    assert taxable == pytest.approx(6_000)
    assert penalty == pytest.approx(600 if penalized else 0.0)


def _retiree_plan(account_type: str, balance: float = 500_000, birth_year: int = 1950,
                  life_expectancy: int = 78, **extra) -> PlanData:
    return PlanData(
        plan_id="00000000-0000-0000-0000-0000000403b0", birth_year=birth_year, filing_status="single",
        life_expectancy=life_expectancy, start_year=2026,
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts={"cash": AccountInfo(100_000, "checking"), "plan": AccountInfo(balance, account_type, name="Plan")},
        expenses=[ExpenseData("living", "Living", 20_000, inflation_linked=False)],
        drawdown_order=[DrawdownEntryData(1, "cash")],
        **extra,
    )


@pytest.mark.parametrize("account_type", ["traditional_403b", "traditional_457b", "traditional_401a"])
def test_rmds_apply_to_traditional_403b_457b_and_401a(account_type):
    assert account_type in RMD_TYPES
    year = run_simulation(_retiree_plan(account_type)).yearly_snapshots[0]
    rmd = sum(s.amount for s in year.cash_flow.income_sources if s.source == "rmd")
    # Age 76 in 2026: Uniform Lifetime divisor 23.7.
    assert rmd == pytest.approx(500_000 / 23.7, rel=1e-3)


@pytest.mark.parametrize("account_type", ["roth_403b", "roth_457b"])
def test_designated_roth_plans_have_no_lifetime_rmd(account_type):
    year = run_simulation(_retiree_plan(account_type)).yearly_snapshots[0]
    assert not [s for s in year.cash_flow.income_sources if s.source == "rmd"]


def test_roth_conversion_from_traditional_403b():
    source, target = AccountInfo(0, "traditional_403b"), AccountInfo(0, "roth_ira")
    assert conversion_error(source, target) is None
    assert conversion_error(source, AccountInfo(0, "roth_403b")) is None
    assert conversion_error(AccountInfo(0, "roth_403b"), target) is not None
    plan = _retiree_plan("traditional_403b", birth_year=1970, life_expectancy=60,
                         priorities=[PriorityData(1, "roth", priority_type="roth_conversion", source_account_id="plan",
                                                  max_annual_amount=20_000)])
    plan.accounts["roth"] = AccountInfo(0, "roth_ira", name="Roth")
    year = run_simulation(plan).yearly_snapshots[0]
    assert year.accounts["roth"] == pytest.approx(20_000)
    assert year.accounts["plan"] == pytest.approx(480_000)


def test_sepp_eligibility_follows_the_72t_rules():
    assert {"traditional_ira", "traditional_401k", "traditional_403b", "traditional_401a"} == SEPP_ELIGIBLE_TYPES


@pytest.mark.parametrize("account_type", ["traditional_403b", "traditional_457b", "roth_403b"])
def test_inherited_employer_plans_follow_the_401k_beneficiary_rules(account_type):
    def balances(kind: str) -> list[float]:
        plan = _retiree_plan(kind, birth_year=1980, life_expectancy=60)
        plan.accounts["plan"] = AccountInfo(100_000, kind, inherited_year=2022, name="Inherited")
        return [year.accounts["plan"] for year in run_simulation(plan).yearly_snapshots]
    counterpart = "roth_401k" if account_type.startswith("roth") else "traditional_401k"
    inherited = balances(account_type)
    assert inherited == pytest.approx(balances(counterpart))
    # A non-eligible beneficiary empties the account by the tenth year after death.
    assert inherited[2032 - 2026] == pytest.approx(0, abs=0.01)


# --- Taxes and warnings ---------------------------------------------------------

def _worker_plan(account_type: str, state_code: str, employer_rate: float = 0.0) -> PlanData:
    return PlanData(
        plan_id="00000000-0000-0000-0000-0000000457b0", birth_year=1986, birth_month=3,
        filing_status="single", life_expectancy=41, start_year=2026, state_code=state_code,
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts={"chk": AccountInfo(50_000, "checking", name="Chk"), "plan": AccountInfo(0, account_type, name="Plan")},
        income_streams=[IncomeData(id="w", name="Wage", annual_amount=100_000, growth_rate=0.0)],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000, inflation_linked=False)],
        priorities=[PriorityData(1, "plan", priority_type="income_percent", source_income_id="w",
                                 employee_rate=0.10, employer_match_rate=employer_rate)],
        drawdown_order=[DrawdownEntryData(1, "chk")],
    )


def _first_year(account_type: str, state_code: str, employer_rate: float = 0.0):
    return run_simulation(_worker_plan(account_type, state_code, employer_rate)).yearly_snapshots[0]


@pytest.mark.parametrize("account_type", ["traditional_403b", "traditional_457b"])
def test_federal_tax_treats_403b_and_457b_deferrals_like_401k(account_type):
    assert _first_year(account_type, "TX").federal_tax == pytest.approx(_first_year("traditional_401k", "TX").federal_tax)


@pytest.mark.parametrize("state_code", ["PA", "MA"])
@pytest.mark.parametrize("account_type", ["traditional_403b", "traditional_457b"])
def test_pa_and_ma_treat_403b_and_457b_deferrals_like_401k(state_code, account_type):
    assert _first_year(account_type, state_code).state_tax == pytest.approx(
        _first_year("traditional_401k", state_code).state_tax)


@pytest.mark.parametrize("account_type", ["traditional_403b", "traditional_457b"])
def test_nj_taxes_403b_and_457b_deferrals_when_made(account_type):
    # The $10,000 deferral is added back at NJ's 6.37% rate ($75,000-$500,000).
    excess = _first_year(account_type, "NJ").state_tax - _first_year("traditional_401k", "NJ").state_tax
    assert excess == pytest.approx(10_000 * 0.0637, abs=0.01)


def test_nj_also_taxes_employer_403b_contributions():
    with_employer = _first_year("traditional_403b", "NJ", employer_rate=0.05).state_tax
    without = _first_year("traditional_403b", "NJ").state_tax
    # $5,000 more NJ income at 6.37%; W-2 employer 401(k) money stays excluded.
    assert with_employer - without == pytest.approx(5_000 * 0.0637, abs=0.01)
    assert _first_year("traditional_401k", "NJ", employer_rate=0.05).state_tax == pytest.approx(
        _first_year("traditional_401k", "NJ").state_tax)


def test_roth_403b_employer_money_is_taxed_and_named_in_the_warning():
    plan = _worker_plan("roth_403b", "TX", employer_rate=0.05)
    result = run_simulation(plan)
    warnings = result.metadata.warnings
    assert any(w.startswith("Employer contributions to a Roth 403(b) are taxed") and "traditional 403(b)" in w
               for w in warnings)
    without = run_simulation(_worker_plan("roth_403b", "TX")).yearly_snapshots[0].federal_tax
    assert result.yearly_snapshots[0].federal_tax > without


def test_catch_up_note_names_the_plan_families_with_deferral_rules():
    warnings = run_simulation(_worker_plan("traditional_457b", "TX")).metadata.warnings
    assert any(w.startswith("457(b) catch-up eligibility:") for w in warnings)
    assert not any("catch-up eligibility" in w for w in run_simulation(_worker_plan("traditional_401a", "TX")).metadata.warnings)


# --- Persistence and API ----------------------------------------------------------

def test_model_constraint_lists_every_account_type():
    constraint = next(c for c in CurrentAccount.__table__.constraints if c.name == "ck_current_accounts_account_type")
    sql = str(constraint.sqltext)
    listed = {part.strip(" '") for part in sql[sql.index("(") + 1:sql.rindex(")")].split(",")}
    assert listed == set(get_args(AccountType))


def test_central_sets_cover_only_known_types():
    assert set(get_args(AccountType)) >= EMPLOYER_PLAN_TYPES | INDIVIDUAL_ONLY_ACCOUNT_TYPES
    assert set(NEW_TYPES) <= INDIVIDUAL_ONLY_ACCOUNT_TYPES


@pytest.mark.parametrize("account_type", NEW_TYPES)
async def test_account_create_update_and_read_round_trip(client, account_type):
    r = await client.post("/api/accounts", json={"name": "Plan", "account_type": account_type, "balance": 1000})
    assert r.status_code == 201, r.text
    account = r.json()
    assert account["account_type"] == account_type
    r = await client.put(f"/api/accounts/{account['id']}", json={"name": "Renamed", "balance": 2000})
    assert r.status_code == 200, r.text
    assert r.json()["account_type"] == account_type
    listed = {row["id"]: row for row in (await client.get("/api/accounts")).json()}
    assert listed[account["id"]]["account_type"] == account_type and listed[account["id"]]["name"] == "Renamed"
    r = await client.put(f"/api/accounts/{account['id']}", json={"account_type": "traditional_401k"})
    assert r.status_code == 200 and r.json()["account_type"] == "traditional_401k"


async def test_unknown_account_type_uses_the_error_envelope(client):
    r = await client.post("/api/accounts", json={"name": "Plan", "account_type": "traditional_403c"})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and error["details"]


async def test_inherited_and_roth_history_persist_for_new_types(client):
    r = await client.post("/api/accounts", json={
        "name": "Inherited 457(b)", "account_type": "traditional_457b", "balance": 1000,
        "inherited_year": 2022, "beneficiary_type": "non_edb"})
    assert r.status_code == 201 and r.json()["inherited_year"] == 2022
    r = await client.post("/api/accounts", json={
        "name": "Roth 403(b)", "account_type": "roth_403b", "balance": 1000,
        "roth_settings": {"contribution_basis": 500, "first_contribution_year": 2020, "conversions": []}})
    assert r.status_code == 201 and r.json()["roth_settings"]["contribution_basis"] == 500


async def _plan_with(client, *types: str):
    plan = (await client.post("/api/plans", json={"name": "Employer plans", "birth_year": 1980, "plan_type": "NOW"})).json()
    accounts = {}
    for account_type in types:
        r = await client.post("/api/accounts", json={"name": account_type, "account_type": account_type, "balance": 10_000})
        accounts[account_type] = r.json()
    wage = await client.post(f"/api/plans/{plan['id']}/incomes", json={
        "name": "Salary", "annual_amount": 120_000, "is_earned_income": True})
    assert wage.status_code == 201, wage.text
    return plan, accounts, wage.json()


async def test_priorities_accept_payroll_and_reject_surplus_for_new_employer_plans(client):
    plan, accounts, wage = await _plan_with(client, "traditional_403b", "traditional_457b", "traditional_401a", "roth_403b")
    payroll = [
        {"priority_rank": 1, "priority_type": "income_percent", "target_account_id": accounts["traditional_403b"]["id"],
         "source_income_id": wage["id"], "employee_rate": 0.05, "employer_match_rate": 0.03},
        {"priority_rank": 2, "priority_type": "pre_tax_contribution", "target_account_id": accounts["traditional_457b"]["id"],
         "source_income_id": wage["id"]},
        {"priority_rank": 3, "priority_type": "income_percent", "target_account_id": accounts["traditional_401a"]["id"],
         "source_income_id": wage["id"], "employer_match_rate": 0.10},
    ]
    r = await save_priorities(client, plan["id"], payroll)
    assert r.status_code == 200, r.text
    surplus = {"priority_rank": 4, "priority_type": "contribution", "target_account_id": accounts["traditional_403b"]["id"]}
    r = await save_priorities(client, plan["id"], [*payroll, surplus])
    assert r.status_code == 422
    assert "403(b) contributions must use a payroll rule" in r.json()["error"]["message"]
    employee_401a = {**payroll[2], "employee_rate": 0.05}
    r = await save_priorities(client, plan["id"], [*payroll[:2], employee_401a])
    assert r.status_code == 422 and "401(a) takes employer contributions only" in r.json()["error"]["message"]
    mega = {"priority_rank": 4, "priority_type": "after_tax_401k", "target_account_id": accounts["roth_403b"]["id"],
            "source_income_id": wage["id"]}
    r = await save_priorities(client, plan["id"], [*payroll, mega])
    assert r.status_code == 422  # the mega backdoor stays 401(k)-only
    sim = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert sim.status_code == 200, sim.text


async def test_sepp_source_accepts_403b_and_rejects_457b(client):
    plan, accounts, _ = await _plan_with(client, "traditional_403b", "traditional_457b")
    settings = {"enabled": True, "method": "fixed_amortization", "start_age": 52, "interest_rate": 0.05}
    r = await client.put(f"/api/plans/{plan['id']}", json={"sepp_settings": {
        **settings, "source_account_id": accounts["traditional_403b"]["id"]}})
    assert r.status_code == 200, r.text
    r = await client.put(f"/api/plans/{plan['id']}", json={"sepp_settings": {
        **settings, "source_account_id": accounts["traditional_457b"]["id"]}})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "sepp_settings.source_account_id"


async def test_stateless_simulation_accepts_new_types(client):
    body = {
        "plan_id": "00000000-0000-0000-0000-00000000a401", "birth_year": 1980, "start_year": 2026,
        "first_year_fraction": 1.0, "life_expectancy": 50,
        "accounts": {
            "b": {"balance": 10_000, "account_type": "traditional_403b", "name": "403(b)"},
            "g": {"balance": 10_000, "account_type": "roth_457b", "name": "Roth 457(b)",
                  "roth_settings": {"contribution_basis": 1_000, "first_contribution_year": 2020}},
            "a": {"balance": 10_000, "account_type": "traditional_401a", "name": "401(a)",
                  "inherited_year": 2025, "beneficiary_type": "non_edb"},
        },
        "income_streams": [{"id": "w", "name": "Salary", "annual_amount": 100_000, "is_earned_income": True}],
        "priorities": [{"priority_rank": 1, "priority_type": "pre_tax_contribution", "target_account_id": "b",
                        "source_income_id": "w"}],
    }
    r = await client.post("/api/simulate/stateless", json=body)
    assert r.status_code == 200, r.text
    first = r.json()["yearly_snapshots"][0]
    assert first["accounts"]["b"] > 10_000
    assert set(first["accounts"]) >= {"b", "g", "a"}


def test_year_to_date_457b_employer_money_uses_the_457b_limit():
    plan = _worker_plan("traditional_457b", "TX")
    plan.priorities = [PriorityData(1, "plan", priority_type="pre_tax_contribution", source_income_id="w")]
    plan.tax_settings = {"year_to_date": {"tax_year": 2026, "employer_contributions_by_account": {"plan": 10_000}}}
    year = run_simulation(plan).yearly_snapshots[0]
    deferral = sum(c.amount for c in year.cash_flow.contributions if c.account_id == "plan" and c.source == "payroll")
    assert deferral == pytest.approx(LIMIT - 10_000)
