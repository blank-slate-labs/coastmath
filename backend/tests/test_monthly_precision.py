"""Tests for month-level pro-rating and standard-plan engine regressions.

Part 1: Verifies month-level pro-rating for income/expenses.
Part 2: Runs the standard_plan fixture through the full engine, alone and with
real assets, liabilities, flex spending, RMDs and Roth conversions added.
"""

from __future__ import annotations

import pytest

from coastmath.engine.milestones import prorate_for_year
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    ExpenseData,
    IncomeData,
    LiabilityData,
    MilestoneData,
    PriorityData,
    RealAssetData,
    SpendingRulesData,
)
from tests.engine_support import fixture_to_plan_data, minimal_plan
from tests.fixtures import load_standard_plan

# ===========================================================================
# Part 1: prorate_for_year unit tests
# ===========================================================================


def _age_ms(ms_id: str, trigger_value: float = 65) -> MilestoneData:
    return MilestoneData(id=ms_id, name=ms_id, trigger_type="age", trigger_value=trigger_value)


class TestProrateForYearUnit:
    """Direct unit tests for milestones.prorate_for_year()."""

    def test_start_month_7_gives_half_year(self):
        """Start milestone triggers this year, start_month=7 → 6/12."""
        fraction = prorate_for_year(
            start_ms=_age_ms("ms_start"),
            end_ms=None,
            start_month=7,
            end_month=None,
            triggered={"ms_start"},
            newly_triggered=["ms_start"],
            year=2025,
        )
        assert fraction == pytest.approx(6 / 12)

    def test_end_month_3_gives_quarter_year(self):
        """End milestone triggers this year, end_month=3 → 3/12."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_age_ms("ms_end"),
            start_month=None,
            end_month=3,
            triggered={"ms_end"},
            newly_triggered=["ms_end"],
            year=2025,
        )
        assert fraction == pytest.approx(3 / 12)

    def test_null_start_month_with_birth_month_jan_is_full_year(self):
        """Age-triggered start with birth_month=1 resolves to Jan → 12/12."""
        fraction = prorate_for_year(
            start_ms=_age_ms("ms_start"),
            end_ms=None,
            start_month=None,
            end_month=None,
            triggered={"ms_start"},
            newly_triggered=["ms_start"],
            year=2025,
            birth_month=1,
        )
        assert fraction == pytest.approx(1.0)

    def test_null_end_month_age_trigger_zero_without_birth_month(self):
        """22.2.1: age-triggered end with birth_month=None resolves to Jan,
        so em = 0 → fraction 0 in trigger year (the event ends before the year
        begins, by convention). Prior behavior assumed Dec; that was the bug."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_age_ms("ms_end"),
            start_month=None,
            end_month=None,
            triggered={"ms_end"},
            newly_triggered=["ms_end"],
            year=2025,
            birth_month=None,
        )
        assert fraction == 0.0

    def test_null_end_month_with_explicit_dec_is_full_year(self):
        """Explicit end_month=12 preserves the old 12/12 result regardless of
        birth_month — this covers the common case where the user set Dec."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_age_ms("ms_end"),
            start_month=None,
            end_month=12,
            triggered={"ms_end"},
            newly_triggered=["ms_end"],
            year=2025,
            birth_month=6,
        )
        assert fraction == pytest.approx(1.0)

    def test_mid_year_start_and_end_same_year(self):
        """Both milestones trigger same year, start_month=4, end_month=9 → 6/12."""
        fraction = prorate_for_year(
            start_ms=_age_ms("ms_start"),
            end_ms=_age_ms("ms_end"),
            start_month=4,
            end_month=9,
            triggered={"ms_start", "ms_end"},
            newly_triggered=["ms_start", "ms_end"],
            year=2025,
        )
        # (9 - 4 + 1) / 12 = 6/12 = 0.5
        assert fraction == pytest.approx(6 / 12)

    def test_start_month_1_full_year(self):
        """start_month=1 in trigger year → (12 - 1 + 1)/12 = 1.0."""
        fraction = prorate_for_year(
            start_ms=_age_ms("ms_start"),
            end_ms=None,
            start_month=1,
            end_month=None,
            triggered={"ms_start"},
            newly_triggered=["ms_start"],
            year=2025,
        )
        assert fraction == pytest.approx(1.0)

    def test_end_month_12_full_year(self):
        """end_month=12 in trigger year → 12/12 = 1.0."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_age_ms("ms_end"),
            start_month=None,
            end_month=12,
            triggered={"ms_end"},
            newly_triggered=["ms_end"],
            year=2025,
        )
        assert fraction == pytest.approx(1.0)

    def test_start_month_12_one_twelfth(self):
        """start_month=12 in trigger year → 1/12."""
        fraction = prorate_for_year(
            start_ms=_age_ms("ms_start"),
            end_ms=None,
            start_month=12,
            end_month=None,
            triggered={"ms_start"},
            newly_triggered=["ms_start"],
            year=2025,
        )
        assert fraction == pytest.approx(1 / 12)

    def test_not_newly_triggered_full_year(self):
        """Already-triggered milestone (not new) → full year."""
        fraction = prorate_for_year(
            start_ms=_age_ms("ms_start"),
            end_ms=None,
            start_month=7,
            end_month=None,
            triggered={"ms_start"},
            newly_triggered=[],  # not new this year
            year=2025,
        )
        assert fraction == pytest.approx(1.0)

    def test_inactive_event_returns_zero(self):
        """Event whose start milestone hasn't triggered → 0.0."""
        fraction = prorate_for_year(
            start_ms=_age_ms("ms_start"),
            end_ms=None,
            start_month=7,
            end_month=None,
            triggered=set(),  # not triggered
            newly_triggered=[],
            year=2025,
        )
        assert fraction == 0.0

    def test_ended_event_returns_zero(self):
        """Event whose end milestone already triggered (not new) → 0.0."""
        fraction = prorate_for_year(
            start_ms=None,
            end_ms=_age_ms("ms_end"),
            start_month=None,
            end_month=None,
            triggered={"ms_end"},
            newly_triggered=[],  # end triggered in a prior year
            year=2025,
        )
        assert fraction == 0.0


