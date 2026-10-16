"""Tests for cost basis tracking logic."""

import pytest

from coastmath.engine.cost_basis import (
    calculate_gain_on_withdrawal,
    update_cost_basis_on_deposit,
)
from coastmath.engine.types import AccountInfo, SimState

# ---------------------------------------------------------------------------
# Pure function tests — calculate_gain_on_withdrawal
# ---------------------------------------------------------------------------

class TestCalculateGainOnWithdrawal:
    def test_basic_gain(self):
        """50% gain: balance 200, basis 100, withdraw 100 -> gain 50."""
        gain, new_basis = calculate_gain_on_withdrawal(100, 200, 100)
        assert gain == pytest.approx(50.0)
        assert new_basis == pytest.approx(50.0)

    def test_no_gain_when_basis_equals_balance(self):
        """No appreciation: all value is cost basis."""
        gain, new_basis = calculate_gain_on_withdrawal(500, 1000, 1000)
        assert gain == pytest.approx(0.0)
        assert new_basis == pytest.approx(500.0)

    def test_full_withdrawal(self):
        """Withdraw everything — basis goes to 0."""
        gain, new_basis = calculate_gain_on_withdrawal(1000, 1000, 400)
        assert gain == pytest.approx(600.0)
        assert new_basis == pytest.approx(0.0)

    def test_zero_balance(self):
        """Zero balance returns no gain."""
        gain, new_basis = calculate_gain_on_withdrawal(100, 0, 0)
        assert gain == 0.0
        assert new_basis == 0.0

    def test_zero_withdrawal(self):
        """No withdrawal means no change."""
        gain, new_basis = calculate_gain_on_withdrawal(0, 1000, 500)
        assert gain == 0.0
        assert new_basis == 500.0

    def test_basis_exceeds_balance(self):
        """Selling below basis realizes a proportional capital loss."""
        gain, new_basis = calculate_gain_on_withdrawal(50, 100, 150)
        assert gain == -25.0  # proportional sale realizes the loss
        # Basis decreases proportionally
        assert new_basis == pytest.approx(75.0)

    def test_small_partial_withdrawal(self):
        """Withdraw 10% of a position with 50% gain."""
        # Balance 10000, basis 5000, withdraw 1000
        gain, new_basis = calculate_gain_on_withdrawal(1000, 10000, 5000)
        assert gain == pytest.approx(500.0)
        assert new_basis == pytest.approx(4500.0)


# ---------------------------------------------------------------------------
# Pure function tests — update_cost_basis_on_deposit
# ---------------------------------------------------------------------------

class TestUpdateCostBasisOnDeposit:
    def test_basic_deposit(self):
        result = update_cost_basis_on_deposit(5000, 10000)
        assert result == 15000.0

    def test_zero_deposit(self):
        result = update_cost_basis_on_deposit(0, 10000)
        assert result == 10000.0

    def test_negative_deposit(self):
        result = update_cost_basis_on_deposit(-100, 10000)
        assert result == 10000.0

    def test_first_deposit(self):
        result = update_cost_basis_on_deposit(1000, 0)
        assert result == 1000.0


# ---------------------------------------------------------------------------
# SimState integration tests
# ---------------------------------------------------------------------------

class TestSimStateCostBasis:
    def _make_state(self) -> SimState:
        return SimState(
            year=2025,
            accounts={
                "brokerage": AccountInfo(
                    balance=10000, account_type="taxable_brokerage", cost_basis=5000,
                ),
                "ira": AccountInfo(
                    balance=50000, account_type="traditional_ira", cost_basis=0,
                ),
                "roth": AccountInfo(
                    balance=30000, account_type="roth_ira", cost_basis=0,
                ),
                "checking": AccountInfo(
                    balance=5000, account_type="checking", cost_basis=0,
                ),
            },
        )

    def test_withdraw_taxable_generates_gain(self):
        state = self._make_state()
        state.withdraw_from("brokerage", 2000)
        # gain = 2000 * (1 - 5000/10000) = 1000
        assert state.capital_gains_this_year == pytest.approx(1000.0)
        assert state.accounts["brokerage"].balance == pytest.approx(8000.0)
        # basis = 5000 * (1 - 2000/10000) = 4000
        assert state.accounts["brokerage"].cost_basis == pytest.approx(4000.0)

    def test_withdraw_ira_no_gain(self):
        state = self._make_state()
        state.withdraw_from("ira", 10000)
        assert state.capital_gains_this_year == 0.0
        assert state.accounts["ira"].balance == pytest.approx(40000.0)

    def test_withdraw_roth_no_gain(self):
        state = self._make_state()
        state.withdraw_from("roth", 5000)
        assert state.capital_gains_this_year == 0.0

    def test_withdraw_checking_no_gain(self):
        state = self._make_state()
        state.withdraw_from("checking", 1000)
        assert state.capital_gains_this_year == 0.0

    def test_deposit_taxable_increases_basis(self):
        state = self._make_state()
        state.deposit_to("brokerage", 3000)
        assert state.accounts["brokerage"].balance == pytest.approx(13000.0)
        assert state.accounts["brokerage"].cost_basis == pytest.approx(8000.0)

    def test_deposit_ira_no_basis_change(self):
        state = self._make_state()
        state.deposit_to("ira", 5000)
        assert state.accounts["ira"].cost_basis == 0.0

    def test_multiple_withdrawals_accumulate_gains(self):
        state = self._make_state()
        state.withdraw_from("brokerage", 2000)  # gain = 1000
        state.withdraw_from("brokerage", 2000)  # recalculate with updated basis
        assert state.capital_gains_this_year > 1000.0
        assert state.accounts["brokerage"].balance == pytest.approx(6000.0)

    def test_full_withdrawal_zeroes_basis(self):
        state = self._make_state()
        state.withdraw_from("brokerage", 10000)
        assert state.accounts["brokerage"].cost_basis == pytest.approx(0.0)
        assert state.capital_gains_this_year == pytest.approx(5000.0)
