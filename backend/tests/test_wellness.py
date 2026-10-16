"""Financial wellness scorecard (coastmath.engine.wellness).

Expected values are computed here from the projection's own snapshots, not
through the module's helpers.
"""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine import wellness as w
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    MilestoneData,
    PlanData,
    PriorityData,
)
from coastmath.engine.wellness import Bands, grade, savings_target, wellness_scorecard
from coastmath.schemas.simulation import (
    CashFlowBreakdownSchema,
    NamedAmountSchema,
    YearSnapshot,
)

KEYS = ["savings_rate", "emergency_fund", "debt_to_income", "savings_to_income", "withdrawal_rate",
        "guaranteed_income", "pre_tax_share", "funded_years", "fi_timing"]
FLAT = AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0,
                      stock_dividend_yield=0.0, cash_yield_rate=0.0)


def _plan(**overrides) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=90, start_year=2026,
        milestones=[MilestoneData(id="ret", name="Retirement", trigger_type="age", trigger_value=60)],
        income_streams=[
            IncomeData(id="w", name="Salary", annual_amount=100_000, end_milestone_id="ret"),
            IncomeData(id="ss", name="Social Security", annual_amount=24_000, tax_category="social_security",
                       claiming_age=67),
        ],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000, category="essential"),
                  ExpenseData(id="f", name="Fun", annual_amount=10_000, category="discretionary")],
        liabilities=[LiabilityData(id="l", name="Car loan", principal_balance=20_000, interest_rate=0.05,
                                   monthly_payment=500)],
        accounts={"c": AccountInfo(balance=30_000, account_type="checking", name="Cash"),
                  "k": AccountInfo(balance=200_000, account_type="traditional_401k", name="401k"),
                  "b": AccountInfo(balance=100_000, account_type="taxable_brokerage", name="Brokerage")},
        drawdown_order=[DrawdownEntryData(1, "c"), DrawdownEntryData(2, "b"), DrawdownEntryData(3, "k")],
        assumptions=FLAT,
    )
    values.update(overrides)
    return PlanData(**values)


def _score(plan: PlanData):
    result = run_simulation(plan)
    card = wellness_scorecard(plan, result)
    return result, {m.key: m for m in card.metrics}, card


def _withdrawn(snap) -> float:
    return (sum(row.amount for row in snap.cash_flow.drawdowns)
            + sum(row.amount for row in snap.cash_flow.income_sources if row.source in ("rmd", "sepp")))


def test_hand_checked_plan_reads_each_metric_from_the_projection():
    plan = _plan()
    result, m, card = _score(plan)
    snaps = {s.year: s for s in result.yearly_snapshots}
    first = result.yearly_snapshots[0]
    assert card.start_year == 2026 and [x.key for x in card.metrics] == KEYS

    # No payroll saving: the positive surplus over gross income.
    assert m["savings_rate"].value == pytest.approx(max(0.0, first.net_cash_flow) / first.gross_income)
    assert (m["savings_rate"].basis_year, m["savings_rate"].unit, m["savings_rate"].section) == (2026, "percent", "income_allocation")
    # 30,000 cash over (40,000 living + 6,000 car loan) / 12.
    assert m["emergency_fund"].value == pytest.approx(30_000 / (46_000 / 12))
    assert m["emergency_fund"].status == "strong"
    assert m["debt_to_income"].value == pytest.approx(6_000 / 100_000)
    assert m["debt_to_income"].status == "strong"
    # 330,000 saved / 100,000 salary; the car loan is not subtracted. Age 46
    # target 3 + 3 x 6/10.
    assert m["savings_to_income"].value == pytest.approx(3.3)
    assert m["savings_to_income"].bands == Bands("higher", 2.4, 4.8)
    assert m["savings_to_income"].status == "fair"

    # Retirement fires in 2040 (age 60): the first retirement year is 2041,
    # read against 2040's closing balances.
    assert m["withdrawal_rate"].basis_year == 2041
    assert m["withdrawal_rate"].value == pytest.approx(_withdrawn(snaps[2041]) / sum(snaps[2040].accounts.values()))
    assert m["pre_tax_share"].basis_year == 2041
    closing = snaps[2040].accounts
    assert m["pre_tax_share"].value == pytest.approx(closing["k"] / (closing["k"] + closing["b"]))
    # Social Security starts in 2047; 2048 is its first full year.
    ss_2048 = sum(r.amount for r in snaps[2048].cash_flow.income_sources if r.name == "Social Security")
    essential_2048 = sum(r.amount for r in snaps[2048].cash_flow.expenses if r.category == "essential")
    assert m["guaranteed_income"].basis_year == 2048
    assert m["guaranteed_income"].value == pytest.approx(ss_2048 / essential_2048)

    short = [s.year for s in result.yearly_snapshots if s.unfunded_expenses > 0.5]
    assert short and m["funded_years"].basis_year == short[0]
    assert m["funded_years"].value == pytest.approx((short[0] - 2026) / len(result.yearly_snapshots))
    assert result.metadata.fi_estimate.year is None
    assert m["fi_timing"].value is None and m["fi_timing"].status == "needs_attention"
    assert m["fi_timing"].bands == Bands("lower", 2045.0, 2040.0) and m["fi_timing"].basis_year == 2040


