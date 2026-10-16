"""Tests for IRS 59.5 early-withdrawal penalty with birth_month."""

from __future__ import annotations

import pytest

from coastmath.engine.types import AccountInfo, DrawdownEntryData, SimState
from coastmath.engine.waterfall import (
    execute_drawdown,
    is_subject_to_early_withdrawal_penalty,
)


def _make_state(balance: float = 100_000.0, year: int = 2040) -> SimState:
    return SimState(
        year=year,
        accounts={
            "ira": AccountInfo(
                balance=balance, account_type="traditional_ira", cost_basis=balance
            )
        },
    )


class TestIsSubjectToEarlyWithdrawalPenalty:
    @pytest.mark.parametrize("birth_month", [None, 1, 6, 7, 12])
    def test_under_59_always_penalized(self, birth_month: int | None):
        assert is_subject_to_early_withdrawal_penalty(58, birth_month) is True
        assert is_subject_to_early_withdrawal_penalty(30, birth_month) is True

    def test_age_59_birth_month_january_no_penalty(self):
        # Born in January — hits 59.5 in July: half the year, not most of it, is early.
        assert is_subject_to_early_withdrawal_penalty(59, 1) is False

    def test_age_59_birth_month_june_mostly_penalized(self):
        # Born in June — hits 59.5 in December: eleven of twelve months are early.
        assert is_subject_to_early_withdrawal_penalty(59, 6) is True

    def test_age_59_birth_month_july_penalty(self):
        # Born in July — doesn't hit 59.5 until age-60 year.
        assert is_subject_to_early_withdrawal_penalty(59, 7) is True

    def test_age_59_birth_month_december_penalty(self):
        assert is_subject_to_early_withdrawal_penalty(59, 12) is True

    def test_age_59_birth_month_none_conservative_penalty(self):
        # Conservative default when birth_month is unknown: apply penalty.
        assert is_subject_to_early_withdrawal_penalty(59, None) is True

    @pytest.mark.parametrize("birth_month", [None, 1, 6, 7, 12])
    def test_age_60_plus_never_penalized(self, birth_month: int | None):
        assert is_subject_to_early_withdrawal_penalty(60, birth_month) is False
        assert is_subject_to_early_withdrawal_penalty(75, birth_month) is False


class TestExecuteDrawdownWithBirthMonth:
    def test_age_59_january_birth_penalizes_the_first_half(self):
        # 59.5 arrives in July: January-June withdrawals carry the 10%.
        state = _make_state()
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(
            10_000, order, state, age=59, birth_month=1
        )
        assert result["ira"] == pytest.approx(10_000 / 0.95)
        assert penalty == pytest.approx(result["ira"] * 0.05)

    def test_age_60_december_birth_penalizes_january_to_may(self):
        # Born in December: 59.5 arrives in June of the year the owner turns 60.
        state = _make_state()
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(
            10_000, order, state, age=60, birth_month=12
        )
        rate = 0.10 * 5 / 12
        assert result["ira"] == pytest.approx(10_000 / (1 - rate))
        assert penalty == pytest.approx(result["ira"] * rate)

    def test_age_59_h2_birth_penalty(self):
        state = _make_state()
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(
            10_000, order, state, age=59, birth_month=12
        )
        total_withdrawn = sum(result.values())
        # To net 10k with a 10% penalty: withdraw 10000/0.9
        assert abs(total_withdrawn - 10_000 / 0.9) < 0.01
        assert abs(penalty - total_withdrawn * 0.10) < 0.01

    def test_age_59_birth_month_none_conservative_penalty(self):
        state = _make_state()
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(
            10_000, order, state, age=59, birth_month=None
        )
        total_withdrawn = sum(result.values())
        assert abs(total_withdrawn - 10_000 / 0.9) < 0.01
        assert penalty > 0

    @pytest.mark.parametrize("birth_month", [None, 1, 6, 7, 12])
    def test_age_58_always_penalized(self, birth_month: int | None):
        state = _make_state()
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        _, penalty = execute_drawdown(
            10_000, order, state, age=58, birth_month=birth_month
        )
        assert penalty > 0

    @pytest.mark.parametrize("birth_month", [None, 1, 6, 7])
    def test_age_60_after_59_and_a_half_is_never_penalized(self, birth_month: int | None):
        state = _make_state()
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(
            10_000, order, state, age=60, birth_month=birth_month
        )
        assert result["ira"] == 10_000
        assert penalty == 0.0

    def test_active_sepp_account_is_skipped_by_ordinary_drawdown(self):
        # Extra withdrawals from an account with an active 72(t) series would
        # modify the series (IRC 72(t)(4)), so the drawdown order skips it
        # instead of treating it as penalty-exempt.
        state = _make_state()
        order = [DrawdownEntryData(rank=1, source_account_id="ira")]
        result, penalty = execute_drawdown(
            10_000, order, state,
            age=58, birth_month=12, sepp_account_ids={"ira"},
        )
        assert "ira" not in result
        assert penalty == 0.0
        assert state.unfunded_expenses == 10_000
