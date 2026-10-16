"""Tests for the historical stress-test API endpoint.

Tests the endpoint integration path: validation + engine call + schema output.
Uses direct engine calls (no TestClient/DB) to match the existing test pattern.
"""

import uuid

import pytest

from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)
from coastmath.schemas.simulation import HistoricalStressResult


def _plan(**overrides) -> PlanData:
    """Minimal plan with sensible defaults."""
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1995,
        filing_status="single",
        life_expectancy=35,  # end = 2030, 5-year sim from 2025
        start_year=2025,
        milestones=[
            MilestoneData(id="plan_start", name="Plan Start", trigger_type="plan_start"),
        ],
        income_streams=[
            IncomeData(
                id="salary",
                name="Salary",
                annual_amount=80_000,
                start_milestone_id="plan_start",
                growth_rate=0.02,
            ),
        ],
        expenses=[],
        priorities=[
            PriorityData(
                priority_rank=1,
                target_account_id="brokerage",
                max_annual_amount=None,
            ),
        ],
        drawdown_order=[],
        assumptions=AssumptionData(
            inflation_rate=0.03,
            stock_growth_rate=0.07,
        ),
        accounts={
            "checking": AccountInfo(balance=10_000, account_type="checking"),
            "brokerage": AccountInfo(balance=100_000, account_type="taxable_brokerage"),
        },
    )
    defaults.update(overrides)
    return PlanData(**defaults)


class TestHistoricalStressEndpointIntegration:
    """Test the engine integration path that the API endpoint uses."""

    def test_valid_start_year_returns_stress_result(self):
        """POST with ?historical_start_year=1966 returns a valid HistoricalStressResult."""
        plan = _plan()
        raw = run_historical_stress_test(plan, start_year=1966)

        # Validate it constructs into the API response schema
        result = HistoricalStressResult(
            simulation_result=raw["simulation_result"],
            metadata=raw["metadata"],
        )

        assert result.metadata.historical_start_year == 1966
        assert len(result.metadata.years_used) > 0
        assert isinstance(result.metadata.wrapped, bool)
        assert len(result.simulation_result.yearly_snapshots) > 0
        assert result.simulation_result.metadata.success is not None

    def test_boundary_start_year_1928(self):
        """Earliest valid year (1928) should work."""
        plan = _plan()
        raw = run_historical_stress_test(plan, start_year=1928)
        result = HistoricalStressResult(
            simulation_result=raw["simulation_result"],
            metadata=raw["metadata"],
        )
        assert result.metadata.historical_start_year == 1928
        assert result.metadata.years_used[0] == 1928

    def test_boundary_start_year_2024(self):
        """Latest valid year (2024) should work (will wrap around)."""
        plan = _plan()
        raw = run_historical_stress_test(plan, start_year=2024)
        result = HistoricalStressResult(
            simulation_result=raw["simulation_result"],
            metadata=raw["metadata"],
        )
        assert result.metadata.historical_start_year == 2024
        assert result.metadata.wrapped is True

    def test_invalid_year_too_low_raises(self):
        """Year 1800 is outside historical data range — should raise ValueError."""
        plan = _plan()
        with pytest.raises(ValueError, match="outside available"):
            run_historical_stress_test(plan, start_year=1800)

    def test_invalid_year_too_high_raises(self):
        """Year 2100 is outside historical data range — should raise ValueError."""
        plan = _plan()
        with pytest.raises(ValueError, match="outside available"):
            run_historical_stress_test(plan, start_year=2100)


class TestHistoricalStressResultSchema:
    """Verify the Pydantic schema serializes correctly."""

    def test_schema_roundtrip(self):
        """HistoricalStressResult should serialize and deserialize cleanly."""
        plan = _plan()
        raw = run_historical_stress_test(plan, start_year=2000)
        result = HistoricalStressResult(
            simulation_result=raw["simulation_result"],
            metadata=raw["metadata"],
        )

        # Serialize to dict and back
        data = result.model_dump()
        restored = HistoricalStressResult.model_validate(data)

        assert restored.metadata.historical_start_year == 2000
        assert len(restored.simulation_result.yearly_snapshots) == len(
            result.simulation_result.yearly_snapshots
        )
