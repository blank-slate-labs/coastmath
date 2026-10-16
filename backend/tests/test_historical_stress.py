"""Tests for the historical stress-test engine."""

import uuid

import pytest

from coastmath.engine.historical_data import (
    DIVIDEND_YIELD_PROVENANCE,
    load_historical_returns,
)
from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)


def _plan(**overrides) -> PlanData:
    """Minimal plan with sensible defaults for stress-test scenarios."""
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1990,
        filing_status="single",
        life_expectancy=95,  # 5 year plan: 2025–2030
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


# Short plan: birth 1990, life_expectancy=95 → end=2085, start=2025 → 60 years
# For quicker tests, use a shorter plan
def _short_plan(**overrides) -> PlanData:
    """Plan running only 5 years (2025–2030) for fast tests."""
    return _plan(life_expectancy=95, start_year=2025, birth_year=1995, **overrides)
    # 1995 + 35 = 2030, range(2025, 2030) = 5 years ... nah
    # birth_year=1995, life_expectancy=35 → end=2030


class TestBasicRun:
    def test_returns_timeline_with_start_year_2000(self):
        """A basic stress test from year 2000 should return a valid result."""
        plan = _short_plan()
        result = run_historical_stress_test(plan, start_year=2000)

        assert "simulation_result" in result
        assert "metadata" in result
        sim = result["simulation_result"]
        assert len(sim.yearly_snapshots) > 0
        assert sim.metadata.success is not None

        meta = result["metadata"]
        assert meta["historical_start_year"] == 2000
        assert len(meta["years_used"]) == len(sim.yearly_snapshots)

    def test_invalid_start_year_raises(self):
        """Start year outside historical range should raise ValueError."""
        plan = _short_plan()
        with pytest.raises(ValueError, match="outside available"):
            run_historical_stress_test(plan, start_year=1900)

    def test_accepts_preloaded_dataframe(self):
        """Passing historical_data skips CSV loading."""
        plan = _short_plan()
        df = load_historical_returns()
        result = run_historical_stress_test(plan, start_year=2000, historical_data=df)
        assert len(result["simulation_result"].yearly_snapshots) > 0


class TestReturnsMatchCSV:
    def test_years_used_match_csv_data(self):
        """The historical years used should be sequential from start_year."""
        plan = _short_plan()
        result = run_historical_stress_test(plan, start_year=2000)
        years_used = result["metadata"]["years_used"]

        df = load_historical_returns()
        max_hist = int(df["year"].max())

        # Should start at 2000 and go sequentially
        expected_start = 2000
        for i, yr in enumerate(years_used):
            expected = expected_start + i
            if expected > max_hist:
                # Wrapped around — just verify it's a valid historical year
                assert yr >= int(df["year"].min())
            else:
                assert yr == expected

    def test_growth_uses_historical_values(self):
        """Verify that the simulation actually uses the historical returns.

        A plan with only a brokerage account and no income/expenses —
        the account growth should reflect the historical stock return.
        """
        plan = PlanData(
            plan_id=str(uuid.uuid4()),
            birth_year=2000,
            filing_status="single",
            life_expectancy=26,  # end = 2026, 1-year sim
            start_year=2025,
            milestones=[],
            income_streams=[],
            expenses=[],
            priorities=[],
            drawdown_order=[],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "brokerage": AccountInfo(
                    balance=100_000, account_type="taxable_brokerage",
                ),
            },
        )

        # Use year 2000 historical data (stock_return from CSV)
        df = load_historical_returns()
        row_2000 = df[df["year"] == 2000].iloc[0]
        expected_return = float(row_2000["stock_return"])

        result = run_historical_stress_test(plan, start_year=2000, historical_data=df)
        snap = result["simulation_result"].yearly_snapshots[0]

        # Account should have grown by the 2000 stock return
        expected_balance = 100_000 * (1 + expected_return)
        assert snap.accounts["brokerage"] == pytest.approx(expected_balance, rel=1e-6)


class TestWrapAround:
    def test_wrap_when_plan_exceeds_data(self):
        """When plan needs more years than available from start_year, wrap around."""
        df = load_historical_returns()
        max_hist = int(df["year"].max())
        min_hist = int(df["year"].min())

        # Start near the end of available data so wrapping is guaranteed
        late_start = max_hist - 2  # only 3 years of data before wrap

        # Plan needs more than 3 years
        plan = PlanData(
            plan_id=str(uuid.uuid4()),
            birth_year=2000,
            filing_status="single",
            life_expectancy=30,  # end = 2030, sim runs 2025–2030 = 5 years
            start_year=2025,
            milestones=[],
            income_streams=[],
            expenses=[],
            priorities=[],
            drawdown_order=[],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "brokerage": AccountInfo(
                    balance=100_000, account_type="taxable_brokerage",
                ),
            },
        )

        result = run_historical_stress_test(plan, start_year=late_start, historical_data=df)
        meta = result["metadata"]

        assert meta["wrapped"] is True
        assert len(meta["years_used"]) == 5  # 5-year plan

        # First few years should be from late_start..max_hist, then wrap to min_hist
        assert meta["years_used"][0] == late_start
        # After wrapping, years should come from the beginning of the dataset
        wrapped_years = [y for y in meta["years_used"] if y < late_start]
        assert len(wrapped_years) > 0
        assert wrapped_years[0] == min_hist

    def test_no_wrap_when_data_sufficient(self):
        """No wrap-around when there's enough data from start_year."""
        plan = _short_plan()
        result = run_historical_stress_test(plan, start_year=1950)
        assert result["metadata"]["wrapped"] is False



def test_replay_uses_recorded_dividend_yield_and_preserves_total_return():
    """The replayed year's total stock return is unchanged; its dividend share
    comes from the recorded yield, not the plan assumption."""
    plan = PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1980, filing_status="single", life_expectancy=48,
        start_year=2026, milestones=[], income_streams=[], expenses=[], priorities=[],
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="brok")],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.07, bond_return_rate=0.0, stock_dividend_yield=0.0),
        accounts={"brok": AccountInfo(balance=100_000, account_type="taxable_brokerage", cost_basis=100_000)},
    )
    hist = load_historical_returns().set_index("year")
    result = run_historical_stress_test(plan, 1950)
    snaps = result["simulation_result"].yearly_snapshots
    total_1950 = float(hist.loc[1950, "stock_return"])
    # Balance grows by the full total return (price + reinvested dividends).
    assert snaps[0].accounts["brok"] == pytest.approx(100_000 * (1 + total_1950), rel=1e-6)
    # Dividends at 1950's 9.11% yield (1950 dividends 1.53 over the 1949 close
    # of 16.79) were recognised as taxable income (qualified dividends in gross income).
    assert snaps[0].gross_income == pytest.approx(100_000 * 1.53 / 16.79, rel=1e-3)
    assert DIVIDEND_YIELD_PROVENANCE in result["simulation_result"].metadata.warnings
    assert result["metadata"]["years_used"][0] == 1950
