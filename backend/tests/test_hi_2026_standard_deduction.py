"""Hawaii 2026 uses Act 46's standard deductions and the head-of-household schedule.

Act 46, SLH 2024, as summarized by DOTAX Announcement No. 2024-03 (June 3, 2024),
https://files.hawaii.gov/tax/news/announce/ann24-03.pdf, p. 3: "For tax year 2026,
the standard deduction amounts will be as follows: Joint or Surviving Spouse
$16,000; Head of Household $12,000; Single or Married Filing Separate $8,000. The
income tax brackets will be the same as in tax year 2025." The 2025 head-of-household
schedule (p. 2) is 1.4% to $14,400, 3.2% to $21,600, 5.5% to $28,800, 6.4% to
$36,000, 6.8% to $54,000, 7.2% to $72,000 ("$3,809 plus 7.6% of excess over
$72,000"), 7.6% to $187,500, 7.9% to $262,500, 8.25% to $337,500, 9% to $412,500,
10% to $487,500 and 11% above. The $1,144 personal exemption remains omitted.
"""

import pytest

from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate

# Single Schedule I through $48,000: 9,600 x 1.4% (134.40) + 4,800 x 3.2% (153.60)
# + 4,800 x 5.5% (264) + 4,800 x 6.4% (307.20) + 12,000 x 6.8% (816)
# + 12,000 x 7.2% (864) = 2,539.20. Joint Schedule II through $96,000 doubles it.
_SINGLE_TO_48_000 = 2_539.20
_JOINT_TO_96_000 = 5_078.40
# Head-of-household Schedule III through $72,000: 14,400 x 1.4% (201.60)
# + 7,200 x 3.2% (230.40) + 7,200 x 5.5% (396) + 7,200 x 6.4% (460.80)
# + 18,000 x 6.8% (1,224) + 18,000 x 7.2% (1,296) = 3,808.80
_HOH_TO_72_000 = 3_808.80


@pytest.mark.parametrize("filing_status, agi, expected_taxable, expected_tax", [
    # 80,000 - 8,000 = 72,000: 2,539.20 + 24,000 x 7.6% (1,824) = 4,363.20
    ("single", 80_000, 72_000, _SINGLE_TO_48_000 + 1_824.00),
    # 150,000 - 16,000 = 134,000: 5,078.40 + 38,000 x 7.6% (2,888) = 7,966.40
    ("married_filing_jointly", 150_000, 134_000, _JOINT_TO_96_000 + 2_888.00),
    # 100,000 - 12,000 = 88,000: 3,808.80 + 16,000 x 7.6% (1,216) = 5,024.80
    ("head_of_household", 100_000, 88_000, _HOH_TO_72_000 + 1_216.00),
    # 300,000 - 12,000 = 288,000: 3,808.80 + 115,500 x 7.6% (8,778)
    # + 75,000 x 7.9% (5,925) + 25,500 x 8.25% (2,103.75) = 20,615.55
    # (Schedule III: 18,512 + 25,500 x 8.25% = 20,615.75)
    ("head_of_household", 300_000, 288_000, 20_615.55),
])
def test_hi_2026_act_46_deductions_and_schedules(filing_status, agi, expected_taxable,
                                                  expected_tax):
    tax, taxable = _state_tax_and_taxable_income(agi, "HI", filing_status=filing_status,
                                                 tax_year=2026)
    assert taxable == pytest.approx(expected_taxable)
    assert tax == pytest.approx(expected_tax, abs=0.01)


def test_hi_head_of_household_through_calculate():
    result = calculate(100_000, 0, "head_of_household", state_code="HI", tax_year=2026,
                       earned_income=100_000, holder_age=45)
    assert result.state == pytest.approx(5_024.80, abs=0.01)
