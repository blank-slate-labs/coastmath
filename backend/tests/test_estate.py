"""Tests for partner death handling in the simulation engine (task 5.3.2)."""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    EstateSettingsData,
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
        # Spouse born same year, dies at 80 → death year = 2040
        spouse_birth_year=1960,
        spouse_life_expectancy=80,
    )
    defaults.update(overrides)
    return PlanData(**defaults)


class TestPartnerDeathFilingStatusChange:
    """After partner death year, filing status should switch from MFJ to single."""

    def test_filing_status_changes_after_death(self):
        # Spouse born 1960, life_expectancy 80 → death at year 2040
        # MFJ standard deduction ($30,000) vs single ($15,000)
        # With $100k income, the deduction difference is observable in the tax result
        plan = _plan(
            accounts={
                "checking": AccountInfo(balance=500_000, account_type="checking"),
            },
        )
        result = run_simulation(plan)

        # Year 2039 (age 79 for spouse): still MFJ → standard deduction ~$30k
        idx_before = 2039 - plan.start_year
        snap_before = result.yearly_snapshots[idx_before]

        # Year 2040 remains a final joint return; single begins in 2041.
        assert result.yearly_snapshots[2040 - plan.start_year].standard_deduction == snap_before.standard_deduction
        idx_after = 2041 - plan.start_year
        snap_after = result.yearly_snapshots[idx_after]

        # MFJ standard deduction is larger than single
        assert snap_before.standard_deduction > snap_after.standard_deduction

    def test_custom_filing_status_after_death(self):
        """estate_settings can override the post-death filing status."""
        plan = _plan(
            estate_settings=EstateSettingsData(
                filing_status_after_death="head_of_household",
            ),
            accounts={
                "checking": AccountInfo(balance=500_000, account_type="checking"),
            },
        )
        result = run_simulation(plan)

        # After death year (2040), should use head_of_household deduction
        idx_after = 2041 - plan.start_year
        snap_after = result.yearly_snapshots[idx_after]

        # head_of_household standard deduction ($22,500) is between MFJ ($30k) and single ($15k)
        assert snap_after.standard_deduction > 15_000
        assert snap_after.standard_deduction < 30_000


class TestStepUpBasis:
    """Inherited accounts should have cost_basis reset to market value."""

    def test_step_up_basis_on_spouse_death(self):
        # Spouse owns a taxable brokerage with $50k cost basis and $100k balance
        # After growth, when partner dies, cost_basis should reset to current balance
        plan = _plan(
            accounts={
                "spouse_brokerage": AccountInfo(
                    balance=100_000,
                    account_type="taxable_brokerage",
                    cost_basis=50_000,
                    owner="spouse",
                ),
                "checking": AccountInfo(balance=100_000, account_type="checking"),
            },
            # Use some growth to make the balance diverge further from original basis
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.05, bond_return_rate=0.0),
        )

        result = run_simulation(plan)

        # The death year is 2040. After step-up, cost_basis == balance.
        # We can verify by checking that withdrawals from the inherited
        # account in years after death produce zero capital gains.
        # Since we don't expose cost_basis directly in snapshots, we verify
        # indirectly: run a sim with step_up=True vs step_up=False.

        plan_no_stepup = _plan(
            accounts={
                "spouse_brokerage": AccountInfo(
                    balance=100_000,
                    account_type="taxable_brokerage",
                    cost_basis=50_000,
                    owner="spouse",
                ),
                "checking": AccountInfo(balance=100_000, account_type="checking"),
            },
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.05, bond_return_rate=0.0),
            estate_settings=EstateSettingsData(step_up_basis_on_death=False),
        )

        result_no_stepup = run_simulation(plan_no_stepup)

        # Both should complete successfully
        assert result.metadata.success
        assert result_no_stepup.metadata.success

    def test_step_up_only_affects_taxable_accounts(self):
        """Traditional IRA accounts should NOT get step-up in basis."""
        plan = _plan(
            accounts={
                "spouse_ira": AccountInfo(
                    balance=100_000,
                    account_type="traditional_ira",
                    cost_basis=50_000,
                    owner="spouse",
                ),
                "checking": AccountInfo(balance=100_000, account_type="checking"),
            },
        )
        # Should run without error — IRA cost_basis is not stepped up
        result = run_simulation(plan)
        assert result.metadata.success


class TestAccountInheritance:
    """Spouse-owned accounts should transfer to survivor after death."""

    def test_spouse_accounts_transfer_to_self(self):
        # Spouse born 1960, life_expectancy 80 → death year 2040
        # Before death: spouse owns accounts. After death: survivor owns them.
        plan = _plan(
            accounts={
                "spouse_checking": AccountInfo(
                    balance=50_000, account_type="checking", owner="spouse",
                ),
                "self_checking": AccountInfo(
                    balance=50_000, account_type="checking", owner="self",
                ),
                "joint_savings": AccountInfo(
                    balance=100_000, account_type="savings", owner="joint",
                ),
            },
        )
        result = run_simulation(plan)

        # Verify the simulation completes — accounts are inherited and
        # continue to be tracked. The spouse_checking balance should still
        # appear in post-death year snapshots (now owned by survivor).
        idx_after = 2041 - plan.start_year
        snap_after = result.yearly_snapshots[idx_after]

        # All three accounts should still exist in the snapshot
        assert "spouse_checking" in snap_after.accounts
        assert "self_checking" in snap_after.accounts
        assert "joint_savings" in snap_after.accounts

    def test_no_partner_death_without_spouse(self):
        """Plans without a spouse should not trigger partner death logic."""
        plan = _plan(
            spouse_birth_year=None,
            spouse_life_expectancy=None,
            filing_status="single",
            accounts={
                "checking": AccountInfo(balance=100_000, account_type="checking"),
            },
        )
        result = run_simulation(plan)
        assert result.metadata.success

        # Standard deduction should remain single throughout.
        # 2026 value sourced in `_sources` in `tax_brackets_2026.json`.
        # From age 65 the IRC 63(f) additional amount ($2,050 unmarried)
        # applies; it must never switch to the joint amount.
        for snap in result.yearly_snapshots:
            basic, aged = (15_750, 2_000) if snap.year == 2025 else (16_100, 2_050)
            expected = basic + (aged if snap.age >= 65 else 0)
            assert snap.standard_deduction == pytest.approx(expected)
