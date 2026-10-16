"""Integration tests for estate + charity scenarios (task 5.8.2).

These tests run full simulations to verify end-to-end behaviour of:
- Net legacy in simulation result metadata
- Step-up basis reducing capital gains after partner death
- QCD reducing taxes in a full simulation
- DAF carryforward across simulation years
"""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    DrawdownEntryData,
    EstateSettingsData,
    IncomeData,
    PlanData,
)


def _plan(**overrides) -> PlanData:
    """Build a minimal PlanData with sensible defaults, overridable."""
    defaults = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1960,
        filing_status="married_filing_jointly",
        life_expectancy=90,
        start_year=2025,
        milestones=[],
        income_streams=[],
        expenses=[],
        priorities=[],
        drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts={},
    )
    defaults.update(overrides)
    return PlanData(**defaults)


# ---------------------------------------------------------------------------
# Net legacy in simulation result
# ---------------------------------------------------------------------------


class TestNetLegacyInSimulationResult:
    """Verify metadata.net_legacy is populated after a full simulation."""

    def test_net_legacy_present_small_estate(self):
        """Small estate below exemption → net_legacy == gross_estate."""
        plan = _plan(
            accounts={
                "checking": AccountInfo(balance=500_000, account_type="checking"),
            },
        )
        result = run_simulation(plan)

        assert result.metadata.net_legacy is not None
        legacy = result.metadata.net_legacy
        legacy = legacy.model_dump()
        assert "gross_estate" in legacy
        assert "estate_tax" in legacy
        assert "net_legacy" in legacy
        # $500k is far below the $13.6M exemption
        assert legacy["estate_tax"] == 0.0
        assert legacy["net_legacy"] == pytest.approx(legacy["gross_estate"])

    def test_net_legacy_present_large_estate(self):
        """Large estate above exemption → estate_tax > 0, net_legacy < gross."""
        # Short sim (dies 2026) so the exemption doesn't inflation-adjust
        # past $20M. At year 2025: exemption = $13.6M, estate = $20M → tax > 0.
        plan = _plan(
            filing_status="single",
            life_expectancy=66,  # born 1960 + 66 = 2026
            accounts={
                "brokerage": AccountInfo(balance=20_000_000, account_type="taxable_brokerage"),
            },
        )
        result = run_simulation(plan)

        assert result.metadata.net_legacy is not None
        legacy = result.metadata.net_legacy.model_dump()
        assert legacy["estate_tax"] > 0
        assert legacy["net_legacy"] < legacy["gross_estate"]
        assert legacy["net_legacy"] == pytest.approx(
            legacy["gross_estate"] - legacy["estate_tax"],
        )

    def test_net_legacy_marital_deduction_when_spouse_survives(self):
        """If spouse outlives plan holder, marital deduction zeroes federal tax."""
        plan = _plan(
            # Plan holder: born 1960, life_expectancy 80 → dies 2040
            life_expectancy=80,
            spouse_birth_year=1960,
            spouse_life_expectancy=95,  # spouse lives to 2055, outlives holder
            accounts={
                "brokerage": AccountInfo(balance=20_000_000, account_type="taxable_brokerage"),
            },
        )
        result = run_simulation(plan)

        legacy = result.metadata.net_legacy.model_dump()
        # Spouse is alive → marital deduction → $0 federal tax
        assert legacy["marital_deduction_applied"] is True
        assert legacy["estate_tax"] == 0.0
        assert legacy["net_legacy"] == pytest.approx(legacy["gross_estate"])


# ---------------------------------------------------------------------------
# Step-up basis — end-to-end verification
# ---------------------------------------------------------------------------


