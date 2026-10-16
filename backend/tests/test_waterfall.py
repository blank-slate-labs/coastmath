"""Tests for the waterfall engine (surplus allocation and drawdown)."""

import pytest

from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import (
    ConversionTaxContext,
    allocate_payroll_contributions,
    allocate_surplus,
    execute_drawdown,
    execute_gain_harvests,
    execute_roth_conversions,
    execute_transfers,
)


def _make_state(accounts: dict[str, float], year: int = 2025) -> SimState:
    """Helper to build a SimState with named accounts."""
    return SimState(
        year=year,
        accounts={
            aid: AccountInfo(balance=bal, account_type="brokerage")
            for aid, bal in accounts.items()
        },
    )


# ---------------------------------------------------------------------------
# allocate_surplus
# ---------------------------------------------------------------------------

class TestAllocateSurplus:
    def test_basic_priority_order(self):
        state = _make_state({"a": 0, "b": 0})
        priorities = [
            PriorityData(priority_rank=2, target_account_id="b", max_annual_amount=3000),
            PriorityData(priority_rank=1, target_account_id="a", max_annual_amount=5000),
        ]
        result = allocate_surplus(10000, priorities, state)
        assert result["a"] == 5000
        assert result["b"] == 3000
        assert state.get_balance("a") == 5000
        assert state.get_balance("b") == 3000

    def test_unlimited_cap(self):
        state = _make_state({"a": 0, "b": 0})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="a", max_annual_amount=None),
            PriorityData(priority_rank=2, target_account_id="b", max_annual_amount=5000),
        ]
        result = allocate_surplus(10000, priorities, state)
        # All surplus goes to first (unlimited) priority
        assert result["a"] == 10000
        assert "b" not in result
        assert state.get_balance("a") == 10000

    def test_surplus_less_than_cap(self):
        state = _make_state({"a": 0})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="a", max_annual_amount=50000),
        ]
        result = allocate_surplus(1000, priorities, state)
        assert result["a"] == 1000

    def test_zero_surplus(self):
        state = _make_state({"a": 100})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="a"),
        ]
        result = allocate_surplus(0, priorities, state)
        assert result == {}
        assert state.get_balance("a") == 100  # unchanged

    def test_empty_priorities(self):
        state = _make_state({"a": 0})
        result = allocate_surplus(5000, [], state)
        assert result == {}

    def test_skip_none_account_id(self):
        state = _make_state({"a": 0})
        priorities = [
            PriorityData(priority_rank=1, target_account_id=None),
            PriorityData(priority_rank=2, target_account_id="a", max_annual_amount=None),
        ]
        result = allocate_surplus(5000, priorities, state)
        assert result["a"] == 5000

    def test_deposits_add_to_existing_balance(self):
        state = _make_state({"a": 1000})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="a", max_annual_amount=None),
        ]
        allocate_surplus(500, priorities, state)
        assert state.get_balance("a") == 1500

    def test_target_balance_stops_maintain_balance_priority(self):
        state = _make_state({"cash": 25_000, "brokerage": 0})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="cash", target_balance=40_000),
            PriorityData(priority_rank=2, target_account_id="brokerage"),
        ]

        result = allocate_surplus(25_000, priorities, state)

        assert result == {"cash": 15_000, "brokerage": 10_000}
        assert state.get_balance("cash") == 40_000

    def test_target_balance_is_absolute_in_partial_year(self):
        state = _make_state({"cash": 25_000, "brokerage": 0})
        priorities = [
            PriorityData(priority_rank=1, target_account_id="cash", target_balance=40_000),
            PriorityData(priority_rank=2, target_account_id="brokerage"),
        ]

        result = allocate_surplus(
            25_000,
            priorities,
            state,
            target_balance_fraction=1 / 3,
        )

        assert result == {"cash": 15_000, "brokerage": 10_000}
        assert state.get_balance("cash") == 40_000


