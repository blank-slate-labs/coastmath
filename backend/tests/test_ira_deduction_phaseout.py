"""Traditional IRA deduction phase-out for workplace-plan participants.

IRC 219(g); Publication 590-A Worksheets 1-1 and 1-2; 2026 ranges from
IR-2025-111 / Notice 2025-67: covered single/HoH $81,000-$91,000, covered
joint $129,000-$149,000, spouse-only covered joint $242,000-$252,000,
separate return $0-$10,000. The full contribution is still deposited; only
the deduction shrinks.

Each integration case is checked against an independent hand computation on
the 2026 single brackets (10% to $12,400, 12% to $50,400, 22% to $105,700),
joint brackets (12% to $100,800, 22% to $211,400) and standard deductions
($16,100 single and separate, $32,200 joint), with zero inflation and growth.
A workplace plan is joined through an employer-only 401(k) contribution, which
never enters AGI, so it changes nothing but coverage.
"""
from __future__ import annotations

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
    RealAssetData,
)
from coastmath.engine.waterfall import traditional_ira_deduction_limit

_WARNING = "Traditional IRA contributions were only partly deductible"


def _limit(magi, status="single", *, covered=True, spouse_covered=False, age=34, factor=1.0, lived_apart=False):
    return traditional_ira_deduction_limit(age, status, magi, covered=covered, spouse_covered=spouse_covered,
                                           inflation_factor=factor, lived_apart=lived_apart)


# --- Worksheet 1-2 arithmetic -------------------------------------------------

@pytest.mark.parametrize("magi, expected", [
    (81_000, 7_500),   # at the start of the range: full deduction
    (86_000, 3_750),   # 7,500 x (91,000 - 86,000) / 10,000
    (86_003, 3_750),   # 3,747.75 rounds up to the next $10
    (90_800, 200),     # 150 is raised to the $200 minimum
    (90_990, 200),     # 7.50 is raised to the $200 minimum
    (91_000, 0),       # fully phased out
    (120_000, 0),
])
def test_single_covered_limit_follows_worksheet_1_2(magi, expected):
    assert _limit(magi) == pytest.approx(expected)


def test_head_of_household_uses_the_single_range():
    assert _limit(86_000, "head_of_household") == pytest.approx(3_750)


def test_age_50_catch_up_phases_out_with_the_base_limit():
    # (7,500 + 1,100) x 0.5 = 4,300.
    assert _limit(86_000, age=50) == pytest.approx(4_300)


def test_not_covered_is_fully_deductible_at_any_income():
    assert _limit(1_000_000, covered=False) == pytest.approx(7_500)
    assert _limit(1_000_000, "married_filing_jointly", covered=False) == pytest.approx(7_500)


def test_joint_return_contributor_covered_vs_only_spouse_covered():
    # Covered: 7,500 x (149,000 - 145,000) / 20,000 = 1,500.
    assert _limit(145_000, "married_filing_jointly") == pytest.approx(1_500)
    assert _limit(145_000, "qualifying_surviving_spouse") == pytest.approx(1_500)
    # Only the spouse covered: the range starts at 242,000.
    assert _limit(145_000, "married_filing_jointly", covered=False, spouse_covered=True) == pytest.approx(7_500)
    assert _limit(247_000, "married_filing_jointly", covered=False, spouse_covered=True) == pytest.approx(3_750)
    assert _limit(252_000, "married_filing_jointly", covered=False, spouse_covered=True) == 0
    # A spouse's coverage means nothing to an unmarried filer.
    assert _limit(1_000_000, "single", covered=False, spouse_covered=True) == pytest.approx(7_500)


def test_separate_return_range_and_living_apart():
    assert _limit(5_000, "married_filing_separately") == pytest.approx(3_750)
    assert _limit(10_000, "married_filing_separately") == 0
    # Spouse covered, living together: the same $0-$10,000 range.
    assert _limit(5_000, "married_filing_separately", covered=False, spouse_covered=True) == pytest.approx(3_750)
    # Lived apart all year: treated as single (IRC 219(g)(4)).
    assert _limit(86_000, "married_filing_separately", lived_apart=True) == pytest.approx(3_750)
    assert _limit(500_000, "married_filing_separately", covered=False, spouse_covered=True,
                  lived_apart=True) == pytest.approx(7_500)


