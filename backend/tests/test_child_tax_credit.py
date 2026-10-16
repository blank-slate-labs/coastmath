"""IRC 24 child tax credit (Rev. Proc. 2025-32): amount, age cutoff, phaseout, limit."""

import pytest

from coastmath.engine.tax_engine import calculate
from coastmath.schemas.coverage_settings import CoverageSettings


def _tax(agi, birth_years=(), filing_status="married_filing_jointly", **kwargs):
    settings = {"dependent_birth_years": list(birth_years)} if birth_years else None
    return calculate(gross_income=agi, deductions=0, filing_status=filing_status,
                     settings=settings, **kwargs)


def test_credit_is_2200_per_child_and_reduces_federal_tax():
    without, with_two = _tax(150_000), _tax(150_000, (2015, 2020))
    assert with_two.child_tax_credit == 4_400
    assert without.federal - with_two.federal == pytest.approx(4_400)
    assert without.total_tax - with_two.total_tax == pytest.approx(4_400)


@pytest.mark.parametrize(("birth_year", "counts"), [
    (2010, True),    # 16 at the end of 2026
    (2009, False),   # 17 at the end of 2026
    (2026, True),    # born this year
    (2027, False),   # not yet born
])
def test_only_children_under_17_at_year_end_count(birth_year, counts):
    assert _tax(150_000, (birth_year,)).child_tax_credit == (2_200 if counts else 0)


@pytest.mark.parametrize(("filing_status", "agi", "expected"), [
    ("married_filing_jointly", 400_000, 2_200),
    # $10,500 over: 11 started $1,000 steps x $50.
    ("married_filing_jointly", 410_500, 2_200 - 550),
    ("single", 201_000, 2_200 - 50),
    ("head_of_household", 250_000, 0),
])
def test_phaseout_is_50_per_started_1000_over_unindexed_threshold(filing_status, agi, expected):
    assert _tax(agi, (2020,), filing_status=filing_status).child_tax_credit == pytest.approx(expected)
    # Thresholds are statutory: projected inflation does not move them.
    indexed = _tax(agi, (2020,), filing_status=filing_status, inflation_factor=1.5, federal_inflation_factor=1.0)
    assert indexed.child_tax_credit == pytest.approx(expected)


def test_credit_is_nonrefundable():
    low = _tax(40_000, (2018, 2020, 2022))
    assert low.child_tax_credit == pytest.approx(_tax(40_000).federal)
    assert low.federal == 0
    assert low.total_tax >= 0


def test_amount_is_indexed_after_2026_and_rounded_down_to_100():
    later = _tax(150_000, (2025,), tax_year=2030, federal_inflation_factor=1.1)
    assert later.child_tax_credit == 2_400  # 2,420 rounded down


@pytest.mark.parametrize(("tax_year", "factor", "per_child"), [
    (2026, 1.0, 2_200),             # 2,200 x 1.0234 = 2,251.48
    (2027, 1.025, 2_300),           # 2,307.77; indexing the rounded 2,200 gives 2,255
    (2028, 1.025 ** 2, 2_300),      # 2,365.46
    (2029, 1.025 ** 3, 2_400),      # 2,424.60; indexing the rounded 2,200 gives 2,369
])
def test_indexing_uses_the_2024_base_not_the_rounded_2026_amount(tax_year, factor, per_child):
    # IRC 24(i)(2)-(3): $2,200 x the C-CPI-U adjustment over 2024, rounded down to
    # $100. The 2026 adjustment is about 1.0234 (`_sources` in `tax_brackets_2026.json`).
    result = _tax(150_000, (2018, 2020), tax_year=tax_year,
                  inflation_factor=factor, federal_inflation_factor=factor)
    assert result.child_tax_credit == 2 * per_child


def test_flat_tax_mode_has_no_credit():
    result = calculate(gross_income=150_000, deductions=0, filing_status="single",
                       settings={"mode": "flat", "ordinary_income_tax_rate": 0.2,
                                 "dependent_birth_years": [2020]})
    assert result.child_tax_credit == 0
    assert result.federal == pytest.approx(30_000)


def test_birth_years_are_validated_and_default_empty():
    assert CoverageSettings().dependent_birth_years == []
    assert CoverageSettings(dependent_birth_years=[2019, 2022]).dependent_birth_years == [2019, 2022]
    with pytest.raises(ValueError):
        CoverageSettings(dependent_birth_years=[1800])
    with pytest.raises(ValueError):
        CoverageSettings(dependent_birth_years=[2020] * 21)
