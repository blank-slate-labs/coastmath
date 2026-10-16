"""Joint Life and Last Survivor RMD divisor (Treas. Reg. 1.401(a)(9)-9(d), Table 3)."""
import pytest

from app.schemas.account import AccountDistributionSettings
from coastmath.engine.rmd import (
    calculate_rmd,
    get_rmd_start_age,
    joint_life_divisor,
    spouse_more_than_ten_years_younger,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import AccountInfo, AssumptionData, PlanData

# Cells transcribed from Table 3 (also printed in IRS Pub. 590-B, Appendix B, Table II).
OFFICIAL_CELLS = [(72, 50, 36.9), (72, 61, 28.1), (73, 62, 27.2), (75, 60, 28.3),
                  (80, 65, 23.8), (90, 70, 19.1), (72, 72, 21.6)]


@pytest.mark.parametrize(("owner", "spouse", "divisor"), OFFICIAL_CELLS)
def test_table_cells_match_the_published_values(owner, spouse, divisor):
    assert joint_life_divisor(owner, spouse) == divisor


def test_table_is_symmetric_where_both_ages_are_in_range():
    for owner in range(72, 121):
        for spouse in range(72, 121):
            assert joint_life_divisor(owner, spouse) == joint_life_divisor(spouse, owner)


def test_ages_beyond_the_table_use_the_final_printed_row_and_column():
    assert joint_life_divisor(130, 125) == joint_life_divisor(120, 120)


def test_rmd_uses_the_joint_divisor_only_when_a_spouse_age_is_supplied():
    uniform = calculate_rmd(1_000_000, 75, 1951)
    joint = calculate_rmd(1_000_000, 75, 1951, spouse_age=60)
    assert uniform == pytest.approx(1_000_000 / 24.6)
    assert joint == pytest.approx(1_000_000 / 28.3)
    assert joint < uniform


def test_exactly_ten_years_is_not_more_than_ten_years_younger():
    assert not spouse_more_than_ten_years_younger(1950, 1960, 6, 6)
    assert not spouse_more_than_ten_years_younger(1950, 1960, 6, 5 + 1)
    assert spouse_more_than_ten_years_younger(1950, 1960, 6, 7)
    assert spouse_more_than_ten_years_younger(1950, 1961, 6, 6)
    # Without both birth months only a gap of more than ten calendar years counts.
    assert not spouse_more_than_ten_years_younger(1950, 1960)
    assert spouse_more_than_ten_years_younger(1950, 1961)


def _rmd_for(spouse_birth_year, *, sole_beneficiary, spouse_month=1, owner="self"):
    settings = {"spouse_sole_beneficiary": True} if sole_beneficiary else None
    plan = PlanData(
        plan_id="00000000-0000-4000-8000-000000000074", birth_year=1951, birth_month=1,
        filing_status="married_filing_jointly", life_expectancy=77, start_year=2026,
        spouse_birth_year=spouse_birth_year, spouse_birth_month=spouse_month, spouse_life_expectancy=95,
        state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0),
        accounts={"ira": AccountInfo(1_000_000, "traditional_ira", owner=owner, distribution_settings=settings)},
    )
    first = run_simulation(plan).yearly_snapshots[0]
    return sum(item.amount for item in first.cash_flow.income_sources if item.name == "RMD")


def test_simulation_switches_to_table_three_for_a_sole_beneficiary_spouse_over_ten_years_younger():
    uniform = _rmd_for(1965, sole_beneficiary=False)
    joint = _rmd_for(1965, sole_beneficiary=True)
    assert uniform == pytest.approx(1_000_000 / 24.6)
    # Owner turns 75 in 2026; the 1965 spouse turns 61.
    assert joint == pytest.approx(1_000_000 / joint_life_divisor(75, 61))


def test_exactly_ten_years_younger_keeps_the_uniform_table():
    assert _rmd_for(1961, sole_beneficiary=True, spouse_month=1) == pytest.approx(1_000_000 / 24.6)


def test_spouse_beneficiary_off_keeps_the_uniform_table_even_when_far_younger():
    assert _rmd_for(1975, sole_beneficiary=False) == pytest.approx(1_000_000 / 24.6)


def test_distribution_settings_schema_is_additive_and_validated():
    assert AccountDistributionSettings().model_dump(exclude_none=True) in ({}, {"spouse_sole_beneficiary": False})
    assert AccountDistributionSettings(spouse_sole_beneficiary=True).spouse_sole_beneficiary is True
    assert get_rmd_start_age(1951) == 73