def test_range_start_is_indexed_except_on_a_separate_return():
    # Factor 1.1: limit 8,250; single range 89,100-99,100. 8,250 x 0.5 = 4,125 -> 4,130.
    assert _limit(94_100, factor=1.1) == pytest.approx(4_130)
    # The separate-return range is not indexed: 0-10,000.
    assert _limit(5_000, "married_filing_separately", factor=1.1) == pytest.approx(4_130)


# --- Simulation ---------------------------------------------------------------

def _plan(salary, *, covered=False, spouse_covered=False, ira=7_500, filing_status="single",
          spouse_salary=0.0, extra_priorities=(), extra_accounts=None, **overrides) -> PlanData:
    priorities = list(extra_priorities)
    if covered:
        priorities.append(PriorityData(1, "k401", priority_type="income_percent", source_income_id="job",
                                       employer_match_rate=0.03))
    if spouse_covered:
        priorities.append(PriorityData(2, "spouse_k401", priority_type="income_percent",
                                       source_income_id="spouse_job", employer_match_rate=0.03))
    if ira:
        priorities.append(PriorityData(3, "trad", allocation_mode="amount", allocation_value=ira))
    priorities.append(PriorityData(4, "cash"))
    incomes = [IncomeData(id="job", name="Job", annual_amount=salary, growth_rate=0.0)]
    if spouse_salary:
        incomes.append(IncomeData(id="spouse_job", name="Spouse job", annual_amount=spouse_salary,
                                  growth_rate=0.0, owner="spouse"))
    accounts = {
        "k401": AccountInfo(0, "traditional_401k"),
        "spouse_k401": AccountInfo(0, "traditional_401k", owner="spouse"),
        "trad": AccountInfo(0, "traditional_ira"),
        "cash": AccountInfo(0, "checking"),
        **(extra_accounts or {}),
    }
    married = filing_status in ("married_filing_jointly", "married_filing_separately")
    # Two plan years (2026-2027): later RMD years would add warnings of their own.
    fields = dict(
        plan_id=str(uuid.uuid4()), birth_year=1992, filing_status=filing_status, life_expectancy=36,
        start_year=2026, spouse_birth_year=1992 if married else None, milestones=[], income_streams=incomes,
        expenses=[], priorities=priorities, drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0), accounts=accounts,
    )
    fields.update(overrides)
    return PlanData(**fields)


def _first(plan):
    result = run_simulation(plan)
    return result.yearly_snapshots[0], result.metadata.warnings


def _federal_delta(**kwargs):
    """Federal tax with workplace coverage less the same plan without it."""
    covered, covered_warnings = _first(_plan(**kwargs))
    uncovered_kwargs = {**kwargs, "covered": False, "spouse_covered": False}
    uncovered, uncovered_warnings = _first(_plan(**uncovered_kwargs))
    # The deposit is never cut back: the full contribution lands either way.
    assert covered.accounts["trad"] == pytest.approx(kwargs.get("ira", 7_500))
    assert uncovered.accounts["trad"] == pytest.approx(kwargs.get("ira", 7_500))
    assert not any(w.startswith(_WARNING) for w in uncovered_warnings)
    return covered.federal_tax - uncovered.federal_tax, covered_warnings


def test_single_covered_below_the_range_keeps_the_full_deduction():
    # MAGI 70,000 < 81,000.
    delta, warnings = _federal_delta(salary=70_000, covered=True)
    assert delta == pytest.approx(0, abs=0.01)
    assert not any(w.startswith(_WARNING) for w in warnings)


def test_single_covered_mid_range_hand_computed():
    # $7,500 contribution, single, covered, MAGI 86,000 -> deductible 3,750.
    # Taxable income 66,150 vs 62,400, both in the 22% bracket:
    # federal tax rises by 22% x 3,750 = 825 (8,440 -> 9,265).
    covered, warnings = _first(_plan(86_000, covered=True))
    uncovered, _ = _first(_plan(86_000))
    assert uncovered.federal_tax == pytest.approx(8_440)
    assert covered.federal_tax == pytest.approx(9_265)
    assert covered.federal_tax - uncovered.federal_tax == pytest.approx(0.22 * 3_750)
    assert any(w.startswith(_WARNING) for w in warnings)


