"""Tests for the RMD calculator module."""

import pytest

from coastmath.engine.rmd import (
    calculate_inherited_ira_rmd,
    calculate_rmd,
    get_rmd_start_age,
    is_rmd_required,
)
from coastmath.engine.single_life import SINGLE_LIFE_TABLE as _SINGLE_LIFE_TABLE

# ---------------------------------------------------------------------------
# get_rmd_start_age
# ---------------------------------------------------------------------------

class TestGetRmdStartAge:
    def test_born_1950_returns_72(self):
        assert get_rmd_start_age(1950) == 72

    def test_born_1945_returns_72(self):
        assert get_rmd_start_age(1945) == 72

    def test_born_1951_returns_73(self):
        assert get_rmd_start_age(1951) == 73

    def test_born_1955_returns_73(self):
        assert get_rmd_start_age(1955) == 73

    def test_born_1959_returns_73(self):
        assert get_rmd_start_age(1959) == 73

    def test_born_1960_returns_75(self):
        assert get_rmd_start_age(1960) == 75

    def test_born_1970_returns_75(self):
        assert get_rmd_start_age(1970) == 75

    def test_born_2000_returns_75(self):
        assert get_rmd_start_age(2000) == 75


# ---------------------------------------------------------------------------
# is_rmd_required
# ---------------------------------------------------------------------------

class TestIsRmdRequired:
    def test_age_72_not_required_born_1955(self):
        # Born 1955 → RMD at 73
        assert is_rmd_required(72, 1955) is False

    def test_age_73_required_born_1955(self):
        assert is_rmd_required(73, 1955) is True

    def test_age_100_required_born_1955(self):
        assert is_rmd_required(100, 1955) is True

    def test_young_age_not_required(self):
        assert is_rmd_required(40, 1955) is False

    def test_age_72_required_born_1950(self):
        # Born 1950 → RMD at 72
        assert is_rmd_required(72, 1950) is True

    def test_age_71_not_required_born_1950(self):
        assert is_rmd_required(71, 1950) is False

    def test_age_74_not_required_born_1960(self):
        # Born 1960 → RMD at 75
        assert is_rmd_required(74, 1960) is False

    def test_age_75_required_born_1960(self):
        assert is_rmd_required(75, 1960) is True


# ---------------------------------------------------------------------------
# calculate_rmd
# ---------------------------------------------------------------------------

class TestCalculateRmd:
    def test_age_73_known_divisor(self):
        # Divisor for age 73 is 26.5
        result = calculate_rmd(500_000, 73, 1955)
        assert result == pytest.approx(500_000 / 26.5)

    def test_age_80_known_divisor(self):
        # Divisor for age 80 is 20.2
        result = calculate_rmd(1_000_000, 80, 1955)
        assert result == pytest.approx(1_000_000 / 20.2)

    def test_age_below_73_returns_zero_born_1955(self):
        assert calculate_rmd(500_000, 72, 1955) == 0.0
        assert calculate_rmd(500_000, 50, 1955) == 0.0

    def test_zero_balance_returns_zero(self):
        assert calculate_rmd(0, 75, 1955) == 0.0

    def test_negative_balance_returns_zero(self):
        assert calculate_rmd(-100, 75, 1955) == 0.0

    def test_age_120_max_table_age(self):
        # Divisor for age 120 is 2.0 (the minimum)
        result = calculate_rmd(200_000, 120, 1955)
        assert result == pytest.approx(200_000 / 2.0)

    def test_age_beyond_table_uses_min_divisor(self):
        # Ages beyond 120 use the minimum divisor (2.0)
        result = calculate_rmd(200_000, 121, 1955)
        assert result == pytest.approx(200_000 / 2.0)

        result_130 = calculate_rmd(200_000, 130, 1955)
        assert result_130 == pytest.approx(200_000 / 2.0)

    def test_rmd_increases_with_age(self):
        """RMD amount increases with age (divisor gets smaller)."""
        balance = 1_000_000
        rmd_73 = calculate_rmd(balance, 73, 1955)
        rmd_80 = calculate_rmd(balance, 80, 1955)
        rmd_90 = calculate_rmd(balance, 90, 1955)
        assert rmd_73 < rmd_80 < rmd_90

    def test_born_1950_rmd_starts_at_72(self):
        """Born 1950 → RMD starts at 72."""
        assert calculate_rmd(500_000, 72, 1950) > 0.0
        assert calculate_rmd(500_000, 71, 1950) == 0.0

    def test_born_1960_rmd_starts_at_75(self):
        """Born 1960 → RMD starts at 75."""
        assert calculate_rmd(500_000, 75, 1960) > 0.0
        assert calculate_rmd(500_000, 74, 1960) == 0.0
        assert calculate_rmd(500_000, 73, 1960) == 0.0