class TestPayrollContributions:
    def test_income_percent_employee_and_employer_amounts(self):
        state = SimState(
            year=2026,
            accounts={
                "401k": AccountInfo(balance=100_000, account_type="traditional_401k"),
            },
        )
        priorities = [
            PriorityData(
                priority_rank=1,
                target_account_id="401k",
                priority_type="income_percent",
                source_income_id="salary",
                employee_rate=0.06,
                employer_match_rate=0.04,
            ),
        ]

        result = allocate_payroll_contributions(
            priorities,
            {"salary": 110_000},
            state,
            age=44,
        )

        assert len(result) == 1
        assert result[0].employee_amount == 6_600
        assert result[0].employer_amount == 4_400
        assert state.get_balance("401k") == 111_000
        assert state.ytd_contributions["401k"] == 6_600

    def test_employee_amount_respects_irs_limit_but_match_does_not_consume_it(self):
        state = SimState(
            year=2026,
            accounts={
                "401k": AccountInfo(balance=0, account_type="traditional_401k"),
            },
        )
        priorities = [
            PriorityData(
                priority_rank=1,
                target_account_id="401k",
                priority_type="income_percent",
                source_income_id="salary",
                employee_rate=0.50,
                employer_match_rate=0.10,
            ),
        ]

        result = allocate_payroll_contributions(
            priorities,
            {"salary": 100_000},
            state,
            age=40,
        )

        assert result[0].employee_amount == 24_500
        assert result[0].employer_amount == 10_000
        assert state.get_balance("401k") == 34_500
        assert state.ytd_contributions["401k"] == 24_500

    def test_pre_tax_hsa_maximizes_legal_limit(self):
        state = SimState(
            year=2026,
            accounts={"hsa": AccountInfo(balance=0, account_type="hsa")},
        )
        priorities = [
            PriorityData(
                priority_rank=1,
                target_account_id="hsa",
                priority_type="pre_tax_contribution",
            ),
        ]

        result = allocate_payroll_contributions(
            priorities,
            {"salary": 150_000},
            state,
            age=47,
        )

        assert result[0].employee_amount == 4_400
        assert result[0].employer_amount == 0
        assert state.get_balance("hsa") == 4_400

    def test_payroll_priorities_are_not_funded_again_from_surplus(self):
        state = SimState(
            year=2026,
            accounts={"401k": AccountInfo(balance=0, account_type="traditional_401k")},
        )
        priority = PriorityData(
            priority_rank=1,
            target_account_id="401k",
            priority_type="income_percent",
            source_income_id="salary",
            employee_rate=0.10,
        )
        allocate_payroll_contributions([priority], {"salary": 100_000}, state, age=40)

        assert allocate_surplus(5_000, [priority], state, age=40) == {}
        assert state.get_balance("401k") == 10_000


# ---------------------------------------------------------------------------
# execute_drawdown
# ---------------------------------------------------------------------------

class TestExecuteDrawdown:
    def test_basic_rank_order(self):
        state = _make_state({"a": 5000, "b": 10000})
        order = [
            DrawdownEntryData(rank=2, source_account_id="b"),
            DrawdownEntryData(rank=1, source_account_id="a"),
        ]
        result, penalty = execute_drawdown(7000, order, state)
        # Draws 5000 from a first, then 2000 from b
        assert result["a"] == 5000
        assert result["b"] == 2000
        assert state.get_balance("a") == 0
        assert state.get_balance("b") == 8000
        assert penalty == 0.0  # brokerage accounts — no penalty

    def test_account_withholding_grosses_up_net_deficit(self):
        state = SimState(
            year=2025,
            accounts={
                "taxable": AccountInfo(
                    balance=100_000,
                    account_type="taxable_brokerage",
                    cost_basis=50_000,
                ),
            },
        )
        order = [DrawdownEntryData(rank=1, source_account_id="taxable")]

        result, penalty = execute_drawdown(
            9_000,
            order,
            state,
            withholding_rates={"taxable_brokerage": 0.10},
        )

        expected_gross = 9_000 / (1.0 - 0.10 * 0.50)
        assert result["taxable"] == pytest.approx(expected_gross)
        assert state.drawdown_tax_withheld_this_year == pytest.approx(
            expected_gross * 0.10 * 0.50,
        )
        assert state.get_balance("taxable") == pytest.approx(100_000 - expected_gross)
        assert penalty == 0.0
        assert state.failure_year is None

    def test_clamp_to_balance(self):
        state = _make_state({"a": 300})
        order = [DrawdownEntryData(rank=1, source_account_id="a")]
        result, _ = execute_drawdown(1000, order, state)
        assert result["a"] == 300
        assert state.get_balance("a") == 0
        # Shortfall → failure
        assert state.failure_year == 2025

    def test_failure_year_set_on_exhaustion(self):
        state = _make_state({"a": 100, "b": 200}, year=2030)
        order = [
            DrawdownEntryData(rank=1, source_account_id="a"),
            DrawdownEntryData(rank=2, source_account_id="b"),
        ]
        result, _ = execute_drawdown(500, order, state)
        assert result["a"] == 100
        assert result["b"] == 200
        assert state.failure_year == 2030

    def test_no_failure_when_fully_covered(self):
        state = _make_state({"a": 10000})
        order = [DrawdownEntryData(rank=1, source_account_id="a")]
        result, _ = execute_drawdown(3000, order, state)
        assert result["a"] == 3000
        assert state.failure_year is None

    def test_zero_deficit(self):
        state = _make_state({"a": 5000})
        order = [DrawdownEntryData(rank=1, source_account_id="a")]
        result, penalty = execute_drawdown(0, order, state)
        assert result == {}
        assert penalty == 0.0
        assert state.get_balance("a") == 5000

    def test_empty_drawdown_order_with_deficit(self):
        state = _make_state({}, year=2028)
        result, _ = execute_drawdown(1000, [], state)
        assert result == {}
        assert state.failure_year == 2028

    def test_skip_none_source_account(self):
        state = _make_state({"b": 5000})
        order = [
            DrawdownEntryData(rank=1, source_account_id=None),
            DrawdownEntryData(rank=2, source_account_id="b"),
        ]
        result, _ = execute_drawdown(3000, order, state)
        assert result["b"] == 3000


