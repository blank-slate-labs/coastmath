"""Plan accuracy checklist rules: applicability, weights, score and review items."""

import copy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.milestone import MilestoneConditions
from coastmath.engine.plan_checks import (
    CHECK_WEIGHTS,
    INFLATION_REVIEW_BELOW,
    REAL_STOCK_RETURN_REVIEW_ABOVE,
    CheckResult,
    evaluate_plan_checks,
    score,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
)

RETIRE = MilestoneData("ret", "Retire", "age", trigger_value=67)


def ss(owner="self", amount=30_000, **kw):
    return IncomeData(f"ss_{owner}", f"Social Security {owner}", amount, tax_category="social_security",
                      owner=owner, claiming_age=67, **kw)


def salary(owner="self", end="ret", **kw):
    return IncomeData(f"wage_{owner}", f"Acme {owner}", 100_000, owner=owner, end_milestone_id=end, **kw)


def plan(**kw) -> PlanData:
    data = dict(
        plan_id=str(uuid4()), birth_year=1980, filing_status="single", life_expectancy=90, start_year=2026,
        accounts={"cash": AccountInfo(50_000, "checking"),
                  "brok": AccountInfo(100_000, "taxable_brokerage", cost_basis=80_000, name="Brokerage")},
        income_streams=[salary(), ss()],
        milestones=[RETIRE],
        expenses=[ExpenseData("living", "Living", 60_000)],
    )
    data.update(kw)
    return PlanData(**data)


def outcomes(**years):
    """Milestone outcomes as the projection reports them: id -> fired year (None = never)."""
    return [SimpleNamespace(id=mid, name=mid.title(), year=year, missed_year=None) for mid, year in years.items()]


def evaluate(p, fired=None, **kw):
    return evaluate_plan_checks(p, outcomes(**(fired if fired is not None else {"ret": 2047})), **kw)


def by_key(result):
    return {c.key: c.passes for c in result.checks}


def keys(result):
    return [i.key for i in result.items]


# --- Score ---------------------------------------------------------------

def test_score_is_weighted_share_rounded_half_up_and_100_when_nothing_applies():
    assert score([]) == 100
    assert score([CheckResult("a", 0, False)]) == 100
    assert score([CheckResult("a", 1, True), CheckResult("b", 1, False)]) == 50
    assert score([CheckResult("a", 1, True), CheckResult("b", 7, False)]) == 13  # 12.5 rounds up
    assert score([CheckResult("a", 2, True), CheckResult("b", 1, False)]) == 67


def test_weights_put_accounts_spending_and_social_security_first():
    assert list(CHECK_WEIGHTS) == sorted(CHECK_WEIGHTS, key=lambda k: -CHECK_WEIGHTS[k])
    assert CHECK_WEIGHTS["accounts_entered"] == CHECK_WEIGHTS["expenses_entered"] == 20
    assert sum(CHECK_WEIGHTS.values()) == 95
    assert "cost_basis_entered" not in CHECK_WEIGHTS


def test_complete_single_plan_scores_100_with_no_items():
    result = evaluate(plan(healthcare_settings={"enabled": True}))
    assert result.score == 100 and result.items == []
    # Pre-Medicare coverage does not apply: work ends at 67.
    assert by_key(result) == {"accounts_entered": True, "expenses_entered": True, "social_security_self": True,
                              "earned_income_ends": True}


# --- Accounts and expenses ------------------------------------------------

def test_accounts_and_expenses_always_apply():
    result = evaluate(plan(accounts={"cash": AccountInfo(0, "checking")}, expenses=[ExpenseData("x", "Zero", 0)]))
    assert by_key(result)["accounts_entered"] is False and by_key(result)["expenses_entered"] is False
    assert [(i.key, i.section, i.title) for i in result.items[:2]] == [
        ("accounts_entered", "accounts", "No account balances"), ("expenses_entered", "expenses", "No expenses")]
    # Social Security and the salary end pass (25 of 65); cost basis needs a taxable balance.
    assert result.score == round(100 * 25 / 65)


# --- Social Security --------------------------------------------------------

def test_social_security_for_each_person_in_a_us_plan():
    p = plan(spouse_birth_year=1982, spouse_life_expectancy=92, filing_status="married_filing_jointly")
    result = evaluate(p)
    assert by_key(result)["social_security_spouse"] is False
    [item] = [i for i in result.items if i.key == "social_security_spouse"]
    assert (item.title, item.person, item.section, item.kind) == (
        "No Social Security for your partner", "spouse", "income", "missing")
    result = evaluate(plan(income_streams=[salary()]))
    assert [i.title for i in result.items] == ["No Social Security for you"]