THRESHOLDS = [
    ("higher", w.SAVINGS_RATE_FAIR, w.SAVINGS_RATE_STRONG),
    ("higher", w.EMERGENCY_FUND_FAIR, w.EMERGENCY_FUND_STRONG),
    ("lower", w.DEBT_TO_INCOME_FAIR, w.DEBT_TO_INCOME_STRONG),
    ("lower", w.WITHDRAWAL_RATE_FAIR, w.WITHDRAWAL_RATE_STRONG),
    ("higher", w.GUARANTEED_INCOME_FAIR, w.GUARANTEED_INCOME_STRONG),
    ("lower", w.PRE_TAX_SHARE_FAIR, w.PRE_TAX_SHARE_STRONG),
    ("higher", w.FUNDED_YEARS_FAIR, w.FUNDED_YEARS_STRONG),
    ("higher", 2.4, 4.8),
    ("lower", 2045.0, 2040.0),
]


@pytest.mark.parametrize("better,fair,strong", THRESHOLDS)
def test_each_band_grades_at_and_around_both_thresholds(better, fair, strong):
    bands = Bands(better, fair, strong)
    step = 1e-6 if better == "higher" else -1e-6
    assert grade(strong, bands) == "strong"
    assert grade(strong + step, bands) == "strong"
    assert grade(strong - step, bands) == "fair"
    assert grade(fair, bands) == "fair"
    assert grade(fair + step, bands) == "fair"
    assert grade(fair - step, bands) == "needs_attention"
    assert grade(None, bands) == "needs_attention"


@pytest.mark.parametrize("age,target", [(20, 0.0), (25, 0.0), (28, 0.6), (30, 1.0), (35, 2.0), (46, 4.8), (63, 8 + 2 * 3 / 7), (67, 10.0), (80, 10.0)])
def test_savings_target_follows_the_savings_by_age_points(age, target):
    assert savings_target(age) == pytest.approx(target)


def test_no_earned_income_has_no_savings_rate_or_income_multiple():
    _, m, _ = _score(_plan(income_streams=[]))
    assert m["savings_rate"].status == "not_applicable" and m["savings_rate"].value is None
    assert m["savings_rate"].bands is None and m["savings_rate"].basis_year is None
    assert m["savings_to_income"].status == "not_applicable"


def test_already_retired_reads_the_first_year_against_opening_balances():
    plan = _plan(birth_year=1960, milestones=[MilestoneData(id="ret", name="Retirement", trigger_type="age", trigger_value=60)],
                 income_streams=[IncomeData(id="p", name="Pension", annual_amount=20_000, tax_category="qualified_pension")],
                 liabilities=[])
    result, m, _ = _score(plan)
    first = result.yearly_snapshots[0]
    assert m["savings_rate"].status == "not_applicable"
    assert m["fi_timing"].status == "not_applicable"
    assert m["withdrawal_rate"].basis_year == 2026
    assert m["withdrawal_rate"].value == pytest.approx(_withdrawn(first) / 330_000)
    assert m["pre_tax_share"].value == pytest.approx(200_000 / 300_000)
    # A pension is guaranteed income; the opening year needs no prior year.
    essential = sum(r.amount for r in first.cash_flow.expenses if r.category == "essential")
    assert m["guaranteed_income"].basis_year == 2026
    assert m["guaranteed_income"].value == pytest.approx(20_000 / essential)


