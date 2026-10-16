"""Employer match formulas, custom plan limits, fee types and paid-out income.

2026 figures (IRS Notice 2025-67): 402(g) limit $24,500, 401(a)(17)
compensation $360,000. A matching formula pays on the employee's actual
deferral as a share of pay; a nonelective contribution does not depend on it.
SECURE 2.0 sec. 604 Roth employer money is taxable income in the year
contributed but not FICA wages (IRS Notice 2024-2, section L).
"""

import pytest

from coastmath.engine import intl_accounts
from coastmath.engine.simulator import (
    _average_monthly_deposit_growth_factor,
    run_simulation,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EmployerMatchData,
    ExpenseData,
    IncomeData,
    MatchTierData,
    PlanData,
    PriorityData,
    SimState,
    employer_match_from_settings,
)
from coastmath.engine.waterfall import (
    allocate_payroll_contributions,
    allocate_surplus,
    employer_match_amount,
)
from tests.api_support import save_priorities

pytestmark = pytest.mark.anyio

LIMIT = 24_500


def _match(*tiers, **options) -> EmployerMatchData:
    return EmployerMatchData(tiers=[MatchTierData(m, up_to) for m, up_to in tiers], **options)


SIX = _match((1.0, 0.06))


# --- Formula -------------------------------------------------------------------

@pytest.mark.parametrize("deferral_rate, expected", [(0.0, 0), (0.03, 3_000), (0.06, 6_000), (0.10, 6_000)])
def test_full_match_on_the_first_six_percent(deferral_rate, expected):
    assert employer_match_amount(SIX, 100_000, 100_000 * deferral_rate, deferral_rate) == pytest.approx(expected)


@pytest.mark.parametrize("deferral_rate, expected", [(0.02, 2_000), (0.04, 3_500), (0.05, 4_000), (0.08, 4_000)])
def test_two_tier_formula_stacks_bands(deferral_rate, expected):
    # 100% of the first 3% of pay, then 50% of the next 2%.
    formula = _match((1.0, 0.03), (0.5, 0.02))
    assert employer_match_amount(formula, 100_000, 100_000 * deferral_rate, deferral_rate) == pytest.approx(expected)


def test_dollar_cap_limits_the_total():
    assert employer_match_amount(SIX, 200_000, 20_000, 0.10, cap=5_000) == pytest.approx(5_000)


def test_nonelective_is_paid_without_deferrals_and_added_to_the_match():
    formula = _match((0.5, 0.06), nonelective_percent=0.03)
    assert employer_match_amount(formula, 100_000, 0, 0.0) == pytest.approx(3_000)
    assert employer_match_amount(formula, 100_000, 6_000, 0.06) == pytest.approx(3_000 + 3_000)


def test_per_period_equals_true_up_when_deferrals_never_stop():
    per_period = _match((1.0, 0.06), true_up=False)
    assert employer_match_amount(per_period, 120_000, 7_200, 0.06) == pytest.approx(7_200)


def test_settings_convert_percents_to_decimals():
    data = employer_match_from_settings({"tiers": [{"match_percent": 50, "up_to_percent_of_pay": 6}],
                                         "cap_amount": 4000, "nonelective_percent": 2, "true_up": False, "roth": True})
    assert data == EmployerMatchData([MatchTierData(0.5, 0.06)], 4000.0, 0.02, False, True)
    assert employer_match_from_settings(None) is None


# --- Payroll allocation ----------------------------------------------------------

def _state(types: dict[str, str], wages: float, age: int = 40) -> SimState:
    return SimState(year=2026, accounts={aid: AccountInfo(0.0, t) for aid, t in types.items()},
                    owner_ages={"self": age}, compensation_by_owner={"self": wages})


def _payroll(state, rules, wages, months=12, fraction=1.0):
    return allocate_payroll_contributions(rules, {"w": wages}, state, 40, contribution_fraction=fraction,
                                          income_owners={"w": "self"}, w2_income_ids={"w"},
                                          pay_months_by_income={"w": months})


def _rule(rate, match=None, legacy=0.0, **kw) -> PriorityData:
    return PriorityData(1, "k", priority_type="income_percent", source_income_id="w",
                        employee_rate=rate, employer_match_rate=legacy, employer_match=match, **kw)


