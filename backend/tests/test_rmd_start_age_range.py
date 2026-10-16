"""Every RMD start age the tax-settings schema accepts has a divisor, with and
without a spouse beneficiary, and simulates end to end."""

import pytest

from app.schemas.plan import TaxSettings
from coastmath.engine import rmd
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    PlanData,
)
from coastmath.schemas.tax_adjustments import MAX_RMD_START_AGE, MIN_RMD_START_AGE

ACCEPTED = range(MIN_RMD_START_AGE, MAX_RMD_START_AGE + 1)


@pytest.mark.parametrize("start_age", ACCEPTED)
def test_every_accepted_start_age_has_uniform_and_joint_divisors(start_age):
    TaxSettings(rmd_start_ages={"self": start_age})  # accepted by the schema
    birth_year = 1960
    for owner_age in range(start_age, start_age + 3):
        uniform = rmd.calculate_rmd(100_000, owner_age, birth_year, start_age=start_age)
        joint = rmd.calculate_rmd(100_000, owner_age, birth_year, spouse_age=owner_age - 15, start_age=start_age)
        assert uniform > 0 and joint > 0
        # The younger spouse's joint period is always the longer one.
        assert joint < uniform


def test_derived_divisors_follow_the_ten_year_younger_joint_basis():
    assert rmd._RMD_DIVISORS[70] == 29.2
    assert rmd._RMD_DIVISORS[71] == 28.3
    for age in range(70, 121):
        assert rmd._RMD_DIVISORS[age] == rmd.joint_life_divisor(age, age - 10)


def test_printed_table_is_unchanged_for_sepp_and_strategy_users():
    assert min(rmd._DIVISORS) == 72


def test_joint_rows_70_and_71_come_from_table_3():
    assert rmd.joint_life_divisor(70, 55) == 33.0
    assert rmd.joint_life_divisor(71, 58) == 30.5
    # Below the first row still uses that row (no lifetime RMD is owed there).
    assert rmd.joint_life_divisor(65, 55) == rmd.joint_life_divisor(70, 55)


@pytest.mark.parametrize("start_age,divisor", [(70, 29.2), (71, 28.3)])
def test_simulation_takes_the_rmd_at_an_assumed_start_age_below_72(start_age, divisor):
    zero = AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0)
    # Born January 1956: 70 in 2026 and 71 in 2027.
    plan = PlanData(
        plan_id="00000000-0000-4000-8000-000000000103", birth_year=1956, birth_month=1,
        life_expectancy=72, start_year=2026, filing_status="single", state_code="FL", assumptions=zero,
        accounts={"ira": AccountInfo(100_000, "traditional_ira")},
        drawdown_order=[DrawdownEntryData(1, "ira")],
        tax_settings={"rmd_start_ages": {"self": start_age}},
    )
    snaps = {s.year: s for s in run_simulation(plan).yearly_snapshots}
    first_year = 1956 + start_age

    def rmd_taken(year):
        return sum(i.amount for i in snaps[year].cash_flow.income_sources if i.source == "rmd")

    assert rmd_taken(first_year) == pytest.approx(100_000 / divisor)
    if start_age == 71:
        assert rmd_taken(2026) == 0.0