def test_no_retirement_milestone_leaves_retirement_metrics_not_applicable():
    _, m, _ = _score(_plan(milestones=[MilestoneData(id="kid", name="College", trigger_type="age", trigger_value=60)],
                           income_streams=[IncomeData(id="w", name="Salary", annual_amount=100_000)]))
    for key in ("withdrawal_rate", "guaranteed_income", "pre_tax_share", "fi_timing"):
        assert m[key].status == "not_applicable", key
    assert m["savings_rate"].status != "not_applicable"


def test_retirement_in_the_last_year_has_no_first_retirement_year():
    _, m, _ = _score(_plan(milestones=[MilestoneData(id="ret", name="Retirement", trigger_type="age", trigger_value=89)]))
    assert m["withdrawal_rate"].status == "not_applicable"
    assert m["pre_tax_share"].status == "not_applicable"
    assert m["fi_timing"].status != "not_applicable"


def test_no_debt_has_no_debt_ratio():
    _, m, _ = _score(_plan(liabilities=[]))
    assert m["debt_to_income"].status == "not_applicable"


def test_no_essential_spending_has_no_emergency_fund_or_coverage():
    _, m, _ = _score(_plan(liabilities=[], expenses=[ExpenseData(id="f", name="Fun", annual_amount=30_000,
                                                                 category="discretionary")]))
    assert m["emergency_fund"].status == "not_applicable"
    assert m["guaranteed_income"].status == "not_applicable"


def test_no_accounts_means_no_emergency_fund_and_nothing_invested():
    result, m, _ = _score(_plan(accounts={}, drawdown_order=[], liabilities=[]))
    assert m["emergency_fund"].value == 0 and m["emergency_fund"].status == "needs_attention"
    # The surplus collects in the engine's own cash account: liquid, not invested.
    closing = {s.year: s for s in result.yearly_snapshots}[2040].accounts
    assert set(closing) == {"unallocated_cash"}
    assert m["withdrawal_rate"].status != "not_applicable"
    assert m["pre_tax_share"].status == "not_applicable"


def test_no_accounts_and_no_income_means_no_portfolio_at_retirement():
    plan = _plan(accounts={}, drawdown_order=[], liabilities=[], income_streams=[])
    _, m, _ = _score(plan)
    assert m["withdrawal_rate"].status == "not_applicable"
    assert m["pre_tax_share"].status == "not_applicable"
    assert m["savings_to_income"].status == "not_applicable"


def test_partial_first_year_annualizes_flows_against_balances():
    plan = _plan(first_year_fraction=0.5, birth_year=1960, liabilities=[],
                 milestones=[MilestoneData(id="ret", name="Retirement", trigger_type="age", trigger_value=60)],
                 income_streams=[])
    result, m, _ = _score(plan)
    first = result.yearly_snapshots[0]
    assert result.metadata.first_year_fraction == 0.5
    essential = sum(r.amount for r in first.cash_flow.expenses if r.category == "essential")
    assert essential == pytest.approx(20_000)  # half of 40,000
    assert m["emergency_fund"].value == pytest.approx(30_000 / (essential / 6))
    assert m["withdrawal_rate"].value == pytest.approx(_withdrawn(first) / 0.5 / 330_000)

    worker = _plan(first_year_fraction=0.5)
    result, m, _ = _score(worker)
    first = result.yearly_snapshots[0]
    assert first.gross_income == pytest.approx(50_000)
    assert m["savings_to_income"].value == pytest.approx(330_000 / (50_000 / 0.5))
    assert m["savings_rate"].value == pytest.approx(max(0.0, first.net_cash_flow) / first.gross_income)


def test_couple_uses_the_plan_holders_retirement_and_both_salaries():
    plan = _plan(
        filing_status="married_filing_jointly", spouse_birth_year=1982, spouse_life_expectancy=90,
        milestones=[MilestoneData(id="pret", name="Partner retirement", trigger_type="age", trigger_value=55),
                    MilestoneData(id="ret", name="Retirement", trigger_type="age", trigger_value=62)],
        income_streams=[IncomeData(id="w", name="Salary", annual_amount=100_000, end_milestone_id="ret"),
                        IncomeData(id="s", name="Partner salary", annual_amount=50_000, owner="spouse",
                                   end_milestone_id="pret")],
    )
    result, m, _ = _score(plan)
    first = result.yearly_snapshots[0]
    assert m["withdrawal_rate"].basis_year == 2043
    assert m["fi_timing"].bands.strong_at == 2042
    assert m["savings_rate"].value == pytest.approx(max(0.0, first.net_cash_flow) / first.gross_income)
    assert first.gross_income == pytest.approx(150_000)