def test_true_up_vs_per_period_when_the_deferral_limit_stops_in_september():
    # 15% of $225,000 is $2,812.50 a month: eight full months, then the last
    # $2,000 of the $24,500 limit in September. Per period that month is
    # matched in full (its deferral still exceeds 6% of its pay) and October
    # through December get nothing: 9 x $1,125. A true-up matches 6% of the
    # whole year's pay because the year's deferral (10.9%) exceeds 6%.
    wages = 225_000
    true_up = _payroll(_state({"k": "traditional_401k"}, wages), [_rule(0.15, _match((1.0, 0.06)))], wages)
    per_period = _payroll(_state({"k": "traditional_401k"}, wages),
                          [_rule(0.15, _match((1.0, 0.06), true_up=False))], wages)
    assert true_up[0].employee_amount == pytest.approx(LIMIT)
    assert true_up[0].employer_amount == pytest.approx(13_500)
    assert per_period[0].employee_amount == pytest.approx(LIMIT)
    assert per_period[0].employer_amount == pytest.approx(9 * 1_125)


def test_per_period_partial_last_month_is_matched_on_its_own_deferral():
    # 12% of $10,000 monthly pay is $1,200; a $12,300 annual maximum gives ten
    # full months matched at 6% ($600 each), then $300 in November: 3% of
    # that month's pay, matched $300. A true-up would match 6% of the year.
    state = _state({"k": "traditional_401k"}, 120_000)
    result = _payroll(state, [_rule(0.12, _match((1.0, 0.06), true_up=False), max_annual_amount=12_300)], 120_000)
    assert result[0].employee_amount == pytest.approx(12_300)
    assert result[0].employer_amount == pytest.approx(10 * 600 + 300)


def test_legacy_employer_rate_is_unchanged_and_pays_without_deferrals():
    state = _state({"k": "traditional_401k"}, 100_000)
    result = _payroll(state, [_rule(0.0, legacy=0.05)], 100_000)
    assert result[0].employee_amount == 0
    assert result[0].employer_amount == pytest.approx(5_000)


def test_formula_without_deferral_pays_nothing():
    state = _state({"k": "traditional_401k"}, 100_000)
    assert _payroll(state, [_rule(0.0, SIX)], 100_000) == []


def test_cap_is_indexed_with_inflation_and_prorated_in_a_partial_year():
    state = _state({"k": "traditional_401k"}, 100_000)
    state.inflation_factor = 1.1
    result = _payroll(state, [_rule(0.10, _match((1.0, 0.06), cap_amount=4_000))], 100_000, fraction=0.5)
    assert result[0].employer_amount == pytest.approx(4_000 * 1.1 * 0.5)


def test_roth_match_goes_to_the_same_plan_roth_account():
    state = _state({"k": "traditional_401k", "r": "roth_401k", "i": "roth_ira"}, 100_000)
    result = _payroll(state, [_rule(0.06, _match((1.0, 0.06), roth=True))], 100_000)
    assert [(c.target_account_id, c.employee_amount, c.employer_amount) for c in result] == [
        ("k", pytest.approx(6_000), 0.0), ("r", 0.0, pytest.approx(6_000))]
    assert state.accounts["k"].balance == pytest.approx(6_000)
    assert state.accounts["r"].balance == pytest.approx(6_000)
    assert state.ytd_employer_contributions == {"r": pytest.approx(6_000)}


def test_roth_match_without_a_roth_account_stays_in_the_rule_account():
    state = _state({"k": "traditional_401k"}, 100_000)
    result = _payroll(state, [_rule(0.06, _match((1.0, 0.06), roth=True))], 100_000)
    assert [(c.target_account_id, c.employer_amount) for c in result] == [("k", pytest.approx(6_000))]


def test_415c_still_caps_a_formula_match():
    # 415(c) is $72,000 in 2026; $24,500 of deferrals leave $47,500.
    state = _state({"k": "traditional_401k"}, 350_000)
    result = _payroll(state, [_rule(0.10, _match((2.0, 0.10)))], 350_000)
    assert result[0].employee_amount == pytest.approx(LIMIT)
    assert result[0].employer_amount == pytest.approx(72_000 - LIMIT)


# --- Custom plan limits ----------------------------------------------------------------

def test_custom_limit_lowers_payroll_deferrals():
    state = _state({"k": "traditional_401k"}, 200_000)
    result = _payroll(state, [_rule(0.10, limit_mode="custom", custom_annual_limit=15_000)], 200_000)
    assert result[0].employee_amount == pytest.approx(15_000)


