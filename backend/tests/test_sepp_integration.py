"""Tests for SEPP 72(t) simulator integration (task 4.4.3)."""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine.sepp import calculate_sepp, get_sepp_end_age
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    PlanData,
    SEPPSettingsData,
)


def _plan(**overrides) -> PlanData:
    """Build a minimal PlanData with sensible defaults."""
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1990,
        filing_status="single",
        life_expectancy=70,  # max age 69, avoids RMD (age 73+)
        start_year=2025,
        milestones=[],
        income_streams=[],
        expenses=[],
        priorities=[],
        drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        accounts={},
    )
    defaults.update(overrides)
    return PlanData(**defaults)


IRA_ID = "ira-account-1"

# life_expectancy=65 → max age 64, SEPP active ages 50-59, no RMD overlap
_SEPP_LIFE_EXPECTANCY = 65
_SEPP_BIRTH_YEAR = 1970
_SEPP_START_YEAR = 2020  # age 50 at start
_SEPP_START_AGE = 50.0


def _plan_with_sepp(method: str = "fixed_amortization", **overrides) -> PlanData:
    """Build a plan with SEPP enabled on an IRA account."""
    accounts = {
        IRA_ID: AccountInfo(balance=500_000.0, account_type="traditional_ira"),
    }
    sepp = SEPPSettingsData(
        enabled=True,
        source_account_id=IRA_ID,
        method=method,
        start_age=_SEPP_START_AGE,
        interest_rate=0.05,
    )
    return _plan(
        birth_year=_SEPP_BIRTH_YEAR,
        start_year=_SEPP_START_YEAR,
        life_expectancy=_SEPP_LIFE_EXPECTANCY,
        accounts=accounts,
        sepp_settings=sepp,
        **overrides,
    )


# ---------------------------------------------------------------------------
# No SEPP — regression safety
# ---------------------------------------------------------------------------


class TestNoSEPP:
    def test_no_sepp_settings(self):
        """When sepp_settings is None, no SEPP withdrawals occur."""
        plan = _plan(
            accounts={IRA_ID: AccountInfo(balance=500_000.0, account_type="traditional_ira")},
        )
        result = run_simulation(plan)
        # Balance shouldn't decrease (no growth, no SEPP, no RMD — max age 69)
        for snap in result.yearly_snapshots:
            assert snap.accounts[IRA_ID] == pytest.approx(500_000.0)

    def test_sepp_disabled(self):
        """When sepp_settings.enabled is False, no withdrawals occur."""
        sepp = SEPPSettingsData(
            enabled=False,
            source_account_id=IRA_ID,
            method="fixed_amortization",
            start_age=50.0,
        )
        plan = _plan(
            accounts={IRA_ID: AccountInfo(balance=500_000.0, account_type="traditional_ira")},
            sepp_settings=sepp,
        )
        result = run_simulation(plan)
        for snap in result.yearly_snapshots:
            assert snap.accounts[IRA_ID] == pytest.approx(500_000.0)


# ---------------------------------------------------------------------------
# Fixed amortization method
# ---------------------------------------------------------------------------


class TestFixedAmortization:
    def test_withdrawals_during_active_period(self):
        """SEPP fixed amortization should withdraw the same amount each active year."""
        plan = _plan_with_sepp(method="fixed_amortization")
        result = run_simulation(plan)

        # Simulator now lets calculate_sepp() use IRS Single Life Table
        expected_annual = calculate_sepp(
            500_000.0, 50, "fixed_amortization", 0.05,
        )
        assert expected_annual > 0

        end_age = get_sepp_end_age(_SEPP_START_AGE)
        assert end_age == 59.5

        # Monthly installments end at 59.5, with only half of the age-59 year.
        for snap in result.yearly_snapshots:
            if snap.age >= 50 and snap.age < 59:
                # gross_income includes SEPP (full amount while balance sufficient)
                assert snap.gross_income >= expected_annual - 1.0
            elif snap.age == 59:
                assert snap.gross_income == pytest.approx(expected_annual / 2)
            elif snap.age >= 60:
                # After SEPP ends, no SEPP income
                assert snap.gross_income == pytest.approx(0.0, abs=1.0)

    def test_fixed_amount_cached(self):
        """Fixed amortization uses same amount each year (cached on first calc)."""
        plan = _plan_with_sepp(method="fixed_amortization")
        result = run_simulation(plan)

        expected_annual = calculate_sepp(
            500_000.0, 50, "fixed_amortization", 0.05,
        )

        active_incomes = [
            snap.gross_income
            for snap in result.yearly_snapshots
            if 50 <= snap.age < 55
        ]
        for income in active_incomes:
            assert income == pytest.approx(expected_annual, rel=0.01)

    def test_balance_decreases(self):
        """Source account balance should decrease by SEPP withdrawal each year."""
        plan = _plan_with_sepp(method="fixed_amortization")
        result = run_simulation(plan)

        expected_annual = calculate_sepp(
            500_000.0, 50, "fixed_amortization", 0.05,
        )
        first_snap = result.yearly_snapshots[0]  # age 50
        assert first_snap.accounts[IRA_ID] == pytest.approx(
            500_000.0 - expected_annual, rel=0.01,
        )