def test_country_regime_plan_uses_country_account_categories_and_benefits(fixture_pack):
    plan = PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1963, filing_status="single", life_expectancy=85, start_year=2026,
        tax_country="QZ", tax_region="N", currency="EUR", assumptions=FLAT,
        milestones=[MilestoneData(id="ret", name="Retire", trigger_type="age", trigger_value=65)],
        income_streams=[IncomeData(id="job", name="Job", annual_amount=80_000, end_milestone_id="ret")],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=36_000, category="essential")],
        accounts={"cash": AccountInfo(20_000, "savings", name="Cash"),
                  "saver": AccountInfo(300_000, "other", name="Pension saver", intl_account_kind="QZ:pension_saver"),
                  "free": AccountInfo(100_000, "other", name="Free saver", intl_account_kind="QZ:free_saver")},
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "free"), DrawdownEntryData(3, "saver")],
        intl_settings={"benefits": [
            {"rule": "QZ:basic_pension", "owner": "self", "start_age": 65, "params": {"monthly_amount": 1_500}},
        ]},
    )
    result, m, _ = _score(plan)
    snaps = {s.year: s for s in result.yearly_snapshots}
    first = result.yearly_snapshots[0]
    assert m["emergency_fund"].value == pytest.approx(20_000 / (36_000 / 12))
    assert m["savings_rate"].value == pytest.approx(max(0.0, first.net_cash_flow) / first.gross_income)
    ret_year = next(o.year for o in result.metadata.milestone_outcomes if o.id == "ret")
    assert ret_year == 2028  # age 65
    basis = m["pre_tax_share"].basis_year
    assert basis == ret_year + 1
    closing = snaps[ret_year].accounts
    assert m["pre_tax_share"].value == pytest.approx(closing["saver"] / (closing["saver"] + closing["free"]))
    benefits = {"Basic pension"}
    year = m["guaranteed_income"].basis_year
    assert year == 2029
    assert m["withdrawal_rate"].value == pytest.approx(_withdrawn(snaps[2029]) / sum(closing.values()))
    paid = sum(r.amount for r in snaps[year].cash_flow.income_sources if r.name in benefits)
    assert paid > 0
    essential = sum(r.amount for r in snaps[year].cash_flow.expenses if r.category == "essential")
    assert m["guaranteed_income"].value == pytest.approx(paid / essential)


def test_a_loan_named_like_an_expense_counts_only_the_loan_rows():
    plan = _plan(expenses=[ExpenseData(id="e", name="Car loan", annual_amount=40_000, category="essential")])
    result, m, _ = _score(plan)
    assert m["debt_to_income"].value == pytest.approx(6_000 / 100_000)
    # Both rows are essential spending.
    assert m["emergency_fund"].value == pytest.approx(30_000 / (46_000 / 12))


def test_discretionary_percent_and_uncategorized_expenses():
    plan = _plan(liabilities=[], expenses=[
        ExpenseData(id="a", name="Housing", annual_amount=24_000, category="essential", discretionary_fraction=0.25),
        ExpenseData(id="b", name="Misc", annual_amount=6_000),
        ExpenseData(id="c", name="Travel", annual_amount=10_000, category="discretionary"),
    ])
    _, m, _ = _score(plan)
    # 24,000 x 0.75 + 6,000 uncategorized = 24,000 essential a year.
    assert m["emergency_fund"].value == pytest.approx(30_000 / (24_000 / 12))


def test_auxiliary_social_security_and_annuities_are_guaranteed_income():
    info = w._Plan(_plan(income_streams=[
        IncomeData(id="ss", name="SS", annual_amount=1, tax_category="social_security"),
        IncomeData(id="a", name="Annuity", annual_amount=1, tax_category="nonqualified_annuity"),
        IncomeData(id="r", name="Rental", annual_amount=1, tax_category="other_ordinary"),
    ]))
    snap = YearSnapshot(year=2030, cash_flow=CashFlowBreakdownSchema(income_sources=[
        NamedAmountSchema(name="SS", amount=10), NamedAmountSchema(name="SS (spousal)", amount=5),
        NamedAmountSchema(name="Annuity", amount=3), NamedAmountSchema(name="Rental", amount=100),
        NamedAmountSchema(name="Social Security survivor top-up", amount=2),
    ]))
    assert info.guaranteed_income(snap) == 20
    assert w.essential_spending(YearSnapshot(year=2030)) == 0
    assert w.portfolio_withdrawals(YearSnapshot(year=2030)) == 0