def test_custom_limit_never_exceeds_the_irs_limit():
    state = _state({"k": "traditional_401k"}, 400_000)
    result = _payroll(state, [_rule(0.20, limit_mode="custom", custom_annual_limit=50_000)], 400_000)
    assert result[0].employee_amount == pytest.approx(LIMIT)


def test_custom_limit_on_a_surplus_rule_and_its_reason():
    state = SimState(year=2026, accounts={"ira": AccountInfo(0.0, "roth_ira", name="Roth IRA")}, owner_ages={"self": 40})
    state.coverage_inflation_factor = 1.0
    deposits = allocate_surplus(20_000, [PriorityData(1, "ira", priority_type="contribution",
                                                      limit_mode="custom", custom_annual_limit=3_000)], state, age=40)
    assert deposits == {"ira": pytest.approx(3_000)}
    assert "plan contribution limit" in state.allocation_flows[0].limited_by


# --- Self-employed employer contributions ----------------------------------------------

SE_ROOM = 18_587.045  # shared employer room for $100,000 of self-employment income


def _se_payroll(accounts: dict[str, AccountInfo], rates: list[tuple[str, float]], room: dict[str, float]):
    state = SimState(2026, accounts=accounts, owner_ages={"self": 40}, compensation_by_owner={"self": 100_000},
                     self_employment_plan_ids={aid for aid, acct in accounts.items() if not acct.intl_account_kind})
    if any(acct.intl_account_kind for acct in accounts.values()):
        intl_accounts.start_year(state, {"self": 40})
    rules = [PriorityData(rank, target_account_id=aid, priority_type="income_percent", source_income_id="se",
                          employee_rate=0, employer_match_rate=rate)
             for rank, (aid, rate) in enumerate(rates, start=1)]
    result = allocate_payroll_contributions(
        rules, {"se": 100_000}, state, 40, income_owners={"se": "self"},
        self_employment_income_ids={"se"}, self_employed_employer_room=room)
    return [(c.target_account_id, c.employer_amount) for c in result], state


def test_self_employed_employer_rules_share_one_profit_and_room():
    room = {"self": SE_ROOM}
    rows, state = _se_payroll({"k1": AccountInfo(0, "traditional_401k"), "k2": AccountInfo(0, "traditional_401k")},
                              [("k1", 0.2), ("k2", 0.2)], room)
    # The first rule uses all of the shared room; the second has none left.
    assert rows == [("k1", pytest.approx(SE_ROOM))]
    assert room["self"] == pytest.approx(0)
    assert state.get_balance("k2") == 0


def test_single_self_employed_employer_rule_is_unchanged():
    room = {"self": SE_ROOM}
    rows, _ = _se_payroll({"k": AccountInfo(0, "traditional_401k")}, [("k", 0.1)], room)
    assert rows == [("k", pytest.approx(10_000))]
    assert room["self"] == pytest.approx(SE_ROOM - 10_000)


def test_country_account_employer_rule_keeps_its_rules_and_spends_the_profit(fixture_pack):
    room = {"self": SE_ROOM}
    rows, state = _se_payroll({
        "super": AccountInfo(0, "other", intl_account_kind="QZ:taxed_pension"),
        "voluntary": AccountInfo(0, "other", intl_account_kind="QZ:after_tax_saver"),
        "k": AccountInfo(0, "traditional_401k"),
    }, [("super", 0.2), ("voluntary", 0.2), ("k", 0.9)], room)
    # The taxed pension takes employer money (15% contributions tax inside
    # the account); the after-tax saver takes none. The 401(k) gets the
    # profit left after the country account, within the shared room.
    assert rows == [("super", pytest.approx(20_000)), ("k", pytest.approx(SE_ROOM))]
    assert state.get_balance("super") == pytest.approx(17_000)
    assert state.get_balance("voluntary") == 0
    assert room["self"] == pytest.approx(0)


# --- Country accounts: employer money within the kind's room ----------------------------

def _country_payroll(kind: str, wages: float, employee_rate: float, employer_rate: float, extra=None):
    accounts = {"a": AccountInfo(0, "other", intl_account_kind=kind), **(extra or {})}
    state = SimState(2026, accounts=accounts, owner_ages={"self": 40}, compensation_by_owner={"self": wages})
    intl_accounts.start_year(state, {"self": 40})
    rule = PriorityData(1, "a", priority_type="income_percent", source_income_id="w",
                        employee_rate=employee_rate, employer_match_rate=employer_rate)
    result = allocate_payroll_contributions([rule], {"w": wages}, state, 40, income_owners={"w": "self"},
                                            w2_income_ids={"w"})
    return [(c.employee_amount, c.employer_amount) for c in result], state


