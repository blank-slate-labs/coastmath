"""Tests for the Social Security benefit estimator."""

import pytest

from coastmath.engine.social_security import estimate_ss_benefit


class TestEstimateSsBenefit:
    def test_average_earner_at_fra(self):
        # 15000*0.9 + 35000*0.32 = 24,700
        assert estimate_ss_benefit(50_000, claiming_age=67) == pytest.approx(24_700)

    def test_high_earner_at_fra(self):
        # 15000*0.9 + 75000*0.32 + 10000*0.15 = 39,000
        assert estimate_ss_benefit(100_000, claiming_age=67) == pytest.approx(39_000)

    def test_very_high_earner_capped_at_wage_base(self):
        # 2026 max worker benefit at FRA ($4,152/mo) caps the simplified estimate.
        assert estimate_ss_benefit(200_000, claiming_age=67) == pytest.approx(49_824)

    def test_early_claim_at_62_is_70_percent_of_fra(self):
        at_67 = estimate_ss_benefit(50_000, claiming_age=67)
        at_62 = estimate_ss_benefit(50_000, claiming_age=62)
        assert at_62 == pytest.approx(at_67 * 0.70)

    def test_delayed_claim_at_70_is_124_percent_of_fra(self):
        at_67 = estimate_ss_benefit(50_000, claiming_age=67)
        at_70 = estimate_ss_benefit(50_000, claiming_age=70)
        assert at_70 == pytest.approx(at_67 * 1.24)

    def test_default_claiming_age_is_fra(self):
        assert estimate_ss_benefit(50_000) == estimate_ss_benefit(50_000, claiming_age=67)

    def test_benefit_monotonic_in_income_up_to_wage_base(self):
        b_low = estimate_ss_benefit(30_000)
        b_mid = estimate_ss_benefit(80_000)
        b_high = estimate_ss_benefit(150_000)
        assert b_low < b_mid < b_high

    def test_benefit_plateaus_above_wage_base(self):
        at_wage_base = estimate_ss_benefit(184_500)
        well_above = estimate_ss_benefit(500_000)
        assert at_wage_base == pytest.approx(well_above)

    def test_low_earner_below_first_bend_point(self):
        # 10000 * 0.9 = 9,000
        assert estimate_ss_benefit(10_000, claiming_age=67) == pytest.approx(9_000)

    def test_delayed_credits_stop_accruing_at_seventy(self):
        assert estimate_ss_benefit(50_000, claiming_age=75) == pytest.approx(24_700 * 1.24)
