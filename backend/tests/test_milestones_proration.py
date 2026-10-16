"""Tests for 22.2.1: birth_month + milestone trigger-month proration.

Covers `resolve_trigger_month` and the trigger-year semantics of
`prorate_for_year` when `start_month`/`end_month` are NULL.
"""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine.milestones import prorate_for_year, resolve_trigger_month
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)


def _retire_at_45() -> MilestoneData:
    return MilestoneData(
        id="ms_retire",
        name="Retire",
        trigger_type="age",
        trigger_value=45,
    )


# ---------------------------------------------------------------------------
# resolve_trigger_month
# ---------------------------------------------------------------------------


class TestResolveTriggerMonth:
    def test_age_trigger_returns_birth_month(self):
        assert resolve_trigger_month(_retire_at_45(), birth_month=6, year=2039) == 6

    def test_age_trigger_null_birth_month_returns_january(self):
        assert resolve_trigger_month(_retire_at_45(), birth_month=None, year=2039) == 1

    def test_date_trigger_uses_trigger_date_month(self):
        ms = MilestoneData(
            id="ms_date", name="Move", trigger_type="date", trigger_date="2030-08-15"
        )
        assert resolve_trigger_month(ms, birth_month=None, year=2030) == 8

    def test_net_worth_trigger_returns_january(self):
        ms = MilestoneData(
            id="ms_nw", name="Target", trigger_type="net_worth", trigger_value=1_000_000
        )
        assert resolve_trigger_month(ms, birth_month=6, year=2030) == 1

    def test_none_milestone_returns_january(self):
        assert resolve_trigger_month(None, birth_month=6, year=2030) == 1


# ---------------------------------------------------------------------------
# prorate_for_year — age-triggered end with no explicit end_month
# ---------------------------------------------------------------------------