# ---------------------------------------------------------------------------
# calculate_inherited_ira_rmd
# ---------------------------------------------------------------------------

class TestInheritedIraNonEdb:
    """Post-2019 non-EDB deaths before RBD: distribute by the tenth year."""

    @pytest.mark.parametrize("elapsed", [1, 5, 9])
    def test_before_rbd_no_interim_rmd(self, elapsed):
        assert calculate_inherited_ira_rmd(500_000, 2020, 2020 + elapsed) == 0

    @pytest.mark.parametrize("elapsed", [10, 15])
    def test_deadline_distributes_current_balance(self, elapsed):
        assert calculate_inherited_ira_rmd(100_000, 2020, 2020 + elapsed) == 100_000

    @pytest.mark.parametrize("balance", [0, -100])
    def test_nonpositive_balance(self, balance):
        assert calculate_inherited_ira_rmd(balance, 2020, 2025) == 0

    def test_death_year_without_unpaid_owner_rmd(self):
        assert calculate_inherited_ira_rmd(1_000_000, 2025, 2025) == 0

    def test_pre_2020_beneficiary_retains_life_expectancy(self):
        # First distribution in2016 at age50:36.2, reduced by9 in2025.
        assert calculate_inherited_ira_rmd(100_000, 2015, 2025, 59) == pytest.approx(100_000 / 27.2)


class TestInheritedIraEdb:
    """Eligible beneficiaries use lifetime distributions without a blanket deadline."""

    @pytest.mark.parametrize("beneficiary_type", ["edb", "spouse"])
    def test_age_required_for_life_expectancy(self, beneficiary_type):
        with pytest.raises(ValueError, match="age"):
            calculate_inherited_ira_rmd(900_000, 2024, 2025, beneficiary_type=beneficiary_type)

    def test_edb_uses_initial_age_then_subtracts_elapsed_years(self):
        # First distribution in2021 at age46 has40.0;2025 subtracts4.
        result = calculate_inherited_ira_rmd(500_000, 2020, 2025, 50, "edb")
        assert result == pytest.approx(500_000 / 36.0)

    def test_edb_death_year_only_unpaid_owner_rmd(self):
        assert calculate_inherited_ira_rmd(1_000_000, 2025, 2025, 50, "edb") == 0
        assert calculate_inherited_ira_rmd(1_000_000, 2025, 2025, 50, "edb", year_of_death_rmd_remaining=2000) == 2000

    def test_spouse_recalculates_current_age(self):
        assert calculate_inherited_ira_rmd(500_000, 2020, 2031, 65, "spouse") == pytest.approx(500_000 / 22.9)

    def test_zero_balance(self):
        assert calculate_inherited_ira_rmd(0, 2020, 2025, beneficiary_type="edb") == 0


# ---------------------------------------------------------------------------
# Single Life Table monotonicity
# ---------------------------------------------------------------------------

class TestRmdSingleLifeTableMonotonicity:
    def test_rmd_single_life_table_is_monotonically_non_increasing(self):
        """Each age must have a life expectancy <= the previous age."""
        ages = sorted(_SINGLE_LIFE_TABLE.keys())
        for i in range(1, len(ages)):
            prev_age, curr_age = ages[i - 1], ages[i]
            assert _SINGLE_LIFE_TABLE[curr_age] <= _SINGLE_LIFE_TABLE[prev_age], (
                f"Non-monotonic at age {curr_age}: "
                f"{_SINGLE_LIFE_TABLE[curr_age]} > {_SINGLE_LIFE_TABLE[prev_age]} (age {prev_age})"
            )