# ---------------------------------------------------------------------------
# Roth conversion
# ---------------------------------------------------------------------------

class TestRothConversion:
    def _make_state_with_types(
        self, accounts: dict[str, tuple[float, str]], year: int = 2025
    ) -> SimState:
        """Build SimState with explicit account types."""
        return SimState(
            year=year,
            accounts={
                aid: AccountInfo(balance=bal, account_type=atype)
                for aid, (bal, atype) in accounts.items()
            },
        )

    def test_basic_roth_conversion(self):
        """Withdraws from source, deposits to target, tracks conversion amount."""
        state = self._make_state_with_types({
            "trad_ira": (100_000, "traditional_ira"),
            "roth_ira": (50_000, "roth_ira"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id="roth_ira",
                max_annual_amount=20_000,
            ),
        ]
        result = execute_roth_conversions(priorities, state)
        assert result["roth_ira"] == 20_000
        assert state.get_balance("trad_ira") == 80_000
        assert state.get_balance("roth_ira") == 70_000
        assert state.roth_conversions_this_year == 20_000

    def test_capped_by_source_balance(self):
        """Conversion cannot exceed source account balance."""
        state = self._make_state_with_types({
            "trad_ira": (5_000, "traditional_ira"),
            "roth_ira": (0, "roth_ira"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id="roth_ira",
                max_annual_amount=20_000,
            ),
        ]
        result = execute_roth_conversions(priorities, state)
        assert result["roth_ira"] == 5_000
        assert state.get_balance("trad_ira") == 0
        assert state.roth_conversions_this_year == 5_000

    def test_capped_by_max_annual_amount(self):
        """Conversion is capped by max_annual_amount, not surplus."""
        state = self._make_state_with_types({
            "trad_ira": (100_000, "traditional_ira"),
            "roth_ira": (0, "roth_ira"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id="roth_ira",
                max_annual_amount=50_000,
            ),
        ]
        result = execute_roth_conversions(priorities, state)
        assert result["roth_ira"] == 50_000
        assert state.get_balance("trad_ira") == 50_000

    def test_no_cap(self):
        """Conversion with no max_annual_amount converts full source balance."""
        state = self._make_state_with_types({
            "trad_ira": (100_000, "traditional_ira"),
            "roth_ira": (0, "roth_ira"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id="roth_ira",
            ),
        ]
        result = execute_roth_conversions(priorities, state)
        assert result["roth_ira"] == 100_000
        assert state.get_balance("trad_ira") == 0

    def test_independent_of_surplus(self):
        """Roth conversions execute even when there is zero surplus."""
        state = self._make_state_with_types({
            "trad_ira": (100_000, "traditional_ira"),
            "roth_ira": (0, "roth_ira"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id="roth_ira",
                max_annual_amount=25_000,
            ),
        ]
        # No surplus needed — execute_roth_conversions is independent
        result = execute_roth_conversions(priorities, state)
        assert result["roth_ira"] == 25_000
        assert state.get_balance("trad_ira") == 75_000

    def test_reject_if_no_source(self):
        """Incomplete rules fail before moving money."""
        state = self._make_state_with_types({
            "roth_ira": (0, "roth_ira"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id=None,
                target_account_id="roth_ira",
                max_annual_amount=10_000,
            ),
        ]
        with pytest.raises(ValueError, match="Roth conversions require"):
            execute_roth_conversions(priorities, state)
        assert state.roth_conversions_this_year == 0
        assert state.get_balance("roth_ira") == 0

    def test_reject_if_no_target(self):
        """A missing destination cannot destroy the source principal."""
        state = self._make_state_with_types({
            "trad_ira": (100_000, "traditional_ira"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id=None,
                max_annual_amount=10_000,
            ),
        ]
        with pytest.raises(ValueError, match="Roth conversions require"):
            execute_roth_conversions(priorities, state)
        assert state.get_balance("trad_ira") == 100_000

    def test_skip_if_source_empty(self):
        """Skipped when source balance is zero."""
        state = self._make_state_with_types({
            "trad_ira": (0, "traditional_ira"),
            "roth_ira": (5_000, "roth_ira"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id="roth_ira",
                max_annual_amount=10_000,
            ),
        ]
        result = execute_roth_conversions(priorities, state)
        assert result == {}
        assert state.roth_conversions_this_year == 0

    def test_mixed_priorities(self):
        """Roth conversions run independently; surplus goes to regular priorities."""
        state = self._make_state_with_types({
            "trad_ira": (100_000, "traditional_ira"),
            "roth_ira": (0, "roth_ira"),
            "brokerage": (0, "brokerage"),
        })
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id="roth_ira",
                max_annual_amount=10_000,
            ),
            PriorityData(
                priority_rank=2,
                target_account_id="brokerage",
            ),
        ]
        # Roth conversion happens independently
        roth_result = execute_roth_conversions(priorities, state)
        assert roth_result["roth_ira"] == 10_000
        # Full 25k surplus goes to non-Roth priorities
        surplus_result = allocate_surplus(25_000, priorities, state)
        assert surplus_result["brokerage"] == 25_000
        assert state.get_balance("trad_ira") == 90_000
        assert state.get_balance("roth_ira") == 10_000
        assert state.get_balance("brokerage") == 25_000
        assert state.roth_conversions_this_year == 10_000


# ---------------------------------------------------------------------------
# Transfer priority
# ---------------------------------------------------------------------------

def _make_transfer_state(accounts: dict[str, float]) -> SimState:
    return SimState(2026, accounts={aid: AccountInfo(balance, "checking") for aid, balance in accounts.items()})


class TestTransferPriority:
    def test_basic_transfer(self):
        """Withdraws from source and deposits to target, independent of surplus."""
        state = _make_transfer_state({"savings": 20_000, "brokerage": 5_000})
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="transfer",
                source_account_id="savings",
                target_account_id="brokerage",
                max_annual_amount=10_000,
            ),
        ]
        result = execute_transfers(priorities, state)
        assert result["brokerage"] == 10_000
        assert state.get_balance("savings") == 10_000
        assert state.get_balance("brokerage") == 15_000

    def test_capped_by_max_annual_amount(self):
        """Transfer respects max_annual_amount cap."""
        state = _make_transfer_state({"a": 100_000, "b": 0})
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="transfer",
                source_account_id="a",
                target_account_id="b",
                max_annual_amount=5_000,
            ),
        ]
        result = execute_transfers(priorities, state)
        assert result["b"] == 5_000
        assert state.get_balance("a") == 95_000

    def test_capped_by_source_balance(self):
        """Transfer cannot exceed source account balance."""
        state = _make_transfer_state({"a": 3_000, "b": 0})
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="transfer",
                source_account_id="a",
                target_account_id="b",
                max_annual_amount=20_000,
            ),
        ]
        result = execute_transfers(priorities, state)
        assert result["b"] == 3_000
        assert state.get_balance("a") == 0
        assert state.get_balance("b") == 3_000

    def test_reject_if_no_source(self):
        """Skipped when source_account_id is None."""
        state = _make_transfer_state({"b": 0})
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="transfer",
                source_account_id=None,
                target_account_id="b",
                max_annual_amount=10_000,
            ),
        ]
        with pytest.raises(ValueError, match="different accounts"):
            execute_transfers(priorities, state)

    def test_reject_if_no_target(self):
        """Skipped when target_account_id is None."""
        state = _make_transfer_state({"a": 10_000})
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="transfer",
                source_account_id="a",
                target_account_id=None,
                max_annual_amount=5_000,
            ),
        ]
        with pytest.raises(ValueError, match="different accounts"):
            execute_transfers(priorities, state)
        assert state.get_balance("a") == 10_000  # unchanged

    def test_reject_if_source_equals_target(self):
        """Skipped when source == target (no-op)."""
        state = _make_transfer_state({"a": 10_000})
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="transfer",
                source_account_id="a",
                target_account_id="a",
                max_annual_amount=5_000,
            ),
        ]
        with pytest.raises(ValueError, match="different accounts"):
            execute_transfers(priorities, state)
        assert state.get_balance("a") == 10_000  # unchanged

    def test_skip_if_source_empty(self):
        """Skipped when source balance is zero."""
        state = _make_transfer_state({"a": 0, "b": 5_000})
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="transfer",
                source_account_id="a",
                target_account_id="b",
                max_annual_amount=10_000,
            ),
        ]
        result = execute_transfers(priorities, state)
        assert result == {}
        assert state.get_balance("b") == 5_000  # unchanged

    def test_transfer_recorded_in_state(self):
        """Transfer is recorded as a TransferFlow in state.transfers."""
        state = _make_transfer_state({"savings": 20_000, "brokerage": 5_000})
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="transfer",
                source_account_id="savings",
                target_account_id="brokerage",
                max_annual_amount=10_000,
            ),
        ]
        execute_transfers(priorities, state)
        assert len(state.transfers) == 1
        tf = state.transfers[0]
        assert tf.source_account_id == "savings"
        assert tf.target_account_id == "brokerage"
        assert tf.amount == 10_000

    def test_mixed_with_regular_and_roth(self):
        """Transfer runs independently; does NOT consume surplus."""
        state = SimState(
            year=2025,
            accounts={
                "trad_ira": AccountInfo(balance=100_000, account_type="traditional_ira"),
                "roth_ira": AccountInfo(balance=0, account_type="roth_ira"),
                "savings": AccountInfo(balance=50_000, account_type="savings"),
                "brokerage": AccountInfo(balance=0, account_type="taxable_brokerage", cost_basis=0),
                "extra": AccountInfo(balance=0, account_type="taxable_brokerage", cost_basis=0),
            },
        )
        priorities = [
            PriorityData(
                priority_rank=1,
                priority_type="roth_conversion",
                source_account_id="trad_ira",
                target_account_id="roth_ira",
                max_annual_amount=10_000,
            ),
            PriorityData(
                priority_rank=2,
                priority_type="transfer",
                source_account_id="savings",
                target_account_id="brokerage",
                max_annual_amount=8_000,
            ),
            PriorityData(
                priority_rank=3,
                target_account_id="extra",
            ),
        ]
        # Roth conversion runs independently
        roth_result = execute_roth_conversions(priorities, state)
        assert roth_result["roth_ira"] == 10_000
        assert state.get_balance("trad_ira") == 90_000
        assert state.roth_conversions_this_year == 10_000
        # Transfer runs independently — does NOT consume surplus
        transfer_result = execute_transfers(priorities, state)
        assert transfer_result["brokerage"] == 8_000
        assert state.get_balance("savings") == 42_000
        # Full 30k surplus available (neither Roth nor transfer consumed it)
        surplus_result = allocate_surplus(30_000, priorities, state)
        assert surplus_result["extra"] == 30_000