@pytest.mark.parametrize("kind, wages, employee_rate, employer_rate, expected", [
    # A 32,500 dollar limit: employer money stops at the cap.
    ("QZ:taxed_pension", 100_000, 0.0, 0.9, (0, 32_500)),
    ("QZ:taxed_pension", 100_000, 0.2, 0.2, (20_000, 12_500)),
    # A 60,000 allowance counts both; the employee's own come first.
    ("QZ:workplace_pension", 100_000, 0.3, 0.5, (30_000, 30_000)),
    # Room of 20% of pay up to 20,000, shared by employee and employer.
    ("QZ:pension_saver", 100_000, 0.1, 0.2, (10_000, 10_000)),
    ("QZ:pension_saver", 300_000, 0.025, 0.075, (7_500, 20_000 - 7_500)),
])
def test_country_account_employer_money_stops_at_the_kinds_room(kind, wages, employee_rate, employer_rate, expected,
                                                                 fixture_pack):
    rows, state = _country_payroll(kind, wages, employee_rate, employer_rate)
    assert rows == [(pytest.approx(expected[0]), pytest.approx(expected[1]))]
    assert state.ytd_contributions["a"] == pytest.approx(sum(expected))
    assert intl_accounts.contribution_room("a", state) == pytest.approx(0)


def test_employer_money_is_outside_the_earnings_limit(fixture_pack):
    """Pay 30,000: the employer's 30,000 fits the 60,000 allowance though it exceeds the
    member's 100% of earnings limit."""
    rows, _ = _country_payroll("QZ:workplace_pension", 30_000, 0.2, 1.0)
    assert rows == [(pytest.approx(6_000), pytest.approx(30_000))]


def test_member_room_counts_only_member_contributions(fixture_pack):
    """Pay 30,000, employee 6,000 and employer 15,000: a private pension has 30,000 - 6,000 of member
    room (the allowance has 60,000 - 21,000 left); employer money has the allowance's 39,000."""
    rows, state = _country_payroll("QZ:workplace_pension", 30_000, 0.2, 0.5,
                                   extra={"private": AccountInfo(0, "other", intl_account_kind="QZ:private_pension")})
    assert rows == [(pytest.approx(6_000), pytest.approx(15_000))]
    assert intl_accounts.contribution_room("private", state) == pytest.approx(24_000)
    assert intl_accounts.contribution_room("private", state, employer=True) == pytest.approx(39_000)


# --- Simulation: Roth match taxed, fees, paid-out income -------------------------------

def _worker_plan(match: EmployerMatchData | None, accounts=None) -> PlanData:
    return PlanData(
        plan_id="00000000-0000-0000-0000-000000000a7c", birth_year=1986, birth_month=3,
        filing_status="single", life_expectancy=41, start_year=2026, state_code="TX",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts=accounts or {"chk": AccountInfo(50_000, "checking", name="Chk"),
                              "k": AccountInfo(0, "traditional_401k", name="401k"),
                              "r": AccountInfo(0, "roth_401k", name="Roth 401k")},
        income_streams=[IncomeData(id="w", name="Wage", annual_amount=100_000, growth_rate=0.0)],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000, inflation_linked=False)],
        priorities=[PriorityData(1, "k", priority_type="income_percent", source_income_id="w",
                                 employee_rate=0.10, employer_match=match)],
        drawdown_order=[DrawdownEntryData(1, "chk")],
    )


def test_roth_match_is_routed_and_taxed_as_income_but_not_fica():
    pre_tax = run_simulation(_worker_plan(_match((1.0, 0.06)))).yearly_snapshots[0]
    roth_result = run_simulation(_worker_plan(_match((1.0, 0.06), roth=True)))
    roth = roth_result.yearly_snapshots[0]
    assert pre_tax.accounts["k"] == pytest.approx(16_000)
    assert roth.accounts["k"] == pytest.approx(10_000)
    assert roth.accounts["r"] == pytest.approx(6_000)
    assert roth.federal_tax - pre_tax.federal_tax == pytest.approx(6_000 * roth.marginal_rate, abs=0.01)
    assert roth.fica_tax == pytest.approx(pre_tax.fica_tax)
    assert any(w.startswith("Employer contributions to a Roth 401(k) are taxed") for w in roth_result.metadata.warnings)