# ---------------------------------------------------------------------------
# Fixed annuitization method
# ---------------------------------------------------------------------------


class TestFixedAnnuitization:
    def test_withdrawals_consistent(self):
        """SEPP fixed annuitization should withdraw a consistent fixed amount."""
        plan = _plan_with_sepp(method="fixed_annuitization")
        result = run_simulation(plan)

        expected_annual = calculate_sepp(
            500_000.0, 50, "fixed_annuitization", 0.05,
        )
        assert expected_annual > 0

        active_incomes = [
            snap.gross_income
            for snap in result.yearly_snapshots
            if 50 <= snap.age < 55
        ]
        for income in active_incomes:
            assert income == pytest.approx(expected_annual, rel=0.01)


# ---------------------------------------------------------------------------
# RMD method — recalculates each year
# ---------------------------------------------------------------------------


class TestRMDMethod:
    def test_rmd_varies_by_year(self):
        """RMD method should recalculate based on current balance each year."""
        plan = _plan_with_sepp(method="rmd_method")
        result = run_simulation(plan)

        # First year: age 50, balance 500k — uses IRS Single Life Table
        first_withdrawal = calculate_sepp(
            500_000.0, 50, "rmd_method", 0.05,
        )
        first_snap = result.yearly_snapshots[0]
        assert first_snap.gross_income == pytest.approx(first_withdrawal, rel=0.01)

        # Second year: balance decreased, age 51 — IRS table lookup
        remaining = 500_000.0 - first_withdrawal
        second_withdrawal = calculate_sepp(
            remaining, 51, "rmd_method", 0.05,
        )
        second_snap = result.yearly_snapshots[1]
        assert second_snap.gross_income == pytest.approx(second_withdrawal, rel=0.01)

    def test_rmd_recalculates_from_balance(self):
        """RMD method recalculates from current balance each year, not cached."""
        # With growth > 0, balance changes non-linearly so RMD amounts diverge
        plan = _plan_with_sepp(
            method="rmd_method",
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.05),
        )
        result = run_simulation(plan)

        active_incomes = [
            snap.gross_income
            for snap in result.yearly_snapshots
            if 50 <= snap.age < 55
        ]
        # With growth, amounts should differ year to year
        assert len({round(x, 2) for x in active_incomes}) > 1


# ---------------------------------------------------------------------------
# SEPP stops at end age
# ---------------------------------------------------------------------------


class TestSEPPEndAge:
    def test_sepp_stops_after_end_age(self):
        """After SEPP end age, no more SEPP withdrawals."""
        plan = _plan_with_sepp(method="fixed_amortization")
        result = run_simulation(plan)

        # SEPP end age for start_age=50 is 59.5
        # With fix: ceil(59.5) = 60, so SEPP active through age 60
        # is_sepp_active(60, 50) → 60 <= 60 → True (active, includes year containing 59½)
        # is_sepp_active(61, 50) → 61 <= 60 → False (inactive)
        for snap in result.yearly_snapshots:
            if snap.age >= 61:
                assert snap.gross_income == pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# Edge case: balance runs out
# ---------------------------------------------------------------------------


class TestSEPPBalanceCap:
    def test_sepp_capped_at_balance(self):
        """SEPP withdrawal should not exceed account balance."""
        accounts = {
            IRA_ID: AccountInfo(balance=1_000.0, account_type="traditional_ira"),
        }
        sepp = SEPPSettingsData(
            enabled=True,
            source_account_id=IRA_ID,
            method="fixed_amortization",
            start_age=50.0,
            interest_rate=0.05,
        )
        plan = _plan(
            birth_year=1970,
            start_year=2020,
            life_expectancy=65,
            accounts=accounts,
            sepp_settings=sepp,
        )
        result = run_simulation(plan)

        # Balance should never go negative
        for snap in result.yearly_snapshots:
            assert snap.accounts[IRA_ID] >= -0.01
