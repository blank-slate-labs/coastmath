"""Tests for the SEPP 72(t) calculator module (task 4.4.1)."""

from __future__ import annotations

import math

import pytest

from coastmath.engine.rmd import single_life_divisor as rmd_divisor
from coastmath.engine.sepp import (
    _SINGLE_LIFE_TABLE,
    _compute_annuity_factor,
    calculate_sepp,
    get_sepp_end_age,
    is_sepp_active,
    single_life_expectancy,
)
from coastmath.engine.sepp import _SINGLE_LIFE_TABLE as sepp_table

# ---------------------------------------------------------------------------
# calculate_sepp — RMD method
# ---------------------------------------------------------------------------


class TestRMDMethod:
    def test_basic_rmd(self):
        """500k balance, age 72, divisor 27.4 -> 500000/27.4."""
        result = calculate_sepp(500_000, 72, "rmd_method")
        assert result == pytest.approx(500_000 / 27.4)

    def test_rmd_age_80(self):
        """500k balance, age 80, divisor 20.2."""
        result = calculate_sepp(500_000, 80, "rmd_method")
        assert result == pytest.approx(500_000 / 20.2)

    def test_rmd_zero_balance(self):
        result = calculate_sepp(0, 72, "rmd_method")
        assert result == 0.0

    def test_rmd_negative_balance(self):
        result = calculate_sepp(-100, 72, "rmd_method")
        assert result == 0.0

    def test_rmd_custom_divisor(self):
        """Custom divisor overrides the IRS table."""
        result = calculate_sepp(500_000, 72, "rmd_method", life_expectancy_divisor=30.0)
        assert result == pytest.approx(500_000 / 30.0)


# ---------------------------------------------------------------------------
# calculate_sepp — Fixed amortization
# ---------------------------------------------------------------------------


class TestFixedAmortization:
    def test_basic_amortization(self):
        """Known amortization: 500k, age 72, Single Life Table n=17.2, 5% rate."""
        balance = 500_000
        r = 0.05
        # Age 72 → 2022 Single Life Expectancy Table gives 17.2 years
        n = 17.2
        expected = balance * (r / (1 - math.pow(1 + r, -n)))
        result = calculate_sepp(balance, 72, "fixed_amortization", interest_rate=r)
        assert result == pytest.approx(expected)

    def test_amortization_zero_rate(self):
        """With 0% interest, amortization = balance / Single Life Table value."""
        # Age 72 → 2022 Single Life Expectancy = 17.2
        result = calculate_sepp(500_000, 72, "fixed_amortization", interest_rate=0.0)
        assert result == pytest.approx(500_000 / 17.2)

    def test_amortization_higher_rate(self):
        """Higher rate should produce larger annual payment."""
        low = calculate_sepp(500_000, 72, "fixed_amortization", interest_rate=0.03)
        high = calculate_sepp(500_000, 72, "fixed_amortization", interest_rate=0.07)
        assert high > low

    def test_amortization_custom_divisor(self):
        balance = 1_000_000
        r = 0.04
        divisor = 25.0
        expected = balance * (r / (1 - math.pow(1 + r, -divisor)))
        result = calculate_sepp(
            balance, 72, "fixed_amortization", interest_rate=r, life_expectancy_divisor=divisor
        )
        assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# calculate_sepp — Fixed annuitization
# ---------------------------------------------------------------------------


class TestFixedAnnuitization:
    def test_basic_annuitization(self):
        """500k, age 72, 5% rate — uses IRS mortality-based annuity factor."""
        balance = 500_000
        r = 0.05
        af = _compute_annuity_factor(72, r)
        expected = balance / af
        result = calculate_sepp(balance, 72, "fixed_annuitization", interest_rate=r)
        assert result == pytest.approx(expected)
        # Sanity: annuity-immediate AF should be reasonable for age 72 at 5%
        # (shorter remaining life + discounting yields ~7-10 range)
        assert 5.0 < af < 25.0

    def test_annuitization_zero_rate(self):
        """With 0% interest, annuity factor is pure mortality-weighted sum of years."""
        af = _compute_annuity_factor(72, 0.0)
        result = calculate_sepp(500_000, 72, "fixed_annuitization", interest_rate=0.0)
        assert result == pytest.approx(500_000 / af)

    def test_annuitization_higher_rate(self):
        """Higher rate -> smaller annuity factor -> larger payment."""
        low = calculate_sepp(500_000, 72, "fixed_annuitization", interest_rate=0.03)
        high = calculate_sepp(500_000, 72, "fixed_annuitization", interest_rate=0.07)
        assert high > low


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrors:
    def test_invalid_method(self):
        with pytest.raises(ValueError, match="Invalid SEPP method"):
            calculate_sepp(500_000, 72, "bogus_method")

    def test_age_below_uniform_table_uses_single_life(self):
        """Ages below 72 fall back to Single Life Table instead of raising."""
        result = calculate_sepp(500_000, 50, "rmd_method")
        assert result == pytest.approx(500_000 / _SINGLE_LIFE_TABLE[50])

    def test_age_above_table_uses_single_life(self):
        """Ages above 120 use the max Single Life Table entry."""
        divisor = single_life_expectancy(121)
        result = calculate_sepp(500_000, 121, "rmd_method")
        assert result == pytest.approx(500_000 / divisor)

    def test_age_below_table_with_override_works(self):
        """Providing a custom divisor bypasses the table lookup."""
        result = calculate_sepp(500_000, 50, "rmd_method", life_expectancy_divisor=35.0)
        assert result == pytest.approx(500_000 / 35.0)

    def test_zero_divisor_raises(self):
        with pytest.raises(ValueError, match="positive"):
            calculate_sepp(500_000, 72, "rmd_method", life_expectancy_divisor=0)


