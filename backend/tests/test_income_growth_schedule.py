"""Per-income growth schedules: segment kinds, fallbacks, caps and consumers."""

import uuid
from dataclasses import replace

import pytest
from pydantic import ValidationError

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)
from coastmath.schemas.plan_data_request import IncomeRequest
from tests.engine_support import source as ss_source
from tests.ss_household_support import pia_ss


def plan(inflation=0.0, **changes):
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1980, birth_month=1, life_expectancy=60,
        filing_status="single", start_year=2026,
        assumptions=AssumptionData(
            inflation_rate=inflation, stock_growth_rate=0, bond_return_rate=0,
            stock_dividend_yield=0, cash_yield_rate=0,
        ),
        accounts={"cash": AccountInfo(balance=0, account_type="savings")},
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0},
    )
    values.update(changes)
    return PlanData(**values)


def salary(amount=100_000, schedule=None, growth=0.02, **extra):
    return IncomeData(
        id="salary", name="Salary", annual_amount=amount, tax_category="employment",
        growth_rate=growth, growth_schedule=schedule, **extra,
    )


def segment(start, kind, value, end=None, dollars=None):
    return {"start_year": start, "end_year": end, "kind": kind, "value": value, "dollars": dollars}


def amounts(result, name="Salary"):
    return {
        row.year: sum(i.amount for i in row.cash_flow.income_sources if i.name == name)
        for row in result.yearly_snapshots
    }


def test_percent_then_gap_falls_back_to_growth_rate():
    schedule = [segment(2027, "percent", 3, end=2028)]
    got = amounts(run_simulation(plan(income_streams=[salary(schedule=schedule)])))
    assert got[2026] == pytest.approx(100_000)
    assert got[2027] == pytest.approx(103_000)
    assert got[2028] == pytest.approx(103_000 * 1.03)
    # 2029 is not covered: the stream's own 2% applies again.
    assert got[2029] == pytest.approx(103_000 * 1.03 * 1.02)


def test_gap_without_growth_rate_follows_wage_curve():
    schedule = [segment(2030, "percent", 0)]
    p = plan(inflation=0.03, income_streams=[salary(schedule=schedule, growth=None)])
    got = amounts(run_simulation(p))
    baseline = amounts(run_simulation(replace(p, income_streams=[salary(growth=None)])))
    assert got[2029] == pytest.approx(baseline[2029])
    assert got[2029] == pytest.approx(100_000 * 1.03 ** 3)
    assert got[2031] == pytest.approx(got[2029])


def test_inflation_offset_uses_realized_inflation():
    schedule = [segment(2027, "inflation_offset", -1)]
    got = amounts(run_simulation(plan(inflation=0.03, income_streams=[salary(schedule=schedule)])))
    assert got[2027] == pytest.approx(100_000 * 1.02)
    assert got[2030] == pytest.approx(100_000 * 1.02 ** 4)


def test_inflation_offset_follows_sampled_monte_carlo_path():
    schedule = [segment(2027, "inflation_offset", 1)]
    p = plan(inflation=0.03, income_streams=[salary(schedule=schedule)])
    sampled = {2026: (0.0, 0.0, 0.05), 2027: (0.0, 0.0, 0.10), 2028: (0.0, 0.0, 0.0)}
    got = amounts(run_simulation(p, override_returns=sampled))
    assert got[2027] == pytest.approx(100_000 * 1.06)
    assert got[2028] == pytest.approx(100_000 * 1.06 * 1.11)


@pytest.mark.parametrize(("dollars", "expected_2028"), [
    ("nominal", 110_000), ("today", 100_000 + 5_000 * 1.02 + 5_000 * 1.02 ** 2),
])
def test_dollar_change(dollars, expected_2028):
    schedule = [segment(2027, "dollar_change", 5_000, end=2028, dollars=dollars)]
    got = amounts(run_simulation(plan(inflation=0.02, income_streams=[salary(schedule=schedule, growth=0)])))
    assert got[2028] == pytest.approx(expected_2028)
    assert got[2029] == pytest.approx(expected_2028)


def test_dollar_change_never_below_zero():
    schedule = [segment(2027, "dollar_change", -60_000, dollars="nominal")]
    got = amounts(run_simulation(plan(income_streams=[salary(schedule=schedule)])))
    assert got[2027] == pytest.approx(40_000)
    assert got[2028] == 0


@pytest.mark.parametrize(("dollars", "expected"), [("nominal", 120_000), ("today", 120_000 * 1.02 ** 3)])
def test_set_amount_then_default_growth(dollars, expected):
    schedule = [segment(2029, "set_amount", 120_000, end=2029, dollars=dollars)]
    got = amounts(run_simulation(plan(inflation=0.02, income_streams=[salary(schedule=schedule, growth=0.05)])))
    assert got[2028] == pytest.approx(100_000 * 1.05 ** 2)
    assert got[2029] == pytest.approx(expected)
    assert got[2030] == pytest.approx(expected * 1.05)


def test_set_amount_on_zero_opening_amount_and_in_first_year():
    late = [segment(2028, "set_amount", 50_000, dollars="nominal")]
    got = amounts(run_simulation(plan(income_streams=[salary(amount=0, schedule=late)])))
    assert got[2027] == 0
    assert got[2028] == pytest.approx(50_000)
    assert got[2029] == pytest.approx(50_000)
    first = [segment(2026, "set_amount", 80_000, end=2026, dollars="nominal")]
    got = amounts(run_simulation(plan(income_streams=[salary(schedule=first)])))
    assert got[2026] == pytest.approx(80_000)
    assert got[2027] == pytest.approx(80_000 * 1.02)