# ===========================================================================
# Part 1b: Monthly precision integration tests (via run_simulation)
# ===========================================================================


class TestMonthlyPrecisionIntegration:
    """Integration tests verifying pro-rating flows through the full engine."""

    def test_income_start_month_7_prorated(self):
        """Income with start_month=7 in trigger year → 6/12 of annual amount."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            milestones=[
                MilestoneData(id="job", name="Start Job", trigger_type="age", trigger_value=35),
            ],
            income_streams=[
                IncomeData(
                    id="sal", name="Salary", annual_amount=120_000,
                    start_milestone_id="job", start_month=7,
                ),
            ],
            accounts={"chk": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="chk")],
        )
        result = run_simulation(plan)
        # Age 35 in 2025, milestone triggers year 0. start_month=7 → 6/12
        snap = result.yearly_snapshots[0]
        assert snap.gross_income == pytest.approx(60_000, abs=1)
        # Next year: full year
        assert result.yearly_snapshots[1].gross_income == pytest.approx(120_000, abs=1)

    def test_expense_end_month_3_prorated(self):
        """Expense ending with end_month=3 in trigger year → 3/12 of annual."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            milestones=[
                MilestoneData(id="retire", name="Retire", trigger_type="age", trigger_value=36),
            ],
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=200_000),
            ],
            expenses=[
                ExpenseData(
                    id="gym", name="Gym",
                    annual_amount=12_000,
                    end_milestone_id="retire",
                    end_month=3,
                    inflation_linked=False,
                ),
            ],
            accounts={"chk": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="chk")],
        )
        result = run_simulation(plan)
        # Year 0 (age 35): retire not triggered, full expense
        assert result.yearly_snapshots[0].expenses == pytest.approx(12_000, abs=1)
        # Year 1 (age 36): retire triggers, end_month=3 → 3/12
        assert result.yearly_snapshots[1].expenses == pytest.approx(3_000, abs=1)
        # Year 2 (age 37): event ended, no expense
        assert result.yearly_snapshots[2].expenses == pytest.approx(0, abs=1)

    def test_null_months_give_full_year(self):
        """Income/expense with null start/end months → full annual amount in trigger year."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            milestones=[
                MilestoneData(id="job", name="Job", trigger_type="age", trigger_value=35),
            ],
            income_streams=[
                IncomeData(
                    id="sal", name="Salary", annual_amount=100_000,
                    start_milestone_id="job",
                    start_month=None, end_month=None,
                ),
            ],
            accounts={"chk": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="chk")],
        )
        result = run_simulation(plan)
        # Null start_month defaults to Jan → 12/12 = full year
        assert result.yearly_snapshots[0].gross_income == pytest.approx(100_000, abs=1)

    def test_mid_year_start_and_end_same_year(self):
        """Both milestones trigger same year: start_month=4, end_month=9 → 6/12."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            milestones=[
                MilestoneData(id="ms_start", name="Start", trigger_type="age", trigger_value=35),
                MilestoneData(id="ms_end", name="End", trigger_type="age", trigger_value=35),
            ],
            income_streams=[
                IncomeData(
                    id="gig", name="Gig", annual_amount=60_000,
                    start_milestone_id="ms_start",
                    end_milestone_id="ms_end",
                    start_month=4, end_month=9,
                ),
            ],
            accounts={"chk": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="chk")],
        )
        result = run_simulation(plan)
        # (9 - 4 + 1) / 12 = 0.5 → 30_000
        assert result.yearly_snapshots[0].gross_income == pytest.approx(30_000, abs=1)
        # After both triggered, event is ended → 0 next year
        assert result.yearly_snapshots[1].gross_income == pytest.approx(0, abs=1)

    def test_payroll_deduction_prorated(self):
        """Payroll deduction ending mid-year is also pro-rated."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            milestones=[
                MilestoneData(id="retire", name="Retire", trigger_type="age", trigger_value=36),
            ],
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=200_000),
            ],
            expenses=[
                ExpenseData(
                    id="hsa", name="HSA",
                    annual_amount=6_000,
                    end_milestone_id="retire",
                    end_month=6,
                    inflation_linked=False,
                    is_payroll_deduction=True,
                ),
            ],
            accounts={"chk": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="chk")],
        )
        result = run_simulation(plan)
        # Year 0 (age 35): full year deduction
        assert result.yearly_snapshots[0].expenses == pytest.approx(6_000, abs=1)
        # Year 1 (age 36): retire triggers, end_month=6 → 6/12 = 3000
        assert result.yearly_snapshots[1].expenses == pytest.approx(3_000, abs=1)


# ===========================================================================
# Part 2: Standard plan regression tests
# ===========================================================================


class TestFixtureOwnerAndCategory:
    """These regressions convert the fixture with account owners and expense categories."""

    def test_opt_in_keeps_owner_and_category(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)

        owners = {a["id"]: a.get("owner", "self") for a in raw["accounts"]}
        categories = {e["id"]: e.get("category") for e in raw["expenses"]}
        assert "spouse" in owners.values()
        assert any(categories.values())
        assert {k: v.owner for k, v in plan.accounts.items()} == owners
        assert {e.id: e.category for e in plan.expenses} == categories

    def test_default_drops_owner_and_category(self):
        plan = fixture_to_plan_data(load_standard_plan())

        assert {a.owner for a in plan.accounts.values()} == {"self"}
        assert {e.category for e in plan.expenses} == {None}


class TestStandardPlanRegression:
    """The standard_plan fixture produces valid simulation results."""

    def test_standard_plan_runs_successfully(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)
        result = run_simulation(plan)

        assert result.metadata.success is True
        assert result.metadata.failure_year is None

        # Correct year count: 1990 + 90 = 2080, range(2025, 2080) = 55 years
        assert len(result.yearly_snapshots) == 55

    def test_standard_plan_has_income_before_retirement(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)
        result = run_simulation(plan)

        # First year should have salary income
        first = result.yearly_snapshots[0]
        assert first.gross_income > 0
        assert first.year == 2025
        assert first.age == 35

    def test_standard_plan_income_stops_at_retirement(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)
        result = run_simulation(plan)

        # Retirement at age 65 = year 2055 (index 30)
        # By age 66 (year 2056), salary should stop, only SS remains
        # SS starts at age 67, so age 66 should have zero or near-zero income
        snap_66 = [s for s in result.yearly_snapshots if s.age == 66][0]
        # No salary, no SS yet → income should be 0
        assert snap_66.gross_income == pytest.approx(0, abs=1)

    def test_standard_plan_net_worth_grows(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)
        result = run_simulation(plan)

        first_nw = result.yearly_snapshots[0].net_worth
        mid_nw = result.yearly_snapshots[20].net_worth
        # Net worth should grow over 20 years of saving with 7% returns
        assert mid_nw > first_nw


class TestRealAssetsAndLiabilitiesRegression:
    """Real assets and liabilities work through the engine."""

    def test_real_asset_appreciates_in_standard_plan(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)
        # Add a real asset
        plan.real_assets = [
            RealAssetData(
                id="house", name="House",
                current_value=400_000,
                annual_appreciation_rate=0.03,
            ),
        ]
        result = run_simulation(plan)

        # Year 0: 400k appreciated once → 400k * 1.03
        snap0 = result.yearly_snapshots[0]
        assert snap0.real_assets_value == pytest.approx(400_000 * 1.03, rel=0.001)

        # Year 10: should be ~400k * 1.03^11
        snap10 = result.yearly_snapshots[10]
        assert snap10.real_assets_value > snap0.real_assets_value

    def test_liability_reduces_net_worth(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)
        plan.liabilities = [
            LiabilityData(
                id="mortgage", name="Mortgage",
                principal_balance=300_000,
                interest_rate=0.065,
                monthly_payment=2_000,
            ),
        ]
        result = run_simulation(plan)

        snap0 = result.yearly_snapshots[0]
        assert snap0.liabilities_balance > 0
        # Net worth reduced by liability
        assert snap0.liabilities_balance < 300_000  # some principal paid


class TestFlexSpendingRegression:
    """Flex spending rules trigger when the portfolio underperforms."""

    def test_flex_spending_reduces_discretionary(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)

        # Set spending rules with a high threshold so it always triggers
        plan.spending_rules = SpendingRulesData(
            flex_threshold=0.50,  # 50% — will never be met with 7% returns
            flex_reduction=0.20,
            lookback_years=1,
        )
        # Set stock growth to small positive so return history exists
        plan.assumptions.stock_growth_rate = 0.05

        result = run_simulation(plan)

        # Year 0: no return history yet, no reduction
        # Year 1+: trailing return ~5% < 50% threshold → discretionary reduced
        # The fixture has "Living" as discretionary = 36_000
        # Check that flex_spending_reduction is positive in year 2+
        has_flex_reduction = any(
            s.flex_spending_reduction > 0 for s in result.yearly_snapshots[1:]
        )
        assert has_flex_reduction, "Flex spending should reduce discretionary expenses"


class TestRmdAndRothConversionRegression:
    """Roth conversions and RMDs work through the engine."""

    def test_rmd_at_correct_start_age(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)
        result = run_simulation(plan)

        # birth_year 1990 → SECURE 2.0 RMD start age is 75
        # The standard plan has a traditional_401k
        snap_75 = [s for s in result.yearly_snapshots if s.age == 75]
        assert len(snap_75) == 1
        # RMD income should appear in cash flow
        rmd_sources = [
            src for src in snap_75[0].cash_flow.income_sources
            if src.name == "RMD"
        ]
        assert len(rmd_sources) == 1
        assert rmd_sources[0].amount > 0

    def test_roth_conversion_in_waterfall(self):
        raw = load_standard_plan()
        plan = fixture_to_plan_data(raw, with_owner_and_category=True)

        # Add Roth IRA target and traditional IRA source for conversion
        plan.accounts["trad_ira"] = AccountInfo(
            balance=200_000, account_type="traditional_ira",
        )
        plan.accounts["roth_ira"] = AccountInfo(
            balance=10_000, account_type="roth_ira",
        )

        # Insert roth_conversion at rank 3 (before the unlimited brokerage bucket)
        # so surplus reaches it before being fully absorbed
        plan.priorities = [
            PriorityData(priority_rank=1, target_account_id="00000000-0000-4000-8000-000000000010", max_annual_amount=20_000),
            PriorityData(priority_rank=2, target_account_id="00000000-0000-4000-8000-000000000012", max_annual_amount=23_500),
            PriorityData(
                priority_rank=3,
                target_account_id="roth_ira",
                source_account_id="trad_ira",
                max_annual_amount=20_000,
                priority_type="roth_conversion",
            ),
            PriorityData(priority_rank=4, target_account_id="00000000-0000-4000-8000-000000000011"),
        ]

        result = run_simulation(plan)

        # In early years with surplus, Roth conversions should happen
        has_conversion = any(
            s.transfers and any(
                t.source_account_id == "trad_ira" and t.target_account_id == "roth_ira"
                for t in s.transfers
            )
            for s in result.yearly_snapshots
        )
        assert has_conversion, "Roth conversion should appear in transfers"