class TestAgeTriggerEndProration:
    def test_birth_month_june_gives_5_12(self):
        """birth_month=6 → retire-at-45 fires in June → salary ends May → 5/12."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_retire_at_45(),
            start_month=None,
            end_month=None,
            triggered={"ms_retire"},
            newly_triggered=["ms_retire"],
            year=2039,
            birth_month=6,
        )
        assert fraction == pytest.approx(5 / 12)

    def test_birth_month_null_gives_zero(self):
        """birth_month=None → treated as Jan → em=0 → fraction 0."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_retire_at_45(),
            start_month=None,
            end_month=None,
            triggered={"ms_retire"},
            newly_triggered=["ms_retire"],
            year=2039,
            birth_month=None,
        )
        assert fraction == 0.0

    def test_explicit_end_month_unaffected_by_birth_month(self):
        """Explicit end_month=12 wins regardless of birth_month."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_retire_at_45(),
            start_month=None,
            end_month=12,
            triggered={"ms_retire"},
            newly_triggered=["ms_retire"],
            year=2039,
            birth_month=6,
        )
        assert fraction == pytest.approx(1.0)

    def test_birth_month_january_gives_zero(self):
        """birth_month=1 → em=0 → fraction 0.0."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_retire_at_45(),
            start_month=None,
            end_month=None,
            triggered={"ms_retire"},
            newly_triggered=["ms_retire"],
            year=2039,
            birth_month=1,
        )
        assert fraction == 0.0

    def test_birth_month_december_gives_11_12(self):
        """birth_month=12 → em=11 → fraction 11/12."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_retire_at_45(),
            start_month=None,
            end_month=None,
            triggered={"ms_retire"},
            newly_triggered=["ms_retire"],
            year=2039,
            birth_month=12,
        )
        assert fraction == pytest.approx(11 / 12)


# ---------------------------------------------------------------------------
# prorate_for_year — age-triggered start with no explicit start_month
# ---------------------------------------------------------------------------


class TestAgeTriggerStartProration:
    def test_birth_month_sept_gives_4_12(self):
        """Start at age 65, birth_month=9 → sm=9 → (12-9+1)/12 = 4/12."""
        ms = MilestoneData(
            id="ms_ss", name="SS start", trigger_type="age", trigger_value=65
        )
        fraction = prorate_for_year(
            start_ms=ms,
            end_ms=None,
            start_month=None,
            end_month=None,
            triggered={"ms_ss"},
            newly_triggered=["ms_ss"],
            year=2055,
            birth_month=9,
        )
        assert fraction == pytest.approx(4 / 12)

    def test_date_trigger_uses_trigger_date_month(self):
        """Date milestone 2030-08-15 → sm=8 → (12-8+1)/12 = 5/12."""
        ms = MilestoneData(
            id="ms_date", name="Move", trigger_type="date", trigger_date="2030-08-15"
        )
        fraction = prorate_for_year(
            start_ms=ms,
            end_ms=None,
            start_month=None,
            end_month=None,
            triggered={"ms_date"},
            newly_triggered=["ms_date"],
            year=2030,
            birth_month=None,
        )
        assert fraction == pytest.approx(5 / 12)


# ---------------------------------------------------------------------------
# Full-simulator integration
# ---------------------------------------------------------------------------


def _build_retire_plan(birth_month: int | None) -> PlanData:
    """Plan with a $120k salary ending on retire-at-45; no explicit end_month."""
    salary = 120_000.0
    retire = _retire_at_45()
    return PlanData(
        plan_id=str(uuid.uuid4()),
        birth_year=1994,
        birth_month=birth_month,
        filing_status="single",
        life_expectancy=47,  # bounds end_year to 2041 for a focused test
        start_year=2026,
        milestones=[retire],
        income_streams=[
            IncomeData(
                id="inc_salary",
                name="Salary",
                annual_amount=salary,
                start_milestone_id=None,
                end_milestone_id="ms_retire",
                growth_rate=0.0,
                withholding_percent=0.0,
                start_month=None,
                end_month=None,
                is_earned_income=True,
            )
        ],
        expenses=[],
        priorities=[PriorityData(priority_rank=1, target_account_id="acct_cash")],
        drawdown_order=[],
        assumptions=AssumptionData(
            inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0
        ),
        accounts={
            "acct_cash": AccountInfo(balance=10_000.0, account_type="checking"),
        },
    )


def _salary_by_year(plan: PlanData) -> dict[int, float]:
    result = run_simulation(plan)
    return {snap.year: snap.gross_income for snap in result.yearly_snapshots}


class TestRetireAt45Integration:
    def test_birth_month_june_ends_in_may_of_trigger_year(self):
        """birth_year=1994, birth_month=6, retire-at-45 → trigger year 2039.
        2038 = full salary, 2039 ≈ 5/12, 2040 = 0."""
        salary_by_year = _salary_by_year(_build_retire_plan(6))
        assert salary_by_year[2038] == pytest.approx(120_000.0)
        assert salary_by_year[2039] == pytest.approx(120_000.0 * 5 / 12)
        assert salary_by_year[2040] == pytest.approx(0.0)

    def test_null_birth_month_ends_in_december_of_prior_year(self):
        """birth_month=None → trigger month = 1 → em=0 → 2039 salary = 0."""
        salary_by_year = _salary_by_year(_build_retire_plan(None))
        assert salary_by_year[2038] == pytest.approx(120_000.0)
        assert salary_by_year[2039] == pytest.approx(0.0)
        assert salary_by_year[2040] == pytest.approx(0.0)

    def test_explicit_end_month_december_preserves_full_trigger_year(self):
        """Explicit end_month=12 overrides resolved trigger month → 2039 full."""
        plan = _build_retire_plan(6)
        plan.income_streams[0].end_month = 12
        salary_by_year = _salary_by_year(plan)
        assert salary_by_year[2038] == pytest.approx(120_000.0)
        assert salary_by_year[2039] == pytest.approx(120_000.0)
        assert salary_by_year[2040] == pytest.approx(0.0)
