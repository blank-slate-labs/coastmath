"""State income tax schedules by filing status.

New Jersey, Maryland and New York give joint filers and heads of household
their own schedules rather than doubled single ones; DC, Virginia and
Massachusetts use one schedule for every filer; California's Behavioral
Health Services Tax threshold is neither doubled nor indexed; and Maryland's
capital gain surtax applies to the whole net gain above an unindexed AGI
threshold.

Expected values come from the cited schedules and rules, not from engine
output.
"""

import pytest

from coastmath.engine.state_tax_allocation import CAPartYearWageContext
from coastmath.engine.tax_engine import _calculate_state_tax, calculate

# ---------------------------------------------------------------------------
# Joint and head-of-household state schedules
# NJ-1040 (2025) Table B covers joint filers, heads of household and
# surviving spouses. Maryland Tax Alert (2025 session) Schedule II covers
# the same statuses. DC, VA and MA use one schedule for every filer.
# ---------------------------------------------------------------------------


class TestJointStateSchedules:
    @pytest.mark.parametrize(("state", "status", "agi", "expected"), [
        # Table B: 280 + 525 + 490 + 350 + 3,867.50 + 22,295 + 44,850.
        ("NJ", "married_filing_jointly", 1_000_000, 72_657.50),
        # Table B at $100K: .05525 x 100,000 - 2,775.
        ("NJ", "head_of_household", 100_000, 2_750.00),
        # Table A is unchanged for single filers: .1075 x 1,000,000 - 32,926.25.
        ("NJ", "single", 1_000_000, 74_573.75),
        # DC: $42,775 at $500,000 for every filer; $30,000 joint deduction.
        ("DC", "married_filing_jointly", 530_000, 42_775.00),
        # VA: 60 + 60 + 600 + 5.75% x 83,000; $17,500 joint deduction.
        ("VA", "married_filing_jointly", 117_500, 5_492.50),
        # MD Schedule II, $300K taxable after the $6,800 joint deduction:
        # 90 + 4.75% x 147,000 + 5% x 25,000 + 5.25% x 50,000 + 5.5% x 75,000.
        ("MD", "married_filing_jointly", 306_800, 15_072.50),
        ("MD", "head_of_household", 306_800, 15_072.50),
        # MD Schedule II to $1.2M: + 5.75% x 300,000 + 6.25% x 600,000.
        ("MD", "married_filing_jointly", 1_206_800, 69_822.50),
        # MA: the 9% surtax threshold applies per return.
        ("MA", "married_filing_jointly", 1_500_000, 0.05 * 1_107_750 + 0.09 * 392_250),
    ])
    def test_published_schedule(self, state, status, agi, expected):
        assert _calculate_state_tax(agi, state, filing_status=status, tax_year=2026) == pytest.approx(expected)

    def test_full_calculation_uses_the_joint_schedule(self):
        result = calculate(1_000_000, 0, "married_filing_jointly", state_code="NJ",
                           earned_income=1_000_000, w2_income_by_owner={"self": 1_000_000}, tax_year=2026)
        assert result.state == pytest.approx(72_657.50)

    def test_custom_brackets_keep_the_doubling_convention(self):
        custom = [{"min": 0, "max": 100_000, "rate": 0.01}, {"min": 100_000, "max": 999_999_999, "rate": 0.02}]
        assert _calculate_state_tax(300_000, "NJ", custom_brackets=custom,
                                    filing_status="married_filing_jointly") == pytest.approx(
            200_000 * 0.01 + 100_000 * 0.02)


# ---------------------------------------------------------------------------
# California Behavioral Health Services Tax
# R&TC 17043; Form 540 line 62: 1% of taxable income over $1,000,000 for
# every filing status. The threshold is neither doubled nor indexed.
# ---------------------------------------------------------------------------