def test_fi_before_retirement_is_strong_and_within_grace_is_fair():
    rich = _plan(liabilities=[], accounts={"b": AccountInfo(balance=2_000_000, account_type="taxable_brokerage", name="B")},
                 drawdown_order=[DrawdownEntryData(1, "b")])
    result, m, _ = _score(rich)
    assert result.metadata.fi_estimate.year is not None
    assert m["fi_timing"].value == result.metadata.fi_estimate.year
    assert m["fi_timing"].basis_year == result.metadata.fi_estimate.year
    assert m["fi_timing"].status == "strong"
    assert m["funded_years"].value == 1.0 and m["funded_years"].status == "strong"
    assert m["funded_years"].basis_year == result.yearly_snapshots[-1].year


def test_failure_year_without_unfunded_rows_still_ends_funding():
    plan = _plan()
    result = run_simulation(plan)
    for snap in result.yearly_snapshots:
        snap.unfunded_expenses = 0.0
    result.metadata.failure_year = 2070
    m = {x.key: x for x in wellness_scorecard(plan, result).metrics}
    assert m["funded_years"].basis_year == 2070
    assert m["funded_years"].value == pytest.approx((2070 - 2026) / len(result.yearly_snapshots))


def test_missing_initial_snapshot_and_fi_estimate_fall_back_to_plan_inputs():
    plan = _plan()
    result = run_simulation(plan)
    result.initial_snapshot = None
    result.metadata.fi_estimate = None
    m = {x.key: x for x in wellness_scorecard(plan, result).metrics}
    assert m["savings_to_income"].value == pytest.approx(3.3)
    assert m["fi_timing"].value is None and m["fi_timing"].status == "needs_attention"


def test_savings_rate_counts_payroll_deferrals_and_employer_money_but_not_payroll_expenses():
    plan = _plan(
        liabilities=[],
        income_streams=[IncomeData(id="w", name="Salary", annual_amount=100_000, end_milestone_id="ret")],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000, category="essential"),
                  ExpenseData(id="p", name="Premium", annual_amount=2_000, is_payroll_deduction=True, tied_income_id="w")],
        priorities=[PriorityData(priority_rank=1, target_account_id="k", priority_type="income_percent",
                                 source_income_id="w", employee_rate=0.15, employer_match_rate=0.05)],
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0.2, "capital_gains_tax_rate": 0.15},
    )
    result, m, _ = _score(plan)
    first = result.yearly_snapshots[0]
    # 15% of 100,000 deferred and 5% from the employer, which gross income includes.
    assert first.gross_income == pytest.approx(105_000)
    expected = (15_000 + 5_000 + max(0.0, first.net_cash_flow)) / 105_000
    assert m["savings_rate"].value == pytest.approx(expected)
    # The surplus alone (the older dashboard figure) understates it by the payroll saving.
    assert m["savings_rate"].value - max(0.0, first.net_cash_flow) / 105_000 == pytest.approx(20_000 / 105_000)


def test_savings_to_income_uses_earned_income_and_ignores_a_mortgage():
    plan = _plan(
        birth_year=1986, milestones=[], income_streams=[IncomeData(id="w", name="Salary", annual_amount=100_000)],
        liabilities=[LiabilityData(id="m", name="Mortgage", principal_balance=400_000, interest_rate=0.05, monthly_payment=2_500)],
        accounts={"b": AccountInfo(balance=500_000, account_type="taxable_brokerage", name="B"),
                  "e": AccountInfo(balance=50_000, account_type="five_twenty_nine", name="529")},
        drawdown_order=[DrawdownEntryData(1, "b")],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0,
                                   stock_dividend_yield=0.02, cash_yield_rate=0.0),
    )
    result, m, _ = _score(plan)
    first = result.yearly_snapshots[0]
    # Dividends raise gross income but not the salary the target is set against.
    assert first.gross_income > 100_000
    assert m["savings_to_income"].value == pytest.approx(500_000 / 100_000)
    assert m["savings_to_income"].bands == Bands("higher", 1.5, 3.0)
    assert m["savings_to_income"].status == "strong"


def test_saved_from_income_without_a_breakdown():
    assert w.saved_from_income(YearSnapshot(year=2030, net_cash_flow=-5)) == 0
    assert w.saved_from_income(YearSnapshot(year=2030, net_cash_flow=7)) == 7