def _growth_plan(settings, growth, accounts_extra=None, inflation=0.0) -> PlanData:
    accounts = {"chk": AccountInfo(0, "checking", name="Chk"),
                "b": AccountInfo(100_000, "taxable_brokerage", name="Brokerage", cost_basis=100_000,
                                 investment_settings=settings)}
    return PlanData(
        plan_id="00000000-0000-0000-0000-0000000fee01", birth_year=1980, filing_status="single",
        life_expectancy=48, start_year=2026,
        assumptions=AssumptionData(inflation_rate=inflation, stock_growth_rate=growth, bond_return_rate=0.0,
                                   stock_dividend_yield=0.0),
        accounts=accounts,
        income_streams=[IncomeData(id="w", name="Wage", annual_amount=60_000, growth_rate=0.0)],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=30_000, inflation_linked=False)],
        drawdown_order=[DrawdownEntryData(1, "chk"), DrawdownEntryData(2, "b")],
    )


def test_flat_fee_amount_is_indexed_and_prorated():
    state = SimState(year=2026, accounts={"ira": AccountInfo(100_000, "traditional_ira",
                                                             investment_settings={"annual_fee_amount": 500})})
    state.inflation_factor = 1.2
    state.apply_growth(0.05, fee_year_fraction=0.5)
    assert state.investment_fees_this_year == pytest.approx(500 * 1.2 * 0.5)
    assert state.accounts["ira"].balance == pytest.approx(105_000 - 300)


def test_fee_on_earnings_charges_gains_but_not_a_loss_year():
    gain = SimState(year=2026, accounts={"ira": AccountInfo(100_000, "traditional_ira",
                                                            investment_settings={"fee_percent_of_earnings": 0.2})})
    gain.apply_growth(0.10)
    assert gain.investment_fees_this_year == pytest.approx(2_000)
    assert gain.accounts["ira"].balance == pytest.approx(108_000)
    loss = SimState(year=2026, accounts={"ira": AccountInfo(100_000, "traditional_ira",
                                                            investment_settings={"fee_percent_of_earnings": 0.2})})
    loss.apply_growth(-0.10)
    assert loss.investment_fees_this_year == 0
    assert loss.accounts["ira"].balance == pytest.approx(90_000)


def test_fee_types_add_up_and_never_take_the_balance_negative():
    state = SimState(year=2026, accounts={"a": AccountInfo(1_000, "roth_ira", investment_settings={
        "annual_fee_rate": 0.01, "annual_fee_amount": 5_000, "fee_percent_of_earnings": 0.5})})
    state.apply_growth(0.10)
    assert state.accounts["a"].balance == pytest.approx(0)
    assert state.investment_fees_this_year == pytest.approx(1_100)


def test_cash_accounts_pay_no_new_fee_types():
    state = SimState(year=2026, accounts={"s": AccountInfo(10_000, "savings", investment_settings={
        "annual_fee_amount": 100, "fee_percent_of_earnings": 0.5})})
    state.apply_growth(0.10, cash_yield_rate=0.04)
    assert state.investment_fees_this_year == 0


def test_paid_out_income_leaves_balance_and_basis_but_is_still_recognized():
    def grown(reinvest):
        state = SimState(year=2026, accounts={"b": AccountInfo(
            100_000, "taxable_brokerage", cost_basis=80_000, investment_settings={"reinvest_income": reinvest})})
        dividends, _ = state.apply_growth(0.04, stock_dividend_yield=0.02)
        return state, dividends
    kept, kept_dividends = grown(None)
    paid, paid_dividends = grown(False)
    assert kept_dividends == paid_dividends == pytest.approx(2_000)
    assert paid.qualified_dividends_this_year == kept.qualified_dividends_this_year == pytest.approx(2_000)
    assert kept.accounts["b"].balance - paid.accounts["b"].balance == pytest.approx(2_000)
    assert paid.accounts["b"].cost_basis == pytest.approx(80_000)
    assert kept.accounts["b"].cost_basis == pytest.approx(82_000)
    assert paid.paid_out_dividends_this_year == pytest.approx(2_000)
    assert kept.paid_out_dividends_this_year == 0