# ---------------------------------------------------------------------------
# get_sepp_end_age
# ---------------------------------------------------------------------------


class TestGetSEPPEndAge:
    def test_young_start_59_5_wins(self):
        """Starting at 50: 50+5=55 < 59.5, so end age is 59.5."""
        assert get_sepp_end_age(50) == 59.5

    def test_older_start_5_years_wins(self):
        """Starting at 56: 56+5=61 > 59.5, so end age is 61."""
        assert get_sepp_end_age(56) == 61

    def test_start_at_58(self):
        """Starting at 58: 58+5=63 > 59.5, so end age is 63."""
        assert get_sepp_end_age(58) == 63

    def test_start_at_54_5(self):
        """Starting at 54.5: 54.5+5=59.5, exactly tied."""
        assert get_sepp_end_age(54.5) == 59.5


# ---------------------------------------------------------------------------
# is_sepp_active
# ---------------------------------------------------------------------------


class TestIsSEPPActive:
    def test_inactive_before_start_age(self):
        """SEPP distributions must not begin before the configured start age."""
        assert is_sepp_active(45, 50) is False

    def test_active_young(self):
        """Started at 50, current 55 — still active (end is 59.5)."""
        assert is_sepp_active(55, 50) is True

    def test_active_boundary(self):
        """Started at 50, current 59 — still active (end is 59.5)."""
        assert is_sepp_active(59, 50) is True

    def test_inactive_at_60_for_59_5_end(self):
        """The age-59.5 modification date has passed."""
        assert is_sepp_active(60, 50) is False

    def test_inactive_past_ceil_end(self):
        """Started at 50, current 61 — inactive (ceil(59.5)=60, 61 > 60)."""
        assert is_sepp_active(61, 50) is False

    def test_active_older_start(self):
        """Started at 56, current 59 — still active (end is 61, ceil=61)."""
        assert is_sepp_active(59, 56) is True

    def test_inactive_older_start_at_end(self):
        """The fifth anniversary itself is no longer a required payment."""
        assert is_sepp_active(61, 56) is False

    def test_inactive_older_start(self):
        """Started at 56, current 62 — inactive (end was 61, ceil=61)."""
        assert is_sepp_active(62, 56) is False


# ---------------------------------------------------------------------------
# Single Life Table monotonicity
# ---------------------------------------------------------------------------


class TestSingleLifeTableMonotonicity:
    def test_sepp_single_life_table_is_monotonically_non_increasing(self):
        """Each age must have a life expectancy <= the previous age."""
        ages = sorted(_SINGLE_LIFE_TABLE.keys())
        for i in range(1, len(ages)):
            prev_age, curr_age = ages[i - 1], ages[i]
            assert _SINGLE_LIFE_TABLE[curr_age] <= _SINGLE_LIFE_TABLE[prev_age], (
                f"Non-monotonic at age {curr_age}: "
                f"{_SINGLE_LIFE_TABLE[curr_age]} > {_SINGLE_LIFE_TABLE[prev_age]} (age {prev_age})"
            )

    def test_sepp_single_life_table_covers_full_range(self):
        """Table must cover ages 0 through 120 with no gaps."""
        assert set(_SINGLE_LIFE_TABLE.keys()) == set(range(0, 121))

    def test_sepp_single_life_table_matches_rmd_for_overlapping_ages(self):
        """SEPP and RMD Single Life Tables must agree for overlapping ages."""
        for age in sepp_table:
            assert sepp_table[age] == rmd_divisor(age), (
                f"Mismatch at age {age}: sepp={sepp_table[age]}, rmd={rmd_divisor(age)}"
            )
