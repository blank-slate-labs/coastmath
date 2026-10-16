"""Cash receipts and pension accrual use resolved dynamic milestone months."""
from uuid import uuid4

import pytest

from coastmath.engine.household_lifecycle import LAST_SURVIVOR
from coastmath.engine.milestones import evaluate_milestones
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    EstateSettingsData,
    IncomeData,
    MilestoneData,
    SimState,
)
from tests.engine_support import source
from tests.ss_household_support import couple, pia_ss, plan


def september_chain():
    condition, relative = str(uuid4()), str(uuid4())
    milestones = [
        MilestoneData(condition, "September goal", "conditions", conditions={
            "combinator": "all", "items": [{"kind": "date", "date": "2026-09"}],
        }),
        MilestoneData(relative, "Start at goal", "relative", relative_to_id=condition),
    ]
    return relative, milestones


def test_relative_condition_month_pays_once_in_partial_opening_year():
    relative, milestones = september_chain()
    receipt = IncomeData("receipt", "Receipt", 12000, frequency="once",
                         tax_category="nontaxable", start_milestone_id=relative)
    result = run_simulation(plan(birth_year=1976, life_expectancy=52,
        first_year_fraction=0.5, income_streams=[receipt], milestones=milestones))
    assert source(result, 2026, "Receipt") == 12000
    assert source(result, 2027, "Receipt") == 0


def test_relative_condition_month_preserves_salary_and_pension_service():
    relative, milestones = september_chain()
    salary = IncomeData("salary", "Salary", 120000, growth_rate=0,
                        tax_category="employment", end_milestone_id=relative)
    pension = IncomeData("pension", "Pension", 0,
        tax_category="qualified_pension", start_milestone_id=relative,
        pension_formula={"kind": "career_average", "linked_income_id": "salary",
                         "benefit_percent_per_year": 2})
    result = run_simulation(plan(birth_year=1976, life_expectancy=52,
        first_year_fraction=0.5, income_streams=[salary, pension], milestones=milestones))
    # July and August service: 120,000 * 2% * 2/12 = 400 annual benefit.
    assert source(result, 2026, "Salary") == pytest.approx(20000)
    assert source(result, 2026, "Pension") == pytest.approx(400 * 4/12)
    assert source(result, 2027, "Pension") == pytest.approx(400)


def test_relative_month_converges_when_any_dependency_resolves_earlier():
    goal = MilestoneData("goal", "Goal", "conditions", conditions={
        "combinator": "any", "items": [
            {"kind": "date", "date": "2026-09"},
            {"kind": "milestone", "milestone_id": "earlier"},
        ],
    })
    child = MilestoneData("child", "Child", "relative", relative_to_id="goal")
    earlier = MilestoneData("earlier", "Earlier", "conditions", conditions={
        "combinator": "all", "items": [{"kind": "date", "date": "2026-07"}],
    })
    for goals in ([goal, child, earlier], [earlier, child, goal]):
        state = SimState(2026)
        evaluate_milestones(state, goals, 2026, 1980)
        assert state.triggered_milestone_months == {"goal": 7, "child": 7, "earlier": 7}


@pytest.mark.parametrize(("month", "withheld"), [(1, 12000), (6, 12000), (7, 0), (8, 0)])
@pytest.mark.parametrize("condition_start", [False, True])
def test_once_bonus_counts_in_actual_payment_month_before_retirement_fra(month, withheld, condition_start):
    start = str(uuid4())
    milestones = [MilestoneData(start, "Bonus date", "conditions", conditions={
        "combinator": "all", "items": [{"kind": "date", "date": f"2026-{month:02}"}],
    })] if condition_start else []
    bonus = IncomeData("bonus", "Bonus", 120000, growth_rate=0, frequency="once",
        tax_category="employment", start_month=None if condition_start else month,
        start_milestone_id=start if condition_start else None)
    benefit = IncomeData("benefit", "Benefit", 24000, growth_rate=0,
        tax_category="social_security", claiming_age=62)
    result = run_simulation(plan(birth_year=1959, birth_month=9, life_expectancy=70,
        milestones=milestones, income_streams=[bonus, benefit]))
    # FRA is July 2026. All of a pre-July bonus counts; July and later do not.
    assert result.yearly_snapshots[0].ss_earnings_test_withheld == pytest.approx(withheld)
    assert source(result, 2026, "Bonus") == 120000


# Survivor entitlement starts January 2022 and FRA is May 2022. With no work
# in Feb-Apr, 2022 is the grace year (20 CFR 404.435(b)(1)): only January's
# $2,000 benefit can be withheld for the January bonus.
@pytest.mark.parametrize(("month", "withheld"), [(1, 2000), (5, 0)])
def test_once_bonus_counts_before_fra_for_survivor_without_own_benefit(month, withheld):
    deceased = IncomeData("deceased", "Deceased", 24000, growth_rate=0,
        tax_category="social_security", owner="self", claiming_age=67)
    bonus = IncomeData("bonus", "Bonus", 240000, growth_rate=0, frequency="once",
        tax_category="employment", owner="spouse", start_month=month)
    result = run_simulation(couple(start_year=2022, birth_year=1950, life_expectancy=71,
        spouse_birth_year=1956, spouse_birth_month=1, spouse_life_expectancy=70,
        estate_settings=EstateSettingsData(household_lifecycle=LAST_SURVIVOR,
            survivor_social_security_policy="claimed_benefit_at_survivor_fra",
            survivor_social_security_eligibility_confirmed=True,
            survivor_social_security_eligibility_source="Synthetic eligibility confirmation"),
        income_streams=[deceased, bonus]))
    assert result.yearly_snapshots[0].ss_earnings_test_withheld == pytest.approx(withheld)


@pytest.mark.parametrize(("month", "calendar"), [(3, 10000), (7, 0), (12, 10000)])
@pytest.mark.parametrize("fraction", [1.0, 0.5])
def test_once_interruption_uses_event_month_for_cash_and_imputed_history(month, calendar, fraction):
    bonus = IncomeData("bonus", "Bonus", 10000, growth_rate=0, frequency="once",
        tax_category="employment", start_month=month,
        pay_interruption=(2026 + 5/12, 2026 + 8/12, 1.0))
    result = run_simulation(plan(birth_year=1976, life_expectancy=51,
        first_year_fraction=fraction, income_streams=[bonus]))
    expected_cash = calendar if (month - 1) / 12 >= 1 - fraction else 0
    assert source(result, 2026, "Bonus") == pytest.approx(expected_cash)
    assert result.yearly_snapshots[0].calendar_year_gross_income == pytest.approx(calendar)


@pytest.mark.parametrize(("fraction", "post_benefits"), [(0.5, 8800), (0.25, 4400)])
def test_pre_start_once_bonus_enters_annual_fra_test_without_new_cash(fraction, post_benefits):
    bonus = IncomeData("bonus", "Bonus", 100000, growth_rate=0, frequency="once",
        tax_category="employment", start_month=3)
    result = run_simulation(plan(birth_year=1959, birth_month=9, life_expectancy=70,
        first_year_fraction=fraction, income_streams=[bonus, pia_ss("self", 2000, 62)]))
    # July FRA: all six earlier benefit months withheld. Six credits reduce
    # early-claim months from 58 to 52; PIA * (1 - .20 - 16*5/1200) = 17,600.
    assert source(result, 2026, "Bonus") == 0
    assert source(result, 2026, "self SS") == pytest.approx(post_benefits)
    assert result.yearly_snapshots[0].calendar_year_gross_income == pytest.approx(108800)
    assert source(result, 2027, "self SS") == pytest.approx(17600)