class TestCaliforniaBehavioralHealthTax:
    # Joint schedule (2x the 2025 single thresholds) on $1.5M taxable:
    # 221.58 + 607.40 + 1,215.04 + 1,930.80 + 2,429.12 + 55,568.43
    # + 15,304.152 + 67,163.132 + 1,733.562 = 146,173.216, plus 1% x 500,000.
    JOINT_1_5M = 146_173.216 + 5_000
    # Head-of-household table on $1.5M taxable: 157,691.62 plus 5,000.
    HOH_1_5M = 157_691.617 + 5_000

    def test_joint_threshold_is_not_doubled(self):
        tax = _calculate_state_tax(1_500_000 + 2 * 5_706, "CA", filing_status="married_filing_jointly")
        assert tax == pytest.approx(self.JOINT_1_5M, abs=0.01)

    def test_head_of_household_owes_the_levy(self):
        tax = _calculate_state_tax(1_500_000 + 11_412, "CA", filing_status="head_of_household")
        assert tax == pytest.approx(self.HOH_1_5M, abs=0.01)

    def test_single_filer_is_unchanged(self):
        # 12.3% above $742,953 and 1% above $1M: $100K more taxable income
        # above $1M costs exactly 13.3%.
        low = _calculate_state_tax(1_100_000 + 5_706, "CA")
        high = _calculate_state_tax(1_200_000 + 5_706, "CA")
        assert high - low == pytest.approx(13_300)

    def test_threshold_is_not_indexed(self):
        # 2028 with 20% cumulative inflation: brackets scale (12.3% starts at
        # $891,543.60) but the levy still starts at $1,000,000.
        deduction = 5_706 * 1.2
        low = _calculate_state_tax(1_000_000 + deduction, "CA", inflation_factor=1.2, tax_year=2028)
        high = _calculate_state_tax(1_100_000 + deduction, "CA", inflation_factor=1.2, tax_year=2028)
        assert high - low == pytest.approx(13_300)

    def test_all_california_part_year_allocation_includes_the_levy(self):
        wages = 1_500_000 + 2 * 5_706
        context = CAPartYearWageContext(total_w2_wages=wages, ca_w2_wages=wages,
                                        legacy_residual_in_ca=True, residency_state_codes=("TX", "CA"))
        result = calculate(wages, 0, "married_filing_jointly", state_code="CA", earned_income=wages,
                           w2_income_by_owner={"self": wages}, ca_part_year_context=context)
        assert result.state == pytest.approx(self.JOINT_1_5M, abs=0.01)


# ---------------------------------------------------------------------------
# New York: IT-2105-I (2026) gives joint filers their
# own schedule (3.9% to $17,150 ... 6.85% to $2,155,350) and a $16,050
# deduction, not twice the single ones.
# ---------------------------------------------------------------------------


class TestNewYorkJointSchedule:
    @pytest.mark.parametrize(("taxable", "expected"), [
        # 17,928.55 at $323,200 + 6.85% x 176,800.
        (500_000, 30_039.35),
        # 8,391.20 at $161,550 + 5.9% x 38,450.
        (200_000, 10_659.75),
    ])
    def test_joint_tax(self, taxable, expected):
        tax = _calculate_state_tax(taxable + 16_050, "NY", filing_status="married_filing_jointly")
        assert tax == pytest.approx(expected, abs=0.01)

    def test_single_unchanged(self):
        # 8,500 x 3.9% + 3,200 x 4.4% + 2,200 x 5.15% + 66,750 x 5.4% + 19,350 x 5.9%.
        assert _calculate_state_tax(108_000, "NY", filing_status="single") == pytest.approx(
            331.5 + 140.8 + 113.3 + 3_604.5 + 1_141.65, abs=0.01)


# ---------------------------------------------------------------------------
# Maryland TG 10-105(a)(3)(i) (Technical Bulletin No.
# 58): 2% of the whole net capital gain when federal AGI exceeds $350,000,
# for every filing status; the threshold is not indexed.
# ---------------------------------------------------------------------------


class TestMarylandCapitalGainSurtax:
    @pytest.mark.parametrize(("agi", "status", "factor", "surtax"), [
        (400_000, "single", 1.0, 2_000.0),
        (400_000, "married_filing_jointly", 1.0, 2_000.0),
        (400_000, "single", 1.5, 2_000.0),   # threshold not indexed
        (350_000, "single", 1.0, 0.0),       # "in excess of" $350,000
    ])
    def test_surtax(self, agi, status, factor, surtax):
        with_gain = _calculate_state_tax(agi, "MD", filing_status=status, inflation_factor=factor,
                                         net_long_term_capital_gains=100_000)
        without = _calculate_state_tax(agi, "MD", filing_status=status, inflation_factor=factor)
        assert with_gain - without == pytest.approx(surtax)

    def test_full_calculation(self):
        r = calculate(300_000, 0, "single", state_code="MD", capital_gains=100_000,
                      earned_income=300_000, tax_year=2026)
        base = calculate(300_000, 0, "single", state_code="MD", capital_gains=0, qualified_dividends=100_000,
                         earned_income=300_000, tax_year=2026)
        # Qualified dividends are not IRC 1222 capital gain, so only the
        # sale gain carries the 2%.
        assert r.state - base.state == pytest.approx(2_000.0)
