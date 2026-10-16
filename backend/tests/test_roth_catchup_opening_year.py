"""SECURE 2.0 Roth catch-up test in the opening year, which has no prior wages.

The opening year's projected W-2 wages, annualized for a partial year, stand
in for prior-year wages against the $150,000 (2026) threshold.
"""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
)

DEFERRAL = 24_500  # 2026 402(g) limit
CATCH_UP = 8_000  # age 50-59


def _plan(salary: float, fraction: float = 1.0, ytd_wages: float | None = None) -> PlanData:
    tax_settings = {"year_to_date": {"tax_year": 2026, "w2_income_by_owner": {"self": ytd_wages}}} if ytd_wages else None
    return PlanData(
        plan_id="00000000-0000-0000-0000-0000000000c3", birth_year=1970, filing_status="single",
        life_expectancy=60, start_year=2026, first_year_fraction=fraction,
        accounts={"cash": AccountInfo(50_000, "checking"), "trad": AccountInfo(0, "traditional_401k")},
        income_streams=[IncomeData("wage", "Salary", salary)],
        expenses=[ExpenseData("living", "Living", 30_000)],
        priorities=[PriorityData(1, "trad", priority_type="pre_tax_contribution", source_income_id="wage"),
                    PriorityData(2, "cash", priority_type="contribution")],
        drawdown_order=[DrawdownEntryData(1, "cash")],
        tax_settings=tax_settings,
    )


def _deferral(result, year_index: int) -> float:
    flows = result.yearly_snapshots[year_index].cash_flow.contributions
    return sum(f.amount for f in flows if f.account_id == "trad" and f.source == "payroll")


@pytest.mark.parametrize("salary,fraction,ytd_wages,catch_up", [
    (120_000, 1.0, None, True),      # below the threshold: Traditional catch-up in year 1
    (200_000, 1.0, None, False),     # above it: catch-up stays Roth-only
    (120_000, 0.5, None, True),      # $60k over half a year is $120k a year
    (280_000, 0.5, None, False),     # $140k over half a year is $280k a year
    (120_000, 0.5, 100_000, True),   # year-to-date wages are history, not the annual rate
])
def test_opening_year_uses_annualized_projected_wages(salary, fraction, ytd_wages, catch_up):
    result = run_simulation(_plan(salary, fraction, ytd_wages))
    assert _deferral(result, 0) == pytest.approx(DEFERRAL + (CATCH_UP if catch_up else 0))
    warning = next(w for w in result.metadata.warnings if w.startswith("401(k) catch-up eligibility"))
    assert "annualized" in warning


def test_later_years_still_use_prior_year_wages():
    high, low = run_simulation(_plan(200_000)), run_simulation(_plan(120_000))
    # Year 2 tests 2026's projected wages: above the threshold, catch-up stays Roth-only.
    assert _deferral(low, 1) - _deferral(high, 1) >= CATCH_UP


def test_a_partial_opening_year_is_annualized_for_the_second_year():
    # $300k starting in October: $75k in the opening year, $300k a year.
    october = run_simulation(_plan(300_000, fraction=0.25))
    full_year_high = run_simulation(_plan(200_000))
    full_year_low = run_simulation(_plan(120_000))
    assert _deferral(october, 0) == pytest.approx(DEFERRAL)
    # Year two stays Roth-only: the same Traditional deferral as a full-year high earner.
    assert _deferral(october, 1) == pytest.approx(_deferral(full_year_high, 1))
    assert _deferral(full_year_low, 1) - _deferral(october, 1) >= CATCH_UP


def test_entered_year_to_date_wages_count_as_opening_year_history():
    # $30k earned before an October start plus $75k projected is $105k for 2026,
    # under the threshold, so year two allows a Traditional catch-up. Year one
    # still tests the $300k annual rate.
    result = run_simulation(_plan(300_000, fraction=0.25, ytd_wages=30_000))
    full_year_low = run_simulation(_plan(120_000))
    assert _deferral(result, 0) == pytest.approx(DEFERRAL)
    assert _deferral(result, 1) == pytest.approx(_deferral(full_year_low, 1))