# ---------------------------------------------------------------------------
# Early withdrawal penalty
# ---------------------------------------------------------------------------

def _make_state_with_types(
    accounts: dict[str, tuple[float, str]], year: int = 2025
) -> SimState:
    """Build SimState with explicit account types."""
    return SimState(
        year=year,
        accounts={
            aid: AccountInfo(balance=bal, account_type=atype, cost_basis=bal)
            for aid, (bal, atype) in accounts.items()
        },
    )


class TestEarlyWithdrawalPenalty:
    def test_pre59_penalty_applied(self):
        """10% penalty on traditional IRA drawdown before age 59."""
        state = _make_state_with_types({"ira": (100_000, "traditional_ira")})
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(10_000, order, state, age=50)
        # To net 10k, must withdraw 10000/0.9 ≈ 11111.11
        total_withdrawn = sum(result.values())
        assert abs(total_withdrawn - 10_000 / 0.9) < 0.01
        assert abs(penalty - total_withdrawn * 0.10) < 0.01
        assert state.failure_year is None

    def test_post59_no_penalty(self):
        """No penalty on drawdown at age 60."""
        state = _make_state_with_types({"ira": (100_000, "traditional_ira")})
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(10_000, order, state, age=60)
        assert result["ira"] == 10_000
        assert penalty == 0.0

    def test_sepp_account_skipped_and_next_account_used(self):
        """An account with an active 72(t) series is left untouched by the
        drawdown order; the deficit moves to the next account."""
        state = _make_state_with_types({"ira": (100_000, "traditional_ira"), "brok": (50_000, "taxable_brokerage")})
        order = [DrawdownEntryData(rank=1, source_account_id="ira"), DrawdownEntryData(rank=2, source_account_id="brok")]
        result, penalty = execute_drawdown(
            10_000, order, state, age=50, sepp_account_ids={"ira"},
        )
        assert "ira" not in result
        assert result["brok"] == 10_000
        assert state.get_balance("ira") == 100_000
        assert penalty == 0.0

    def test_default_age_no_penalty(self):
        """Default age=100 produces no penalty (backward compat)."""
        state = _make_state_with_types({"ira": (100_000, "traditional_ira")})
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(10_000, order, state)
        assert result["ira"] == 10_000
        assert penalty == 0.0

    def test_brokerage_no_penalty_pre59(self):
        """Taxable brokerage is never subject to early withdrawal penalty."""
        state = _make_state_with_types({"brok": (100_000, "taxable_brokerage")})
        order = [DrawdownEntryData(rank=1, source_account_id="brok")]
        result, penalty = execute_drawdown(10_000, order, state, age=30)
        assert result["brok"] == 10_000
        assert penalty == 0.0

    def test_roth_401k_penalized_pre59(self):
        """Roth 401k is also subject to early withdrawal penalty."""
        state = _make_state_with_types({"r401k": (100_000, "roth_401k")})
        order = [DrawdownEntryData(rank=1, source_account_id="r401k")]
        result, penalty = execute_drawdown(10_000, order, state, age=50)
        assert penalty > 0
        assert abs(sum(result.values()) - 10_000 / 0.9) < 0.01

    def test_mixed_accounts_only_retirement_penalized(self):
        """Only retirement accounts get penalized; brokerage drawn first is free."""
        state = _make_state_with_types({
            "brok": (5_000, "taxable_brokerage"),
            "ira": (100_000, "traditional_ira"),
        })
        order = [
            DrawdownEntryData(rank=1, source_account_id="brok"),
            DrawdownEntryData(rank=2, source_account_id="ira"),
        ]
        result, penalty = execute_drawdown(8_000, order, state, age=50)
        # 5k from brokerage (no penalty), remaining 3k from IRA (penalized)
        assert result["brok"] == 5_000
        ira_withdrawn = result["ira"]
        # To net 3k from penalized IRA: 3000/0.9 ≈ 3333.33
        assert abs(ira_withdrawn - 3_000 / 0.9) < 0.01
        # Penalty is only on IRA withdrawal
        assert abs(penalty - ira_withdrawn * 0.10) < 0.01