def test_single_covered_above_the_range_deducts_nothing():
    # MAGI 95,000 >= 91,000: 22% x 7,500 = 1,650; equals having no IRA deduction.
    delta, warnings = _federal_delta(salary=95_000, covered=True)
    assert delta == pytest.approx(0.22 * 7_500)
    assert any(w.startswith(_WARNING) for w in warnings)
    no_ira, _ = _first(_plan(95_000, covered=True, ira=0))
    covered, _ = _first(_plan(95_000, covered=True))
    assert covered.federal_tax == pytest.approx(no_ira.federal_tax)


def test_single_covered_near_the_top_keeps_the_200_minimum():
    # MAGI 90,800: 150 -> 200 deductible, 7,300 not: 22% x 7,300 = 1,606.
    delta, _ = _federal_delta(salary=90_800, covered=True)
    assert delta == pytest.approx(0.22 * 7_300)


def test_mid_range_rounds_the_deductible_part_up_to_10():
    # MAGI 86,003: 3,747.75 -> 3,750 deductible, 3,750 not: 22% x 3,750.
    delta, _ = _federal_delta(salary=86_003, covered=True)
    assert delta == pytest.approx(0.22 * 3_750)


def test_not_covered_is_fully_deductible():
    # No workplace contributions, MAGI 95,000: the whole 7,500 comes off
    # (22% x 7,500 = 1,650 less tax than with no IRA at all).
    with_ira, warnings = _first(_plan(95_000))
    without, _ = _first(_plan(95_000, ira=0))
    assert without.federal_tax - with_ira.federal_tax == pytest.approx(0.22 * 7_500)
    assert not any(w.startswith(_WARNING) for w in warnings)


def test_a_457b_plan_does_not_make_the_owner_covered():
    # IRC 219(g)(5): a 457(b) is not an active-participant plan.
    plan = _plan(95_000, extra_accounts={"k457": AccountInfo(0, "traditional_457b")},
                 extra_priorities=[PriorityData(1, "k457", priority_type="income_percent", source_income_id="job",
                                                employer_match_rate=0.03)])
    with_457, warnings = _first(plan)
    plain, _ = _first(_plan(95_000))
    assert with_457.accounts["k457"] > 0
    assert with_457.federal_tax == pytest.approx(plain.federal_tax)
    assert not any(w.startswith(_WARNING) for w in warnings)


def test_joint_return_contributor_covered():
    # MFJ, MAGI 145,000, contributor covered: deductible 1,500, nondeductible
    # 6,000. Taxable 105,300 vs 111,300, both in 22%: 22% x 6,000 = 1,320.
    delta, warnings = _federal_delta(salary=100_000, spouse_salary=45_000, covered=True,
                                     filing_status="married_filing_jointly")
    assert delta == pytest.approx(0.22 * 6_000)
    assert any(w.startswith(_WARNING) for w in warnings)


def test_joint_return_only_spouse_covered():
    # Same MAGI 145,000 with only the spouse covered: 145,000 < 242,000, full deduction.
    delta, warnings = _federal_delta(salary=100_000, spouse_salary=45_000, spouse_covered=True,
                                     filing_status="married_filing_jointly")
    assert delta == pytest.approx(0, abs=0.01)
    assert not any(w.startswith(_WARNING) for w in warnings)
    # MAGI 247,000, only the spouse covered: 3,750 deductible, 3,750 not.
    # Taxable 207,300 vs 211,050, both in 22%: 22% x 3,750 = 825.
    delta, warnings = _federal_delta(salary=150_000, spouse_salary=97_000, spouse_covered=True,
                                     filing_status="married_filing_jointly")
    assert delta == pytest.approx(0.22 * 3_750)
    assert any(w.startswith(_WARNING) for w in warnings)


def test_separate_return_covered():
    # MFS, MAGI 60,000 >= 10,000: nothing deductible. Taxable 43,900 vs
    # 36,400, both in 12%: 12% x 7,500 = 900.
    delta, warnings = _federal_delta(salary=60_000, covered=True, filing_status="married_filing_separately")
    assert delta == pytest.approx(0.12 * 7_500)
    assert any(w.startswith(_WARNING) for w in warnings)
    # Living apart all year makes it the single range: 60,000 < 81,000.
    delta, warnings = _federal_delta(salary=60_000, covered=True, filing_status="married_filing_separately",
                                     tax_settings={"mfs_lived_apart_all_year": True})
    assert delta == pytest.approx(0, abs=0.01)
    assert not any(w.startswith(_WARNING) for w in warnings)


