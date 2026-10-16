"""Tests for 22.1.2: per-year state resolution via residency_periods.

Unit tests cover `resolve_state_for_year`; integration tests verify the
simulator applies CA vs NV state tax in the right years.
"""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine.residency import resolve_state_for_year
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
    ResidencyPeriodData,
)


def _base_plan(**overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1994,
        birth_month=1,
        filing_status="single",
        life_expectancy=40,
        start_year=2026,
        milestones=[],
        income_streams=[],
        expenses=[],
        priorities=[],
        drawdown_order=[],
        assumptions=AssumptionData(
            inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0
        ),
        accounts={},
        state_code="CA",
        residency_periods=[],
    )
    defaults.update(overrides)
    return PlanData(**defaults)


# ---------------------------------------------------------------------------
# resolve_state_for_year — unit tests
# ---------------------------------------------------------------------------


class TestResolveStateForYear:
    def test_no_periods_falls_back_to_plan_state_code(self):
        plan = _base_plan(state_code="CA", residency_periods=[])
        for year in (2026, 2030, 2050):
            assert resolve_state_for_year(year, set(), plan) == "CA"

    def test_no_periods_and_null_state_code_returns_none(self):
        plan = _base_plan(state_code=None, residency_periods=[])
        assert resolve_state_for_year(2030, set(), plan) is None

    def test_year_based_switch_ca_to_nv(self):
        """CA period ends 2028; NV period starts 2029."""
        plan = _base_plan(
            state_code="CA",
            residency_periods=[
                ResidencyPeriodData(state_code="CA", end_year=2028, rank=0),
                ResidencyPeriodData(state_code="NV", start_year=2029, rank=1),
            ],
        )
        assert resolve_state_for_year(2026, set(), plan) == "CA"
        assert resolve_state_for_year(2027, set(), plan) == "CA"
        assert resolve_state_for_year(2028, set(), plan) == "CA"
        assert resolve_state_for_year(2029, set(), plan) == "NV"
        assert resolve_state_for_year(2035, set(), plan) == "NV"

    def test_rank_tiebreaker_lower_wins(self):
        """Two periods both match a given year; lower rank wins."""
        plan = _base_plan(
            state_code="FL",
            residency_periods=[
                ResidencyPeriodData(state_code="NV", rank=5),
                ResidencyPeriodData(state_code="CA", rank=1),
                ResidencyPeriodData(state_code="TX", rank=10),
            ],
        )
        assert resolve_state_for_year(2030, set(), plan) == "CA"

    def test_milestone_triggered_switch(self):
        """CA ends when milestone triggers; NV starts when same milestone triggers."""
        plan = _base_plan(
            state_code="CA",
            residency_periods=[
                ResidencyPeriodData(
                    state_code="CA", end_milestone_id="ms_move", rank=0,
                ),
                ResidencyPeriodData(
                    state_code="NV", start_milestone_id="ms_move", rank=1,
                ),
            ],
        )
        # Before milestone triggers
        assert resolve_state_for_year(2030, set(), plan) == "CA"
        # After milestone triggers
        assert resolve_state_for_year(2030, {"ms_move"}, plan) == "NV"

    def test_period_with_no_bounds_matches_all_years(self):
        plan = _base_plan(
            state_code="FL",
            residency_periods=[ResidencyPeriodData(state_code="WA")],
        )
        assert resolve_state_for_year(2026, set(), plan) == "WA"
        assert resolve_state_for_year(2099, set(), plan) == "WA"

    def test_no_matching_period_falls_back_to_plan_state_code(self):
        """Residency period exists but its window hasn't started yet."""
        plan = _base_plan(
            state_code="CA",
            residency_periods=[
                ResidencyPeriodData(state_code="NV", start_year=2040),
            ],
        )
        assert resolve_state_for_year(2030, set(), plan) == "CA"
        assert resolve_state_for_year(2040, set(), plan) == "NV"


# ---------------------------------------------------------------------------
# Full-simulator integration
# ---------------------------------------------------------------------------


def _build_income_plan(
    state_code: str | None,
    residency_periods: list[ResidencyPeriodData],
    milestones: list[MilestoneData] | None = None,
) -> PlanData:
    """Plan with $200k salary 2026-2035, so CA income tax is meaningfully non-zero."""
    return PlanData(
        plan_id=str(uuid.uuid4()),
        birth_year=1994,
        birth_month=1,
        filing_status="single",
        life_expectancy=42,  # covers 2026-2035
        start_year=2026,
        milestones=milestones or [],
        income_streams=[
            IncomeData(
                id="inc_salary",
                name="Salary",
                annual_amount=200_000.0,
                growth_rate=0.0,
                withholding_percent=0.0,
                is_earned_income=True,
            )
        ],
        expenses=[],
        priorities=[PriorityData(priority_rank=1, target_account_id="acct_cash")],
        drawdown_order=[],
        assumptions=AssumptionData(
            inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0
        ),
        accounts={"acct_cash": AccountInfo(balance=10_000.0, account_type="checking")},
        state_code=state_code,
        residency_periods=residency_periods,
    )


def _state_tax_by_year(plan: PlanData) -> dict[int, float]:
    result = run_simulation(plan)
    return {snap.year: snap.state_tax for snap in result.yearly_snapshots}


class TestResidencySimulatorIntegration:
    def test_no_periods_uses_plan_state_code_every_year(self):
        """Fallback path: CA state tax applied every year when no residency_periods."""
        plan = _build_income_plan(state_code="CA", residency_periods=[])
        tax = _state_tax_by_year(plan)
        for year in range(2026, 2036):
            assert tax[year] > 0, f"CA state tax should be > 0 in {year}, got {tax[year]}"

    def test_year_based_switch_ca_to_nv(self):
        """CA 2026-2028, NV 2029-2035 → CA years have state tax, NV years do not."""
        plan = _build_income_plan(
            state_code="CA",
            residency_periods=[
                ResidencyPeriodData(state_code="CA", end_year=2028, rank=0),
                ResidencyPeriodData(state_code="NV", start_year=2029, rank=1),
            ],
        )
        tax = _state_tax_by_year(plan)
        for year in (2026, 2027, 2028):
            assert tax[year] > 0, f"CA year {year} should have state tax, got {tax[year]}"
        for year in (2029, 2030, 2031, 2035):
            assert tax[year] == pytest.approx(0.0), (
                f"NV year {year} should have 0 state tax, got {tax[year]}"
            )

    def test_milestone_triggered_switch_at_age_35(self):
        """CA pre-35, NV post-35. age-35 milestone fires in 2029 (birth_year=1994).
        2026-2028 taxed as CA (>0); 2029+ taxed as NV (0)."""
        move_ms = MilestoneData(
            id="ms_move",
            name="Move to NV",
            trigger_type="age",
            trigger_value=35,
        )
        plan = _build_income_plan(
            state_code="CA",
            residency_periods=[
                ResidencyPeriodData(
                    state_code="CA", end_milestone_id="ms_move", rank=0,
                ),
                ResidencyPeriodData(
                    state_code="NV", start_milestone_id="ms_move", rank=1,
                ),
            ],
            milestones=[move_ms],
        )
        tax = _state_tax_by_year(plan)
        for year in (2026, 2027, 2028):
            assert tax[year] > 0, f"Pre-move year {year} should have CA state tax, got {tax[year]}"
        for year in (2029, 2030, 2031, 2035):
            assert tax[year] == pytest.approx(0.0), (
                f"Post-move year {year} should have 0 NV state tax, got {tax[year]}"
            )