def test_inactive_social_security_does_not_count():
    result = evaluate(plan(income_streams=[salary(), ss(is_active=False)]))
    assert by_key(result)["social_security_self"] is False


def test_social_security_not_applicable_to_country_regime_plans():
    result = evaluate(plan(income_streams=[salary()], tax_country="QZ", currency="EUR"))
    assert "social_security_self" not in by_key(result)
    assert "pre_medicare_coverage" not in by_key(result)


def test_no_spouse_check_without_a_partner():
    assert "social_security_spouse" not in by_key(evaluate(plan()))


# --- Earned income ends ------------------------------------------------------

def test_salary_without_end_or_with_unfired_end_fails():
    p = plan(income_streams=[salary(end=None), ss()])
    result = evaluate(p)
    assert by_key(result)["earned_income_ends"] is False
    [item] = result.items
    assert (item.title, item.target_id, item.person) == ("Salary never ends: Acme self", "wage_self", "self")
    # An end milestone that never fires in the projection leaves the salary running.
    assert by_key(evaluate(plan(), fired={"ret": None}))["earned_income_ends"] is False


def test_earned_income_check_skips_one_time_inactive_zero_and_never_starting_pay():
    streams = [
        IncomeData("bonus", "Bonus", 10_000, frequency="once"),
        IncomeData("old", "Old job", 50_000, is_active=False),
        IncomeData("zero", "Zero", 0),
        IncomeData("later", "Later", 50_000, start_milestone_id="fi"),
        IncomeData("pension", "Pension", 20_000, tax_category="qualified_pension"),
        ss(),
    ]
    fi = MilestoneData("fi", "FI", "net_worth", trigger_value=10**9)
    result = evaluate(plan(income_streams=streams, milestones=[RETIRE, fi]), fired={"ret": 2047, "fi": None})
    assert "earned_income_ends" not in by_key(result)


def test_spouse_salary_item_names_the_partner():
    p = plan(spouse_birth_year=1982, spouse_life_expectancy=92, income_streams=[salary(), salary("spouse", None), ss(), ss("spouse")])
    [item] = evaluate(p).items
    assert (item.key, item.person, item.target_id) == ("earned_income_ends", "spouse", "wage_spouse")


# --- Pre-Medicare coverage --------------------------------------------------

def early(**kw):
    return plan(milestones=[MilestoneData("ret", "Retire", "age", trigger_value=55)], **kw)


def test_coverage_needed_when_work_ends_before_65():
    result = evaluate(early(), fired={"ret": 2035})
    assert by_key(result)["pre_medicare_coverage"] is False
    [item] = result.items
    assert (item.title, item.section, item.person) == ("No coverage before Medicare", "healthcare", "self")


