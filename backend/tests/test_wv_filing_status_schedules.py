"""West Virginia taxes joint filers on the single schedule and MFS on halved bands.

W. Va. Code 11-21-4e (https://code.wvlegislature.gov/11-21-4E/): Schedule A
applies to individuals (except married filing separately), joint returns, heads
of household, estates and trusts; Schedule B (married filing separately) halves
the thresholds. WV Tax Division 2026 tables
(https://tax.wv.gov/Individuals/Pages/PersonalIncomeTaxReductionBill.aspx):
Schedule A 2.11% to $10,000; $211.00 + 2.81% to $25,000; $632.50 + 3.16% to
$40,000; $1,106.50 + 4.22% to $60,000; $1,950.50 + 4.58% above. Schedule B
2.11% to $5,000; $105.50 + 2.81% to $12,500; $316.25 + 3.16% to $20,000;
$553.25 + 4.22% to $30,000; $975.25 + 4.58% above. WV has no standard
deduction in the data, so taxable income equals AGI.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate


@pytest.mark.parametrize("filing_status, agi, expected_tax", [
    # Schedule A: 1,950.50 + 90,000 x 4.58% (4,122.00) = 6,072.50
    ("married_filing_jointly", 150_000, 6_072.50),
    # Schedule A at the top threshold: 1,950.50
    ("married_filing_jointly", 60_000, 1_950.50),
    # Unchanged single: 6,072.50
    ("single", 150_000, 6_072.50),
    # Head of household also uses Schedule A: 1,106.50 + 10,000 x 4.22% = 1,528.50
    ("head_of_household", 50_000, 1_528.50),
    # Schedule B: 975.25 + 50,000 x 4.58% (2,290.00) = 3,265.25
    ("married_filing_separately", 80_000, 3_265.25),
    # Schedule B: 316.25 + 2,500 x 3.16% (79.00) = 395.25
    ("married_filing_separately", 15_000, 395.25),
])
def test_wv_schedule(filing_status, agi, expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "WV", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(agi)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_wv_joint_through_calculate():
    result = calculate(gross_income=150_000, deductions=0, filing_status="married_filing_jointly",
                       state_code="WV", tax_year=2026)
    assert result.state == pytest.approx(6_072.50, abs=0.01)