# ---------------------------------------------------------------------------
# Roth IRA modified-AGI phaseouts
# ---------------------------------------------------------------------------


class TestRothIRAIncomePhaseout:
    @staticmethod
    def _state() -> SimState:
        return SimState(
            year=2026,
            accounts={
                "roth": AccountInfo(balance=0, account_type="roth_ira"),
                "taxable": AccountInfo(
                    balance=0,
                    account_type="taxable_brokerage",
                    cost_basis=0,
                ),
            },
        )

    @staticmethod
    def _priorities() -> list[PriorityData]:
        return [
            PriorityData(priority_rank=1, target_account_id="roth"),
            PriorityData(priority_rank=2, target_account_id="taxable"),
        ]

    def test_joint_filer_below_phaseout_gets_full_limit(self):
        state = self._state()
        result = allocate_surplus(
            20_000,
            self._priorities(),
            state,
            age=40,
            filing_status="married_filing_jointly",
            modified_agi=241_999,
        )
        assert result["roth"] == 7_500
        assert result["taxable"] == 12_500

    def test_joint_filer_mid_phaseout_gets_reduced_limit(self):
        state = self._state()
        result = allocate_surplus(
            20_000,
            self._priorities(),
            state,
            age=40,
            filing_status="married_filing_jointly",
            modified_agi=247_000,
        )
        assert result["roth"] == 3_750
        assert result["taxable"] == 16_250

    def test_joint_filer_above_phaseout_gets_no_roth_contribution(self):
        state = self._state()
        result = allocate_surplus(
            20_000,
            self._priorities(),
            state,
            age=40,
            filing_status="married_filing_jointly",
            modified_agi=285_000,
        )
        assert "roth" not in result
        assert result["taxable"] == 20_000
        assert state.get_balance("roth") == 0

    def test_phaseout_thresholds_scale_with_simulation_inflation(self):
        # IRC 408A(c)(3): the $242,000 start doubles to $484,000; the $10,000
        # range width is not indexed, so $489,000 is the midpoint.
        state = self._state()
        state.coverage_inflation_factor = 2.0
        result = allocate_surplus(
            30_000,
            self._priorities(),
            state,
            age=40,
            filing_status="married_filing_jointly",
            modified_agi=489_000,
        )
        assert result["roth"] == 7_500
        assert result["taxable"] == 22_500


