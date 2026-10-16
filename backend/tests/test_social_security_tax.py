"""Tests for IRS Pub. 915 Social Security taxation worksheet (task 12.2.1).

Verifies the layered calculation replaces the old cliff model.
"""

import pytest

from coastmath.engine.tax_engine import _calculate_taxable_social_security

# ---------------------------------------------------------------------------
# Single filer tests
# ---------------------------------------------------------------------------

class TestSingleFiler:
    """Single filer: t1=$25k, t2=$34k, tier2_base=$4,500."""

    def test_below_tier1_threshold(self):
        """Provisional <= $25k → $0 taxable."""
        # SS=24k, other_income=13k → provisional = 13k + 12k = 25k
        result = _calculate_taxable_social_security(24_000.0, 13_000.0, "single")
        assert result == 0.0

    def test_just_above_tier1_threshold(self):
        """Provisional = $25,001 → taxable = $0.50 (not $12,000 cliff)."""
        # SS=24k, other_income=13_001 → provisional = 13_001 + 12_000 = 25_001
        result = _calculate_taxable_social_security(24_000.0, 13_001.0, "single")
        # min(0.5 * 24000, 0.5 * (25001 - 25000)) = min(12000, 0.50) = 0.50
        assert result == pytest.approx(0.50)

    def test_tier1_midrange(self):
        """Provisional = $30k → taxable = min(12k, 2.5k) = $2,500."""
        # SS=24k, other_income=18k → provisional = 18k + 12k = 30k
        result = _calculate_taxable_social_security(24_000.0, 18_000.0, "single")
        assert result == pytest.approx(2_500.0)

    def test_at_tier2_boundary(self):
        """Provisional = $34k → still in tier 1: min(12k, 4.5k) = $4,500."""
        # SS=24k, other_income=22k → provisional = 22k + 12k = 34k
        result = _calculate_taxable_social_security(24_000.0, 22_000.0, "single")
        assert result == pytest.approx(4_500.0)

    def test_tier2(self):
        """Provisional = $42k → tier 2: min(0.85*24k, 4500 + 0.85*(42k-34k))."""
        # SS=24k, other_income=30k → provisional = 30k + 12k = 42k
        result = _calculate_taxable_social_security(24_000.0, 30_000.0, "single")
        # min(20400, 4500 + 6800) = min(20400, 11300) = 11300
        assert result == pytest.approx(11_300.0)

    def test_tier2_high_income(self):
        """Very high provisional → capped at 85% of SS benefit."""
        # SS=24k, other_income=100k → provisional = 100k + 12k = 112k
        result = _calculate_taxable_social_security(24_000.0, 100_000.0, "single")
        # min(0.85 * 24000, 4500 + 0.85 * (112000 - 34000))
        # = min(20400, 4500 + 66300) = min(20400, 70800) = 20400
        assert result == pytest.approx(20_400.0)

    def test_small_ss_tier1_caps_at_half_benefit(self):
        """When SS is small, tier 1 caps at 0.5 * SS, not 0.5 * excess."""
        # SS=2k, other_income=28k → provisional = 28k + 1k = 29k
        result = _calculate_taxable_social_security(2_000.0, 28_000.0, "single")
        # min(0.5 * 2000, 0.5 * (29000 - 25000)) = min(1000, 2000) = 1000
        assert result == pytest.approx(1_000.0)


# ---------------------------------------------------------------------------
# MFJ filer tests
# ---------------------------------------------------------------------------

class TestMFJFiler:
    """MFJ filer: t1=$32k, t2=$44k, tier2_base=$6,000."""

    def test_below_tier1_threshold(self):
        """Provisional <= $32k → $0 taxable."""
        # SS=24k, other_income=20k → provisional = 20k + 12k = 32k
        result = _calculate_taxable_social_security(
            24_000.0, 20_000.0, "married_filing_jointly",
        )
        assert result == 0.0

    def test_tier1_midrange(self):
        """Provisional = $38k → min(12k, 3k) = $3,000."""
        # SS=24k, other_income=26k → provisional = 26k + 12k = 38k
        result = _calculate_taxable_social_security(
            24_000.0, 26_000.0, "married_filing_jointly",
        )
        # min(0.5 * 24000, 0.5 * (38000 - 32000)) = min(12000, 3000) = 3000
        assert result == pytest.approx(3_000.0)

    def test_at_tier2_boundary(self):
        """Provisional = $44k → tier 1 max: min(12k, 6k) = $6,000."""
        # SS=24k, other_income=32k → provisional = 32k + 12k = 44k
        result = _calculate_taxable_social_security(
            24_000.0, 32_000.0, "married_filing_jointly",
        )
        assert result == pytest.approx(6_000.0)

    def test_tier2(self):
        """Provisional = $50k → tier 2 formula."""
        # SS=24k, other_income=38k → provisional = 38k + 12k = 50k
        result = _calculate_taxable_social_security(
            24_000.0, 38_000.0, "married_filing_jointly",
        )
        # min(0.85 * 24000, 6000 + 0.85 * (50000 - 44000))
        # = min(20400, 6000 + 5100) = min(20400, 11100) = 11100
        assert result == pytest.approx(11_100.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_ss_income(self):
        result = _calculate_taxable_social_security(0.0, 50_000.0, "single")
        assert result == 0.0

    def test_negative_ss_income(self):
        result = _calculate_taxable_social_security(-100.0, 50_000.0, "single")
        assert result == 0.0

    def test_zero_other_income(self):
        """SS=30k, other=0 → provisional = 15k < 25k → $0."""
        result = _calculate_taxable_social_security(30_000.0, 0.0, "single")
        assert result == 0.0

    def test_head_of_household_uses_single_thresholds(self):
        """Non-MFJ statuses use single thresholds."""
        single = _calculate_taxable_social_security(24_000.0, 18_000.0, "single")
        hoh = _calculate_taxable_social_security(24_000.0, 18_000.0, "head_of_household")
        assert single == hoh