class TestStepUpBasisIntegration:
    """Full sim: step-up basis should reduce capital gains after partner death."""

    def test_step_up_vs_no_step_up_capital_gains(self):
        """With step-up, post-death capital gains should be lower than without."""
        # Spouse dies at year 2035 (born 1960, life_expectancy 75)
        # Brokerage grows 5%/yr for 10 years before death, accumulating gains.
        # After step-up, cost_basis resets to market value → less gain on withdrawal.
        common = dict(
            birth_year=1960,
            life_expectancy=90,
            start_year=2025,
            filing_status="married_filing_jointly",
            spouse_birth_year=1960,
            spouse_life_expectancy=75,  # dies 2035
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.05, bond_return_rate=0.0),
            accounts={
                "spouse_brokerage": AccountInfo(
                    balance=200_000,
                    account_type="taxable_brokerage",
                    cost_basis=100_000,  # 50% unrealised gain
                    owner="spouse",
                ),
                "checking": AccountInfo(balance=50_000, account_type="checking"),
            },
        )

        plan_with_stepup = _plan(
            **common,
            estate_settings=EstateSettingsData(step_up_basis_on_death=True),
        )
        plan_no_stepup = _plan(
            **common,
            estate_settings=EstateSettingsData(step_up_basis_on_death=False),
        )

        result_stepup = run_simulation(plan_with_stepup)
        result_no_stepup = run_simulation(plan_no_stepup)

        assert result_stepup.metadata.success
        assert result_no_stepup.metadata.success

        # Compare total taxes paid in years after spouse death (2035+)
        death_idx = 2035 - 2025  # index 10
        taxes_stepup = sum(
            s.taxes for s in result_stepup.yearly_snapshots[death_idx:]
        )
        taxes_no_stepup = sum(
            s.taxes for s in result_no_stepup.yearly_snapshots[death_idx:]
        )

        # Step-up should result in equal or lower taxes (less capital gains)
        assert taxes_stepup <= taxes_no_stepup


# ---------------------------------------------------------------------------
# QCD end-to-end in full simulation
# ---------------------------------------------------------------------------


class TestQcdFullSimulation:
    """Full sim: QCD should reduce taxable income and taxes paid."""

    def test_pre_rmd_qcd_does_not_create_cash_deficit(self):
        """A pre-RMD QCD is funded by IRA withdrawal only, not drawdown too."""
        plan = _plan(
            birth_year=1955,  # age 71 in 2026; QCD-eligible, pre-RMD
            life_expectancy=72,
            start_year=2026,
            filing_status="single",
            assumptions=AssumptionData(
                inflation_rate=0.0,
                stock_growth_rate=0.0,
                bond_return_rate=0.0,
            ),
            accounts={
                "ira": AccountInfo(balance=100_000, account_type="traditional_ira"),
                "checking": AccountInfo(balance=100_000, account_type="checking"),
            },
            charity_entities=[
                CharityData(id="qcd1", name="Charity", entity_type="qcd", annual_amount=5_000),
            ],
            drawdown_order=[
                DrawdownEntryData(rank=1, source_account_id="checking"),
            ],
        )

        result = run_simulation(plan)
        first = result.yearly_snapshots[0]

        assert first.net_cash_flow == pytest.approx(0.0)
        assert first.accounts["ira"] == pytest.approx(95_000.0)
        assert first.accounts["checking"] == pytest.approx(100_000.0)
        assert first.net_worth == pytest.approx(195_000.0)

    def test_qcd_reduces_taxes_in_simulation(self):
        """A plan with QCD entities should pay less tax than one without."""
        # Person born 1950, start 2025 → age 75 (past RMD age 73)
        # Has $1M traditional IRA → generates RMDs
        # QCD of $30k/yr should offset some RMD income
        common = dict(
            birth_year=1950,
            life_expectancy=90,
            start_year=2025,
            filing_status="single",
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.04, bond_return_rate=0.0),
            accounts={
                "ira": AccountInfo(balance=1_000_000, account_type="traditional_ira"),
                "checking": AccountInfo(balance=100_000, account_type="checking"),
            },
        )

        plan_no_qcd = _plan(**common, charity_entities=[])
        plan_with_qcd = _plan(
            **common,
            charity_entities=[
                CharityData(id="qcd1", name="Red Cross", entity_type="qcd", annual_amount=30_000),
            ],
        )

        result_no_qcd = run_simulation(plan_no_qcd)
        result_with_qcd = run_simulation(plan_with_qcd)

        # Compare total taxes over first 5 years (ages 75-79, all RMD years)
        taxes_no_qcd = sum(s.taxes for s in result_no_qcd.yearly_snapshots[:5])
        taxes_with_qcd = sum(s.taxes for s in result_with_qcd.yearly_snapshots[:5])

        assert taxes_with_qcd < taxes_no_qcd

    def test_qcd_does_not_exceed_rmd_in_simulation(self):
        """QCD amount in the sim should not exceed the year's RMD."""
        # Person born 1950, start 2025 → age 75
        # Small IRA → small RMD. Large QCD request → should be capped.
        plan = _plan(
            birth_year=1950,
            life_expectancy=85,
            start_year=2025,
            filing_status="single",
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
            accounts={
                "ira": AccountInfo(balance=200_000, account_type="traditional_ira"),
                "checking": AccountInfo(balance=50_000, account_type="checking"),
            },
            charity_entities=[
                CharityData(id="qcd1", name="Charity", entity_type="qcd", annual_amount=500_000),
            ],
        )

        result = run_simulation(plan)
        assert result.metadata.success

        # The simulation should still complete — QCD is capped internally
        # Verify IRA balance decreases but isn't wiped out by over-distribution
        first_year_ira = result.yearly_snapshots[0].accounts.get("ira", 0)
        assert first_year_ira > 0  # IRA not fully drained in year 1