def test_conversion_income_pushes_magi_into_the_range():
    # Salary 80,000 is below 81,000, but a 6,000 Roth conversion counts in
    # the deduction MAGI (unlike the Roth contribution MAGI): 86,000 ->
    # 3,750 deductible. Taxable 69,900 vs 66,150: 22% x 3,750 = 825.
    conversion = [PriorityData(0, "roth", priority_type="roth_conversion", source_account_id="old",
                               max_annual_amount=6_000)]
    extra = {"old": AccountInfo(100_000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira")}
    delta, warnings = _federal_delta(salary=80_000, covered=True, extra_priorities=conversion, extra_accounts=extra)
    assert delta == pytest.approx(0.22 * 3_750)
    assert any(w.startswith(_WARNING) for w in warnings)
    # Without the conversion the same person keeps the full deduction.
    delta, _ = _federal_delta(salary=80_000, covered=True)
    assert delta == pytest.approx(0, abs=0.01)


def test_a_year_without_workplace_contributions_is_not_covered():
    # The employer contribution stops when the age-35 milestone triggers
    # (2027). 2026 is covered (9,265, as above); 2027 is not (8,440).
    plan = _plan(86_000, covered=True, milestones=[MilestoneData("stop", "Stop", "age", trigger_value=35)])
    plan.priorities[0].end_milestone_id = "stop"
    years = {snap.year: snap for snap in run_simulation(plan).yearly_snapshots}
    assert years[2026].accounts["k401"] > 0
    assert years[2026].federal_tax == pytest.approx(9_265)
    assert years[2027].accounts["k401"] == pytest.approx(years[2026].accounts["k401"])
    assert years[2027].federal_tax == pytest.approx(8_440)


def test_states_without_an_ira_deduction_add_back_only_the_deducted_part():
    # New Jersey taxes every IRA contribution. With half the deduction
    # disallowed federally, state income must equal the no-IRA plan's.
    partial, _ = _first(_plan(86_000, covered=True, state_code="NJ"))
    no_ira, _ = _first(_plan(86_000, covered=True, ira=0, state_code="NJ"))
    assert partial.state_tax == pytest.approx(no_ira.state_tax)
    # A state that allows the deduction follows the federal amount: the
    # covered plan pays tax on 3,750 more than the uncovered one.
    covered, _ = _first(_plan(86_000, covered=True, state_code="IL"))
    uncovered, _ = _first(_plan(86_000, state_code="IL"))
    assert covered.state_tax - uncovered.state_tax == pytest.approx(0.0495 * 3_750)


def _rental():
    # $10,000 rent, $20,000 expenses, $275,000 / 27.5 = $10,000 depreciation:
    # a -$20,000 Schedule E loss from an actively managed rental.
    return RealAssetData(id="r", name="Duplex", current_value=300_000, annual_appreciation_rate=0.0,
                         adjusted_basis=300_000, tax_treatment="rental", rental_income=10_000,
                         rental_income_growth_rate=0.0, rental_expenses=20_000, building_basis=275_000)


@pytest.mark.parametrize("covered, expected_tax", [
    # Deductible IRA: taxable 120,000 - 7,500 - 15,000 - 16,100 = 81,400;
    # 1,240 + 4,560 + 22% x 31,000 = 12,620.
    (False, 12_620),
    # Covered at 105,000 MAGI: nothing deductible, so taxable is
    # 120,000 - 15,000 - 16,100 = 88,900; 1,240 + 4,560 + 22% x 38,500 = 14,270.
    (True, 14_270),
])
def test_rental_special_allowance_ignores_the_ira_deduction(covered, expected_tax):
    # IRC 469(i)(3)(F)(iii): the $25,000 allowance phase-out uses AGI without
    # the section 219 deduction, so MAGI is 120,000 either way and the
    # allowance is 25,000 - 50% x 20,000 = 15,000; 5,000 stays suspended.
    snap, _ = _first(_plan(120_000, covered=covered, real_assets=[_rental()]))
    assert snap.rental_taxable_income == pytest.approx(-15_000)
    assert snap.suspended_passive_losses == pytest.approx(5_000)
    assert snap.federal_tax == pytest.approx(expected_tax)