# ---------------------------------------------------------------------------
# Inflation-indexed IRS contribution limits
# ---------------------------------------------------------------------------


class TestInflationIndexedLimits:
    def test_inflation_factor_doubles_401k_limit(self):
        """With coverage_inflation_factor=2.0, 401k limit scales to 2 x 24,500 = 49,000."""
        state = SimState(
            year=2026,
            coverage_inflation_factor=2.0,
            accounts={
                "k401": AccountInfo(balance=0, account_type="traditional_401k"),
            },
        )
        priorities = [
            PriorityData(priority_rank=1, target_account_id="k401"),
        ]
        result = allocate_surplus(100_000, priorities, state, age=40)
        assert result["k401"] == 49_000
        assert state.get_balance("k401") == 49_000

    def test_inflation_factor_1_preserves_nominal_limit(self):
        """Default coverage_inflation_factor=1.0 keeps the 2026 nominal 401k limit."""
        state = SimState(
            year=2026,
            accounts={
                "k401": AccountInfo(balance=0, account_type="traditional_401k"),
            },
        )
        priorities = [
            PriorityData(priority_rank=1, target_account_id="k401"),
        ]
        result = allocate_surplus(100_000, priorities, state, age=40)
        assert result["k401"] == 24_500
        assert state.get_balance("k401") == 24_500

    def test_inflation_factor_scales_ira_limit(self):
        """IRA limit also scales with inflation_factor."""
        state = SimState(
            year=2026,
            coverage_inflation_factor=1.5,
            accounts={
                "ira": AccountInfo(balance=0, account_type="roth_ira"),
            },
        )
        priorities = [
            PriorityData(priority_rank=1, target_account_id="ira"),
        ]
        result = allocate_surplus(100_000, priorities, state, age=40)
        assert result["ira"] == 7_500 * 1.5  # 11,250
        assert state.get_balance("ira") == 11_250

    def test_inflation_factor_scales_catchup(self):
        """Catch-up contributions are also inflation-indexed."""
        state = SimState(
            year=2026,
            coverage_inflation_factor=2.0,
            accounts={
                "k401": AccountInfo(balance=0, account_type="traditional_401k"),
            },
        )
        priorities = [
            PriorityData(priority_rank=1, target_account_id="k401"),
        ]
        # age 55 triggers the 50+ catch-up: (24,500 + 8,000) * 2.0 = 65,000
        result = allocate_surplus(100_000, priorities, state, age=55)
        assert result["k401"] == 65_000

    def test_inflation_factor_scales_hsa(self):
        """HSA base limit indexes; the statutory $1,000 catch-up stays fixed."""
        state = SimState(
            year=2026,
            coverage_inflation_factor=3.0,
            accounts={
                "hsa": AccountInfo(balance=0, account_type="hsa"),
            },
        )
        priorities = [
            PriorityData(priority_rank=1, target_account_id="hsa"),
        ]
        # age 56: indexed base 4,400 * 3.0 + fixed catch-up 1,000 = 14,200
        result = allocate_surplus(100_000, priorities, state, age=56)
        assert result["hsa"] == 14_200