def test_growth_cap_applies_after_schedule():
    schedule = [segment(2027, "percent", 50)]
    got = amounts(run_simulation(plan(income_streams=[salary(schedule=schedule, growth_cap=180_000)])))
    assert got[2027] == pytest.approx(150_000)
    assert got[2028] == pytest.approx(180_000)


def test_one_time_payment_uses_the_scheduled_amount_once():
    pay = MilestoneData(id="pay", name="Pay", trigger_type="date", trigger_date="2028-03-01")
    bonus = IncomeData(
        id="bonus", name="Bonus", annual_amount=10_000, tax_category="employment", frequency="once",
        start_milestone_id="pay", growth_rate=0.0, growth_schedule=[segment(2027, "percent", 10)],
    )
    got = amounts(run_simulation(plan(milestones=[pay], income_streams=[bonus])), "Bonus")
    assert got[2028] == pytest.approx(12_100)
    assert sum(got.values()) == pytest.approx(12_100)


def test_employer_match_sees_scheduled_salary():
    schedule = [segment(2028, "set_amount", 150_000, dollars="nominal")]
    match = PriorityData(
        priority_rank=1, target_account_id="401k", priority_type="income_percent",
        source_income_id="salary", employee_rate=0.0, employer_match_rate=0.08,
    )
    p = plan(
        income_streams=[salary(schedule=schedule, growth=0)], priorities=[match],
        accounts={"401k": AccountInfo(balance=0, account_type="traditional_401k"),
                  "cash": AccountInfo(balance=0, account_type="savings")},
    )
    rows = {row.year: row for row in run_simulation(p).yearly_snapshots}
    employer = lambda year: sum(c.amount for c in rows[year].cash_flow.contributions if c.source == "employer")  # noqa: E731
    assert employer(2027) == pytest.approx(8_000)
    assert employer(2028) == pytest.approx(12_000)


def test_final_average_pension_sees_scheduled_salary():
    retire = MilestoneData(id="retire", name="Retire", trigger_type="date", trigger_date="2029-01-01")
    pension = IncomeData(
        id="pension", name="Pension", annual_amount=0, tax_category="qualified_pension",
        start_milestone_id="retire",
        pension_formula={"kind": "final_average", "linked_income_id": "salary", "benefit_percent_per_year": 1.5,
                         "years_of_service_before_plan": 10, "final_average_years": 2},
    )
    schedule = [segment(2027, "set_amount", 120_000, end=2027, dollars="nominal"),
                segment(2028, "dollar_change", 10_000, dollars="nominal")]
    p = plan(milestones=[retire], income_streams=[
        salary(schedule=schedule, growth=0, end_milestone_id="retire"), pension,
    ])
    got = amounts(run_simulation(p), "Pension")
    assert got[2029] == pytest.approx((120_000 + 130_000) / 2 * 13 * 0.015)


def test_covered_earnings_see_scheduled_salary():
    change = MilestoneData(id="raise", name="Raise", trigger_type="date", trigger_date="2028-01-01")
    benefit = pia_ss("self", 1_000, 67, growth=0.0, pia_reflects="current_record", covered_years_to_date=20)
    scheduled = salary(schedule=[segment(2028, "set_amount", 180_000, dollars="nominal")], growth=0)
    split = [
        IncomeData(id="before", name="Before", annual_amount=100_000, tax_category="employment",
                   growth_rate=0, end_milestone_id="raise"),
        IncomeData(id="after", name="After", annual_amount=180_000, tax_category="employment",
                   growth_rate=0, start_milestone_id="raise"),
    ]
    base = dict(birth_year=1970, life_expectancy=80, milestones=[change])
    a = run_simulation(plan(**base, income_streams=[benefit, scheduled]))
    b = run_simulation(plan(**base, income_streams=[benefit, *split]))
    assert ss_source(a, 2037, "self SS") == pytest.approx(ss_source(b, 2037, "self SS"))
    assert ss_source(a, 2037, "self SS") > 12_000


def test_request_validation():
    base = dict(id="s", name="S", annual_amount=1, tax_category="employment")
    with pytest.raises(ValidationError, match="overlap"):
        IncomeRequest(**base, growth_schedule=[segment(2027, "percent", 1), segment(2030, "percent", 2)])
    with pytest.raises(ValidationError, match="today's or nominal"):
        IncomeRequest(**base, growth_schedule=[segment(2027, "set_amount", 1)])
    with pytest.raises(ValidationError, match="negative"):
        IncomeRequest(**base, growth_schedule=[segment(2027, "set_amount", -1, dollars="nominal")])
    with pytest.raises(ValidationError):
        IncomeRequest(**base, growth_schedule=[segment(2027, "percent", float("nan"))])
    with pytest.raises(ValidationError, match="COLA"):
        IncomeRequest(**{**base, "tax_category": "social_security"},
                      growth_schedule=[segment(2027, "percent", 1)])
    ok = IncomeRequest(**base, growth_schedule=[segment(2027, "percent", 1, end=2029), segment(2030, "percent", 2)])
    assert len(ok.growth_schedule) == 2
    assert "growth_schedule" not in IncomeRequest(**base).model_dump(exclude_unset=False)