@pytest.mark.parametrize("settings, passes", [
    ({"enabled": False, "aca_enabled": True}, False),
    ({"enabled": True}, False),
    ({"enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 9000, "aca_plan_premium_annual": 8000}, True),
    ({"enabled": True, "persons": [{"owner": "self", "mode": "itemized", "itemized_annual_amount": 12000}]}, True),
    ({"enabled": True, "persons": [{"owner": "self", "mode": "off"}]}, False),
    ({"enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 9000, "aca_plan_premium_annual": 8000,
      "persons": [{"owner": "self", "mode": "coverage", "aca_enabled": False}]}, False),
    ({"enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 9000, "aca_plan_premium_annual": 8000,
      "persons": [{"owner": "self", "mode": "coverage", "aca_enabled": True}]}, True),
])
def test_what_counts_as_pre_medicare_coverage(settings, passes):
    assert by_key(evaluate(early(healthcare_settings=settings), fired={"ret": 2035}))["pre_medicare_coverage"] is passes


def test_coverage_boundary_at_medicare_age_and_override_age():
    # Work ends the year the owner turns 65: not applicable; 64: applicable.
    assert "pre_medicare_coverage" not in by_key(evaluate(early(), fired={"ret": 2045}))
    assert "pre_medicare_coverage" in by_key(evaluate(early(), fired={"ret": 2044}))
    late_enrollment = {"enabled": True, "persons": [{"owner": "self", "mode": "coverage", "medicare_start_age": 67}]}
    result = evaluate(early(healthcare_settings=late_enrollment), fired={"ret": 2046})
    assert by_key(result)["pre_medicare_coverage"] is False


def test_no_earned_income_means_coverage_from_plan_start():
    result = evaluate(plan(income_streams=[ss()]), fired={})
    assert by_key(result)["pre_medicare_coverage"] is False
    assert "earned_income_ends" not in by_key(result)


def test_partner_coverage_uses_household_work_end_and_marketplace_spouse_flag():
    aca = {"enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 9000, "aca_plan_premium_annual": 8000}
    p = early(spouse_birth_year=1990, spouse_life_expectancy=92, income_streams=[salary(), ss(), ss("spouse")],
              healthcare_settings={**aca, "aca_cover_spouse": False})
    result = evaluate(p, fired={"ret": 2035})
    [item] = result.items
    assert (item.title, item.person) == ("No partner coverage before Medicare", "spouse")
    p.healthcare_settings = aca
    assert evaluate(p, fired={"ret": 2035}).items == []


def test_coverage_skipped_while_any_salary_never_ends_or_after_death():
    result = evaluate(early(income_streams=[salary(end=None), ss()]))
    assert "pre_medicare_coverage" not in by_key(result)
    # A partner past their longevity when work ends needs no coverage.
    p = early(spouse_birth_year=1940, spouse_life_expectancy=90, income_streams=[salary(), ss(), ss("spouse")])
    assert [i.person for i in evaluate(p, fired={"ret": 2035}).items] == ["self"]


# --- Cost basis and connected balances ----------------------------------------

def test_blank_cost_basis_on_taxable_accounts_is_an_unscored_review_item():
    accounts = {
        "brok": AccountInfo(100_000, "taxable_brokerage", name="Brokerage"),
        "coin": AccountInfo(5_000, "cryptocurrency", cost_basis=1_000, name="Coins"),
        "empty": AccountInfo(0, "taxable_brokerage"),
        "abroad": AccountInfo(10_000, "taxable_brokerage", intl_account_kind="QZ:general"),
        "ira": AccountInfo(10_000, "traditional_ira"),
    }
    result = evaluate(plan(accounts=accounts))
    [item] = result.items
    assert (item.key, item.kind, item.title, item.target_id, item.section) == (
        "cost_basis_assumed", "review", "Basis assumed equal to balance: Brokerage", "brok", "accounts")
    assert result.score == 100
    assert "cost_basis_entered" not in by_key(result)
    unnamed = evaluate(plan(accounts={"b": AccountInfo(1, "taxable_brokerage")}))
    assert unnamed.items[0].title == "Basis assumed equal to balance: Taxable account"
    assert evaluate(plan(accounts={"c": AccountInfo(1, "checking")})).items == []


def test_connected_balances_apply_only_to_linked_plan_accounts():
    assert "balances_current" not in by_key(evaluate(plan()))
    assert "balances_current" not in by_key(evaluate(plan(), balance_current={"elsewhere": False}))
    result = evaluate(plan(), balance_current={"cash": True, "brok": False})
    assert by_key(result)["balances_current"] is False
    [item] = result.items
    assert (item.title, item.target_id) == ("Stale balance: Brokerage", "brok")
    assert evaluate(plan(accounts={"x": AccountInfo(1, "checking")}), balance_current={"x": False}).items[0].title == "Stale balance: Account"
    assert by_key(evaluate(plan(), balance_current={"cash": True}))["balances_current"] is True


# --- Review: assumptions ------------------------------------------------------

def test_real_stock_return_threshold_counts_dividends_and_flags_only_above():
    # (1 + growth + dividend) / (1 + inflation) - 1 exactly at the threshold is not flagged.
    at = (1 + REAL_STOCK_RETURN_REVIEW_ABOVE) * 1.03 - 1
    assert keys(evaluate(plan(assumptions=AssumptionData(stock_growth_rate=at - 0.02, stock_dividend_yield=0.02)))) == []
    above = evaluate(plan(assumptions=AssumptionData(stock_growth_rate=at - 0.02 + 1e-4, stock_dividend_yield=0.02)))
    [item] = above.items
    assert (item.key, item.kind, item.section, item.title) == (
        "high_real_stock_return", "review", "assumptions", "Stock return over 8% after inflation")
    assert above.score == 100  # review items are unscored


def test_inflation_floor_flags_only_below():
    assert keys(evaluate(plan(assumptions=AssumptionData(inflation_rate=INFLATION_REVIEW_BELOW, stock_growth_rate=0.05)))) == []
    [item] = evaluate(plan(assumptions=AssumptionData(inflation_rate=0.0099, stock_growth_rate=0.05))).items
    assert (item.key, item.title) == ("low_inflation", "Inflation under 1%")


def test_assumption_curves_are_checked_in_every_projected_year():
    curve = AssumptionCurveData("inflation", mode="curve", control_points=[{"x": 46, "y": 0.03}, {"x": 80, "y": 0.005}])
    assert keys(evaluate(plan(assumption_curves=[curve]))) == ["low_inflation"]
    fixed = AssumptionCurveData("market_return", fixed_rate=0.2)
    assert keys(evaluate(plan(assumption_curves=[fixed]))) == ["high_real_stock_return"]


# --- Review: events and milestones --------------------------------------------

def test_event_never_runs_when_start_never_fires_or_follows_end():
    fi = MilestoneData("fi", "FI", "net_worth", trigger_value=10**9)
    off = MilestoneData("off", "Off", "age", trigger_value=50, is_active=False)
    late = MilestoneData("late", "Late", "age", trigger_value=70)
    expenses = [ExpenseData("living", "Living", 60_000),
                ExpenseData("travel", "Travel", 5_000, start_milestone_id="fi"),
                ExpenseData("gap", "Gap", 5_000, start_milestone_id="late", end_milestone_id="ret"),
                ExpenseData("same", "Same", 5_000, start_milestone_id="ret", end_milestone_id="ret"),
                ExpenseData("switched", "Switched off", 5_000, start_milestone_id="off")]
    streams = [salary(), ss(), IncomeData("side", "Side gig", 1_000, start_milestone_id="fi", is_earned_income=False),
               IncomeData("idle", "Idle", 1_000, start_milestone_id="fi", is_active=False)]
    p = plan(milestones=[RETIRE, fi, off, late], expenses=expenses, income_streams=streams)
    result = evaluate(p, fired={"ret": 2047, "fi": None, "off": None, "late": 2050})
    assert [(i.key, i.section, i.title, i.target_id) for i in result.items] == [
        ("event_never_runs", "income", "Never runs: Side gig", "side"),
        ("event_never_runs", "expenses", "Never runs: Travel", "travel"),
        ("event_never_runs", "expenses", "Never runs: Gap", "gap"),
    ]


def test_missed_milestone_from_projection_outcomes():
    goal = MilestoneData("goal", "Goal", "conditions", conditions=MilestoneConditions.model_validate({
        "combinator": "all", "deadline": {"kind": "year", "value": 2027, "action": "miss"},
        "items": [{"kind": "metric", "metric": "net_worth", "comparator": ">=", "value_unit": "dollars", "value": 10**9}],
    }).model_dump())
    p = plan(milestones=[RETIRE, goal], expenses=[ExpenseData("living", "Living", 60_000),
                                                  ExpenseData("boat", "Boat", 9_000, start_milestone_id="goal")])
    result = evaluate_plan_checks(p, run_simulation(copy.deepcopy(p)).metadata.milestone_outcomes)
    assert [(i.key, i.title, i.target_id) for i in result.items] == [
        ("event_never_runs", "Never runs: Boat", "boat"),
        ("milestone_missed", "Missed milestone: Goal", "goal"),
    ]
    # Synthetic or unknown outcomes are ignored.
    stray = [SimpleNamespace(id="x", name="X", year=None, missed_year=2030)]
    assert evaluate_plan_checks(plan(), stray + outcomes(ret=2047)).items == []


def test_zero_amount_social_security_is_a_review_item():
    streams = [salary(), ss(amount=0), ss("spouse", amount=0, ss_benefit_basis="pia", pia_monthly=2000)]
    p = plan(income_streams=streams, spouse_birth_year=1982, spouse_life_expectancy=90)
    result = evaluate(p)
    [item] = result.items
    assert (item.key, item.title, item.person, item.target_id) == ("zero_social_security", "Social Security is $0: Social Security self", "self", "ss_self")
    assert by_key(result)["social_security_self"] is True
    spouse_zero = evaluate(plan(income_streams=[salary(), ss(), ss("spouse", amount=0)], spouse_birth_year=1982, spouse_life_expectancy=90))
    assert spouse_zero.items[0].person == "spouse"


# --- Ordering ---------------------------------------------------------------

def test_items_order_missing_by_weight_then_review_in_fixed_order():
    p = plan(accounts={"brok": AccountInfo(100_000, "taxable_brokerage", name="B")}, expenses=[],
             income_streams=[salary(end=None), ss(amount=0)],
             spouse_birth_year=1982, spouse_life_expectancy=90,
             assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.2))
    result = evaluate(p)
    assert keys(result) == ["expenses_entered", "social_security_spouse", "earned_income_ends",
                            "high_real_stock_return", "low_inflation", "zero_social_security", "cost_basis_assumed"]
    assert [c.key for c in result.checks] == ["accounts_entered", "expenses_entered", "social_security_self",
                                              "social_security_spouse", "earned_income_ends"]
    assert result.score == round(100 * (20 + 15) / (20 + 20 + 15 + 15 + 10))