class TestBracketFillConversions:
    """fill_bracket Roth conversions convert only ordinary-income headroom."""

    def _state(self):
        return _make_state_with_types({"ira": (500_000, "traditional_ira"), "roth": (10_000, "roth_ira")})

    def _rule(self, **kw):
        base = dict(priority_rank=1, priority_type="roth_conversion", source_account_id="ira",
                    target_account_id="roth", conversion_mode="fill_bracket", bracket_ceiling_rate=0.22)
        base.update(kw)
        return PriorityData(**base)

    def test_converts_headroom_below_bracket_top(self):
        ctx = ConversionTaxContext(ordinary_taxable_income=60_000, modified_agi=75_000,
                                   brackets=[(24_800, 0.10), (100_800, 0.12), (211_400, 0.22), (403_550, 0.24)])
        state = self._state()
        result = execute_roth_conversions([self._rule()], state, tax_context=ctx)
        assert result["roth"] == pytest.approx(211_400 - 60_000)
        assert state.roth_conversions_this_year == pytest.approx(151_400)
        assert state.get_balance("ira") == pytest.approx(500_000 - 151_400)

    def test_magi_cap_and_balance_and_annual_cap_bind(self):
        ctx = ConversionTaxContext(ordinary_taxable_income=60_000, modified_agi=75_000,
                                   brackets=[(100_800, 0.12), (211_400, 0.22)], inflation_factor=1.0)
        state = self._state()
        result = execute_roth_conversions([self._rule(magi_cap=100_000)], state, tax_context=ctx)
        assert result["roth"] == pytest.approx(25_000)  # MAGI room 100k - 75k
        state = self._state()
        result = execute_roth_conversions([self._rule(max_annual_amount=20_000)], state, tax_context=ctx)
        assert result["roth"] == pytest.approx(20_000)
        state = _make_state_with_types({"ira": (5_000, "traditional_ira"), "roth": (0, "roth_ira")})
        result = execute_roth_conversions([self._rule()], state, tax_context=ctx)
        assert result["roth"] == pytest.approx(5_000)

    def test_no_headroom_flat_tax_or_missing_context_converts_nothing(self):
        full = ConversionTaxContext(ordinary_taxable_income=250_000, modified_agi=250_000, brackets=[(211_400, 0.22)])
        assert execute_roth_conversions([self._rule()], self._state(), tax_context=full) == {}
        flat = ConversionTaxContext(ordinary_taxable_income=0, modified_agi=0, brackets=[(211_400, 0.22)], flat_tax=True)
        assert execute_roth_conversions([self._rule()], self._state(), tax_context=flat) == {}
        assert execute_roth_conversions([self._rule()], self._state()) == {}

    def test_milestone_window_and_shared_headroom(self):
        ctx = ConversionTaxContext(ordinary_taxable_income=0, modified_agi=0, brackets=[(100_800, 0.12), (211_400, 0.22)])
        rules = [self._rule(start_milestone_id="retire"), self._rule(priority_rank=2, bracket_ceiling_rate=0.22)]
        state = self._state()
        result = execute_roth_conversions(rules, state, tax_context=ctx, triggered_milestones=set())
        assert result["roth"] == pytest.approx(211_400)  # only the unbounded rule fired
        state = self._state()
        result = execute_roth_conversions(rules, state, tax_context=ctx, triggered_milestones={"retire"})
        assert result["roth"] == pytest.approx(211_400)  # headroom is shared, not doubled