def test_reinvest_false_moves_income_to_cash_and_keeps_tax():
    def first(settings):
        plan = _growth_plan(settings, 0.0)
        plan.assumptions.stock_dividend_yield = 0.03
        return run_simulation(plan).yearly_snapshots[0]
    reinvested = first({"dividend_yield": 0.03})
    paid_out = first({"dividend_yield": 0.03, "reinvest_income": False})
    assert paid_out.federal_tax == pytest.approx(reinvested.federal_tax)
    assert reinvested.accounts["b"] - paid_out.accounts["b"] == pytest.approx(3_000)
    assert paid_out.accounts["chk"] - reinvested.accounts["chk"] == pytest.approx(3_000)
    reinvest_flows = [c for c in paid_out.cash_flow.contributions if c.source == "reinvestment"]
    assert reinvest_flows == []


def _contribution_plan(reinvest, tax_settings=None) -> PlanData:
    """$120,000 saved monthly into an empty brokerage: 3% dividends, no price growth."""
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000102", birth_year=1960, birth_month=1,
        filing_status="single", life_expectancy=67, start_year=2026, state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                                   stock_dividend_yield=0.03),
        accounts={"cash": AccountInfo(0, "checking", name="Cash"),
                  "b": AccountInfo(0, "taxable_brokerage", investment_settings={
                      "reinvest_income": reinvest, "bond_allocation": 0})},
        income_streams=[IncomeData("i", "Income", 120_000, is_earned_income=False, tax_category="nontaxable")],
        priorities=[PriorityData(1, target_account_id="b")],
        drawdown_order=[DrawdownEntryData(1, "cash")],
        tax_settings=tax_settings or {"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0})


def _first_year_with_basis(plan, monkeypatch):
    bases = []
    original = SimState.snapshot

    def snapshot(state):
        if state.year == plan.start_year:
            bases.append({aid: a.cost_basis for aid, a in state.accounts.items()})
        return original(state)

    monkeypatch.setattr(SimState, "snapshot", snapshot)
    # The year's last snapshot is its year-end record.
    return run_simulation(plan).yearly_snapshots[0], bases[-1]


def test_income_on_contributions_is_paid_out_when_reinvestment_is_off(monkeypatch):
    snap, basis = _first_year_with_basis(_contribution_plan(False), monkeypatch)
    assert snap.accounts["b"] == pytest.approx(120_000, abs=0.01)
    assert basis["b"] == pytest.approx(120_000, abs=0.01)
    assert snap.accounts["cash"] == pytest.approx(1_641.19, abs=0.01)
    flows = snap.cash_flow.contributions
    assert [c for c in flows if c.source == "reinvestment"] == []
    banked = [c for c in flows if c.source == "default_sink"]
    assert [(c.account_id, round(c.amount, 2)) for c in banked] == [("cash", 1_641.19)]
    income = {c.name: c.amount for c in snap.cash_flow.income_sources}
    assert income["Taxable Stock Dividends on Contributions"] == pytest.approx(1_641.19, abs=0.01)


def test_income_on_contributions_is_reinvested_by_default(monkeypatch):
    snap, basis = _first_year_with_basis(_contribution_plan(None), monkeypatch)
    assert snap.accounts["b"] == pytest.approx(121_641.19, abs=0.01)
    assert basis["b"] == pytest.approx(121_641.19, abs=0.01)
    assert snap.accounts["cash"] == 0
    reinvested = [(c.name, round(c.amount, 2)) for c in snap.cash_flow.contributions if c.source == "reinvestment"]
    assert reinvested == [("Reinvested dividends on contributions", 1_641.19)]


def test_paid_out_income_on_contributions_keeps_its_tax():
    taxed = {"mode": "flat", "ordinary_income_tax_rate": 0.2, "capital_gains_tax_rate": 0.15}
    paid = run_simulation(_contribution_plan(False, taxed)).yearly_snapshots[0]
    kept = run_simulation(_contribution_plan(None, taxed)).yearly_snapshots[0]
    assert paid.taxes > 0
    assert paid.taxes == pytest.approx(kept.taxes)


def _drawdown_plan(reinvest, tax_settings=None) -> PlanData:
    """$60,000 of spending drawn from a $100,000 brokerage: 3% dividends, no price growth."""
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000103", birth_year=1960, birth_month=1,
        filing_status="single", life_expectancy=67, start_year=2026, state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                                   stock_dividend_yield=0.03),
        accounts={"cash": AccountInfo(0, "checking", name="Cash"),
                  "b": AccountInfo(100_000, "taxable_brokerage", name="Brokerage", cost_basis=100_000,
                                   investment_settings={"reinvest_income": reinvest, "bond_allocation": 0})},
        expenses=[ExpenseData("e", "Living", 60_000)],
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "b")],
        tax_settings=tax_settings or {"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0})


def _brokerage_drawdown(snap) -> float:
    return sum(c.amount for c in snap.cash_flow.drawdowns if c.account_id == "b")


@pytest.mark.parametrize("reinvest", [None, False])
def test_money_withdrawn_mid_year_earns_no_income_whether_paid_out_or_reinvested(reinvest):
    # Both settings credit a full year of dividends on the opening balance and
    # take back what the money withdrawn each month never earned.
    unearned = _average_monthly_deposit_growth_factor(0.03, 12)
    snap = run_simulation(_drawdown_plan(reinvest)).yearly_snapshots[0]
    withdrawn = _brokerage_drawdown(snap)
    # Paid-out dividends fund part of the spending; reinvested ones do not.
    assert withdrawn == pytest.approx(60_000 if reinvest is None else 57_000, abs=0.01)
    assert snap.accounts["b"] == pytest.approx(
        100_000 + 3_000 - 60_000 - withdrawn * unearned, abs=0.01)


def test_paid_out_income_on_withdrawn_money_is_not_taxed(monkeypatch):
    taxed = {"mode": "flat", "ordinary_income_tax_rate": 0.2, "capital_gains_tax_rate": 0.2}
    snap, basis = _first_year_with_basis(_drawdown_plan(False, taxed), monkeypatch)
    withdrawn = _brokerage_drawdown(snap)
    earned = 3_000 - withdrawn * _average_monthly_deposit_growth_factor(0.03, 12)
    # No price growth and basis equal to the balance: the dividends are the only income.
    assert snap.taxes == pytest.approx(0.2 * earned, abs=0.01)
    # The unearned income leaves the balance at cost: no phantom gain or loss.
    assert basis["b"] == pytest.approx(snap.accounts["b"], abs=0.01)


def test_reinvest_flag_is_ignored_outside_taxable_brokerage():
    state = SimState(year=2026, accounts={"ira": AccountInfo(100_000, "traditional_ira",
                                                             investment_settings={"reinvest_income": False})})
    state.apply_growth(0.0, stock_dividend_yield=0.02)
    assert state.accounts["ira"].balance == pytest.approx(102_000)


# --- API and persistence ---------------------------------------------------------------

async def _plan_with(client, *types: str):
    plan = (await client.post("/api/plans", json={"name": "Match", "birth_year": 1980, "plan_type": "NOW"})).json()
    accounts = {}
    for account_type in types:
        r = await client.post("/api/accounts", json={"name": account_type, "account_type": account_type, "balance": 0})
        assert r.status_code == 201, r.text
        accounts[account_type] = r.json()
    wage = await client.post(f"/api/plans/{plan['id']}/incomes", json={
        "name": "Salary", "annual_amount": 120_000, "is_earned_income": True})
    assert wage.status_code == 201, wage.text
    return plan, accounts, wage.json()


MATCH = {"tiers": [{"match_percent": 100, "up_to_percent_of_pay": 3}, {"match_percent": 50, "up_to_percent_of_pay": 2}],
         "cap_amount": 6000, "nonelective_percent": 1, "true_up": False, "roth": True}


async def test_priority_formula_and_custom_limit_round_trip_and_simulate(client):
    plan, accounts, wage = await _plan_with(client, "traditional_401k", "roth_401k", "roth_ira")
    rule = {"priority_rank": 1, "priority_type": "income_percent", "target_account_id": accounts["traditional_401k"]["id"],
            "source_income_id": wage["id"], "employee_rate": 6, "employer_match": MATCH,
            "limit_mode": "custom", "custom_annual_limit": 20_000}
    surplus = {"priority_rank": 2, "priority_type": "contribution", "target_account_id": accounts["roth_ira"]["id"]}
    r = await save_priorities(client, plan["id"], [rule, surplus])
    assert r.status_code == 200, r.text
    listed = (await client.get(f"/api/plans/{plan['id']}/priorities")).json()["items"]
    assert listed[0]["employer_match"] == MATCH
    assert (listed[0]["limit_mode"], listed[0]["custom_annual_limit"]) == ("custom", 20_000)
    assert (listed[1]["employer_match"], listed[1]["limit_mode"], listed[1]["custom_annual_limit"]) == (None, "irs", None)
    sim = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert sim.status_code == 200, sim.text
    first = sim.json()["yearly_snapshots"][0]
    # The employer money (4% matched plus 1% nonelective, capped) is paid
    # into the Roth 401(k); the opening year is partial, so only its
    # destination is checked here.
    employer = [c for c in first["cash_flow"]["contributions"] if c.get("source") == "employer"]
    assert [c["account_id"] for c in employer] == [accounts["roth_401k"]["id"]]
    assert 0 < employer[0]["amount"] <= 6_000
    # Resaving the unchanged rules keeps them.
    items = [{k: v for k, v in item.items() if k not in ("id", "plan_id")} for item in listed]
    r = await save_priorities(client, plan["id"], items)
    assert r.status_code == 200, r.text


async def test_roth_match_without_a_roth_account_is_rejected(client):
    plan, accounts, wage = await _plan_with(client, "traditional_401k")
    rule = {"priority_rank": 1, "priority_type": "income_percent", "target_account_id": accounts["traditional_401k"]["id"],
            "source_income_id": wage["id"], "employee_rate": 6, "employer_match": MATCH}
    r = await save_priorities(client, plan["id"], [rule])
    assert r.status_code == 422
    assert "add a Roth 401(k)" in r.json()["error"]["message"]
    r = await save_priorities(client, plan["id"], [{**rule, "employer_match": {**MATCH, "roth": False}}])
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("change, message", [
    ({"employer_match_rate": 3}, "not both"),
    ({"priority_type": "pre_tax_contribution"}, "only to income_percent"),
    ({"limit_mode": "custom"}, "needs custom_annual_limit"),
    ({"custom_annual_limit": 5_000}, "requires limit_mode"),
    ({"employer_match": {"tiers": [{"match_percent": 100, "up_to_percent_of_pay": 60},
                                   {"match_percent": 50, "up_to_percent_of_pay": 50}]}}, "more than 100% of pay"),
])
async def test_invalid_formulas_use_the_error_envelope(client, change, message):
    plan, accounts, wage = await _plan_with(client, "traditional_401k")
    rule = {"priority_rank": 1, "priority_type": "income_percent", "target_account_id": accounts["traditional_401k"]["id"],
            "source_income_id": wage["id"], "employee_rate": 6, "employer_match": {**MATCH, "roth": False}, **change}
    r = await save_priorities(client, plan["id"], [rule])
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert message in str(body)


async def test_account_fee_and_reinvest_settings_round_trip(client):
    settings = {"annual_fee_rate": 0.002, "annual_fee_amount": 250, "fee_percent_of_earnings": 0.1,
                "reinvest_income": False}
    r = await client.post("/api/accounts", json={"name": "Brokerage", "account_type": "taxable_brokerage",
                                                 "balance": 10_000, "investment_settings": settings})
    assert r.status_code == 201, r.text
    stored = r.json()["investment_settings"]
    assert {key: stored[key] for key in settings} == settings
    # A client that omits the new keys keeps them.
    r = await client.put(f"/api/accounts/{r.json()['id']}", json={"investment_settings": {"annual_fee_rate": 0.003}})
    assert r.status_code == 200, r.text
    assert r.json()["investment_settings"]["annual_fee_amount"] == 250
    assert r.json()["investment_settings"]["reinvest_income"] is False


async def test_stateless_request_carries_the_formula(client):
    body = {
        "plan_id": "00000000-0000-0000-0000-000000000a7d", "birth_year": 1986, "start_year": 2026,
        "first_year_fraction": 1.0, "life_expectancy": 50, "state_code": "TX",
        "assumptions": {"inflation_rate": 0, "stock_growth_rate": 0, "bond_return_rate": 0},
        "accounts": {"chk": {"balance": 50_000, "account_type": "checking", "name": "Chk"},
                     "k": {"balance": 0, "account_type": "traditional_401k", "name": "401k"}},
        "income_streams": [{"id": "w", "name": "Salary", "annual_amount": 100_000, "is_earned_income": True}],
        "priorities": [{"priority_rank": 1, "priority_type": "income_percent", "target_account_id": "k",
                        "source_income_id": "w", "employee_rate": 3,
                        "employer_match": {"tiers": [{"match_percent": 100, "up_to_percent_of_pay": 6}]}}],
    }
    r = await client.post("/api/simulate/stateless", json=body)
    assert r.status_code == 200, r.text
    # $3,000 deferred and matched dollar for dollar.
    assert r.json()["yearly_snapshots"][0]["accounts"]["k"] == pytest.approx(6_000)
