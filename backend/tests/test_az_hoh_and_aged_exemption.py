"""Arizona head-of-household deduction and age-65 exemption.

ARS 43-1041(A), (H) (https://www.azleg.gov/ars/43/01041.htm): standard
deduction $15,750 single/MFS, $23,625 head of household, $31,500 MFJ, indexed
like the federal basic standard deduction, so 2026 = $16,100 / $24,150 /
$32,200 (Rev. Proc. 2025-32). ARS 43-1023(E)
(https://www.azleg.gov/ars/43/01023.htm): a fixed, unindexed $2,100 exemption
for a taxpayer 65 or older, and another for a 65+ spouse on a joint return.
Flat 2.5% rate (ARS 43-1011).
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, holder_age, spouse_age, expected_taxable", [
    ("single", 45, None, 80_000 - 16_100),                      # 63,900
    ("single", 70, None, 80_000 - 16_100 - 2_100),              # 61,800
    ("head_of_household", 45, None, 80_000 - 24_150),           # 55,850
    ("head_of_household", 70, None, 80_000 - 24_150 - 2_100),   # 53,750
    ("married_filing_jointly", 70, 70, 80_000 - 32_200 - 4_200),  # 43,600
    ("married_filing_jointly", 70, 60, 80_000 - 32_200 - 2_100),  # 45,700
    ("married_filing_separately", 70, 70, 80_000 - 16_100 - 2_100),  # spouse only on joint return
])
def test_az_deduction_and_aged_exemption(filing_status, holder_age, spouse_age, expected_taxable):
    tax, taxable = _state_tax_and_taxable_income(
        80_000, "AZ", filing_status=filing_status, holder_age=holder_age,
        spouse_age=spouse_age, tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_taxable * 0.025, abs=0.01)


@pytest.mark.parametrize("filing_status, holder_age, spouse_age, expected_state", [
    ("head_of_household", 45, None, 1_396.25),        # 55,850 x 2.5%
    ("head_of_household", 70, None, 1_343.75),        # 53,750 x 2.5%
    ("single", 70, None, 1_545.00),                   # 61,800 x 2.5%
    ("married_filing_jointly", 70, 70, 1_090.00),     # 43,600 x 2.5%
    ("single", 45, None, 1_597.50),                   # 63,900 x 2.5%
])
def test_az_calculate(filing_status, holder_age, spouse_age, expected_state):
    r = calculate(gross_income=80_000, deductions=0, filing_status=filing_status, state_code="AZ",
                  tax_year=2026, holder_age=holder_age, spouse_age=spouse_age)
    assert r.state == pytest.approx(expected_state, abs=0.01)


def test_az_aged_exemption_is_not_indexed():
    # 80,000 - 24,150 x 1.1 - 2,100 = 51,335
    _, taxable = _state_tax_and_taxable_income(
        80_000, "AZ", filing_status="head_of_household", holder_age=70,
        tax_year=2026, inflation_factor=1.1)
    assert taxable == pytest.approx(80_000 - 24_150 * 1.1 - 2_100)