class TestGainHarvesting:
    """gain_harvest realises taxable gains up to a capital-gains bracket ceiling."""

    def _ctx(self, ordinary=20_000, gains_so_far=0.0, flat=False):
        return ConversionTaxContext(
            ordinary_taxable_income=ordinary, modified_agi=ordinary + gains_so_far,
            brackets=[(100_800, 0.12), (211_400, 0.22)],
            ltcg_brackets=[(49_450, 0.0), (545_500, 0.15), (999_999_999, 0.20)],
            capital_gains_so_far=gains_so_far, flat_tax=flat,
        )

    def _rule(self, **kw):
        base = dict(priority_rank=1, priority_type="gain_harvest", source_account_id="brok",
                    conversion_mode="fill_bracket", bracket_ceiling_rate=0.0)
        base.update(kw)
        return PriorityData(**base)

    def _state(self, balance=300_000, basis=100_000):
        state = _make_state_with_types({"brok": (balance, "taxable_brokerage"), "cash": (10_000, "checking")})
        state.accounts["brok"].cost_basis = basis
        return state

    def test_harvests_room_below_zero_percent_bracket_and_steps_up_basis(self):
        state = self._state()
        result = execute_gain_harvests([self._rule()], state, tax_context=self._ctx())
        assert result["brok"] == pytest.approx(49_450 - 20_000)
        assert state.get_balance("brok") == pytest.approx(300_000)  # sell and rebuy: no cash movement
        assert state.accounts["brok"].cost_basis == pytest.approx(100_000 + 29_450)
        assert state.capital_gains_this_year == pytest.approx(29_450)
        assert state.harvested_gains_this_year == pytest.approx(29_450)

    def test_room_is_reduced_by_conversions_and_existing_gains_and_capped(self):
        state = self._state()
        state.roth_conversions_this_year = 10_000
        result = execute_gain_harvests([self._rule()], state, tax_context=self._ctx(gains_so_far=5_000))
        assert result["brok"] == pytest.approx(49_450 - 20_000 - 10_000 - 5_000)
        state = self._state(balance=120_000, basis=100_000)
        result = execute_gain_harvests([self._rule()], state, tax_context=self._ctx())
        assert result["brok"] == pytest.approx(20_000)  # limited by unrealised gain
        state = self._state()
        result = execute_gain_harvests([self._rule(max_annual_amount=5_000)], state, tax_context=self._ctx())
        assert result["brok"] == pytest.approx(5_000)
        state = self._state()
        result = execute_gain_harvests([self._rule(magi_cap=30_000)], state, tax_context=self._ctx())
        assert result["brok"] == pytest.approx(10_000)  # MAGI room 30k - 20k

    def test_ineligible_accounts_missing_basis_and_flat_tax_do_nothing(self):
        state = self._state()
        state.accounts["brok"].cost_basis = None
        assert execute_gain_harvests([self._rule()], state, tax_context=self._ctx()) == {}
        state = _make_state_with_types({"ira": (300_000, "traditional_ira")})
        assert execute_gain_harvests([self._rule(source_account_id="ira")], state, tax_context=self._ctx()) == {}
        assert execute_gain_harvests([self._rule()], self._state(), tax_context=self._ctx(flat=True)) == {}
        assert execute_gain_harvests([self._rule()], self._state(), tax_context=None) == {}

    def test_fifteen_percent_ceiling_and_milestone_window(self):
        state = self._state(balance=1_000_000, basis=100_000)
        result = execute_gain_harvests([self._rule(bracket_ceiling_rate=0.15)], state, tax_context=self._ctx())
        assert result["brok"] == pytest.approx(545_500 - 20_000)
        state = self._state()
        rule = self._rule(start_milestone_id="retire")
        assert execute_gain_harvests([rule], state, tax_context=self._ctx(), triggered_milestones=set()) == {}
        assert execute_gain_harvests([rule], state, tax_context=self._ctx(), triggered_milestones={"retire"})["brok"] > 0
