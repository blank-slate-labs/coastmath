"""Literal 2026 nonbusiness rate checks from ORC 5747.02(A)(3)(c).

https://codes.ohio.gov/ohio-revised-code/section-5747.02
These values exercise the rate schedule before omitted personal exemptions,
Ohio AGI adjustments and credits; they are not full-return expected taxes.
"""

import pytest

from coastmath.engine.tax_engine import _calculate_state_tax


@pytest.mark.parametrize("filing_status", [
    "single", "head_of_household", "married_filing_jointly", "married_filing_separately",
])
@pytest.mark.parametrize("taxable_income, expected", [
    (0, 0),
    (26_050, 0),
    (26_050.01, 332.000275),
    (26_051, 332.0275),
    (52_100, 1_048.375),
    (100_000, 2_365.625),
    (134_250, 3_307.5),
])
def test_all_filing_statuses_share_threshold_and_conditional_base(taxable_income, expected, filing_status):
    assert _calculate_state_tax(taxable_income, "OH", filing_status=filing_status,
                                tax_year=2026) == pytest.approx(expected)


def test_future_year_indexing_scales_base_and_threshold_together():
    assert _calculate_state_tax(200_000, "OH", inflation_factor=2,
                                tax_year=2027) == pytest.approx(4_731.25)


def test_custom_ohio_brackets_do_not_inherit_statutory_base():
    custom = [{"min": 0, "max": 999_999_999, "rate": 0.01}]
    assert _calculate_state_tax(100_000, "OH", custom_brackets=custom) == pytest.approx(1_000)


def test_other_state_retains_existing_joint_threshold_convention():
    # Michigan is flat 4.25% with zero standard deduction in the existing data.
    assert _calculate_state_tax(100_000, "MI", filing_status="married_filing_jointly") == pytest.approx(4_250)