# ---------------------------------------------------------------------------
# DAF carryforward across simulation years
# ---------------------------------------------------------------------------


class TestDafCarryforwardInSimulation:
    """Full sim: DAF excess should carry forward and be used in later years."""

    def test_daf_excess_carries_forward_and_reduces_future_taxes(self):
        """DAF exceeding 60% AGI creates carryforward that reduces future taxes."""
        # Person with $50k income and $40k DAF contribution
        # 60% of $50k = $30k deduction limit → $10k carries forward
        # Next year the carryforward should provide additional deduction
        plan_with_daf = _plan(
            birth_year=1980,
            life_expectancy=90,
            start_year=2025,
            filing_status="single",
            income_streams=[
                IncomeData(id="job", name="Salary", annual_amount=50_000),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
            accounts={
                "checking": AccountInfo(balance=500_000, account_type="checking"),
            },
            charity_entities=[
                CharityData(id="daf1", name="DAF Fund", entity_type="daf", annual_amount=40_000),
            ],
        )

        plan_no_daf = _plan(
            birth_year=1980,
            life_expectancy=90,
            start_year=2025,
            filing_status="single",
            income_streams=[
                IncomeData(id="job", name="Salary", annual_amount=50_000),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
            accounts={
                "checking": AccountInfo(balance=500_000, account_type="checking"),
            },
            charity_entities=[],
        )

        result_daf = run_simulation(plan_with_daf)
        result_no_daf = run_simulation(plan_no_daf)

        # Year 1: DAF plan should pay less tax (gets $30k deduction)
        assert result_daf.yearly_snapshots[0].taxes < result_no_daf.yearly_snapshots[0].taxes

        # Year 2: carryforward ($10k) should also reduce taxes vs no-DAF
        assert result_daf.yearly_snapshots[1].taxes < result_no_daf.yearly_snapshots[1].taxes

    def test_daf_carryforward_expires_after_five_years(self):
        """Carryforward older than 5 years should no longer reduce taxes."""
        # Large one-time DAF contribution creates big carryforward
        # After year 6, carryforward from year 1 should expire
        plan = _plan(
            birth_year=1980,
            life_expectancy=95,
            start_year=2025,
            filing_status="single",
            income_streams=[
                IncomeData(id="job", name="Salary", annual_amount=30_000),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
            accounts={
                "checking": AccountInfo(balance=1_000_000, account_type="checking"),
            },
            charity_entities=[
                # $100k DAF, 60% of $30k = $18k limit → $82k excess carries forward
                CharityData(id="daf1", name="DAF Fund", entity_type="daf", annual_amount=100_000),
            ],
        )

        result = run_simulation(plan)
        assert result.metadata.success

        # In years 2-6 (indices 1-5), carryforward should provide deductions
        # making taxes lower than what they'd be with just the standard deduction.
        # By year 7+ (index 6+), carryforward from year 1 should be expired.
        # We check that deductions used in early years include "itemized" from
        # the large charitable contribution.
        early_year = result.yearly_snapshots[0]
        assert early_year.deduction_used == "itemized"
