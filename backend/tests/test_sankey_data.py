"""Tests for Sankey CashFlowBreakdown value summation.

Verifies that the CashFlowBreakdown produced by run_simulation has
internally consistent sums — every dollar of gross income flows to
tax, payroll, net pay, expenses, or contributions with no leakage.
"""

from __future__ import annotations

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
    SpendingRulesData,
)


def _base_plan(**overrides) -> PlanData:
    """Minimal PlanData — 1 year of simulation by default."""
    defaults = dict(
        plan_id="00000000-0000-0000-0000-000000000001",
        birth_year=1990,
        filing_status="single",
        life_expectancy=2,  # sim runs [start_year, birth_year+life_expectancy)
        start_year=1990,    # age 0 → 1 year: [1990, 1992) = years 1990, 1991
    )
    defaults.update(overrides)
    return PlanData(**defaults)


class TestGrossIncomeSummation:
    """CashFlowBreakdown.gross_income == sum of income_sources."""

    def test_single_income(self):
        plan = _base_plan(
            income_streams=[
                IncomeData(id="inc1", name="Salary", annual_amount=100_000),
            ],
            accounts={"chk": AccountInfo(balance=10_000, account_type="checking")},
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None

        source_sum = sum(s.amount for s in cf.income_sources)
        assert cf.gross_income == pytest.approx(source_sum)

    def test_multiple_incomes(self):
        plan = _base_plan(
            income_streams=[
                IncomeData(id="inc1", name="Salary", annual_amount=80_000),
                IncomeData(id="inc2", name="Side gig", annual_amount=20_000),
            ],
            accounts={"chk": AccountInfo(balance=10_000, account_type="checking")},
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None

        source_sum = sum(s.amount for s in cf.income_sources)
        assert cf.gross_income == pytest.approx(source_sum)
        assert cf.gross_income == pytest.approx(100_000)


class TestGrossEqualsComponents:
    """gross_income == tax_withheld + payroll_deductions + net_pay."""

    def test_with_withholding_and_payroll(self):
        plan = _base_plan(
            income_streams=[
                IncomeData(
                    id="inc1", name="Salary", annual_amount=100_000,
                    withholding_percent=0.22,
                ),
            ],
            expenses=[
                ExpenseData(
                    id="pd1", name="Health Insurance", annual_amount=5_000,
                    is_payroll_deduction=True,
                ),
            ],
            accounts={"chk": AccountInfo(balance=10_000, account_type="checking")},
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None

        reconstructed = cf.tax_withheld + cf.payroll_deductions + cf.net_pay
        assert cf.gross_income == pytest.approx(reconstructed)

    def test_no_withholding_no_payroll(self):
        plan = _base_plan(
            income_streams=[
                IncomeData(id="inc1", name="Salary", annual_amount=50_000),
            ],
            accounts={"chk": AccountInfo(balance=10_000, account_type="checking")},
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None

        assert cf.tax_withheld == pytest.approx(0.0)
        assert cf.payroll_deductions == pytest.approx(0.0)
        assert cf.net_pay == pytest.approx(cf.gross_income)


class TestDeficitYearDrawdowns:
    """When expenses exceed income, drawdowns should be populated."""

    def test_drawdowns_present(self):
        plan = _base_plan(
            income_streams=[],  # no income
            expenses=[
                ExpenseData(id="exp1", name="Living", annual_amount=30_000),
            ],
            accounts={
                "chk": AccountInfo(balance=50_000, account_type="checking"),
            },
            drawdown_order=[
                DrawdownEntryData(rank=1, source_account_id="chk"),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None

        assert len(cf.drawdowns) > 0
        total_drawdown = sum(d.amount for d in cf.drawdowns)
        assert total_drawdown > 0

    def test_no_drawdowns_when_surplus(self):
        plan = _base_plan(
            income_streams=[
                IncomeData(id="inc1", name="Salary", annual_amount=100_000),
            ],
            expenses=[
                ExpenseData(id="exp1", name="Living", annual_amount=10_000),
            ],
            accounts={"chk": AccountInfo(balance=10_000, account_type="checking")},
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None
        assert len(cf.drawdowns) == 0


class TestFlexRulesReflectedInExpenses:
    """Flex spending rules reduce discretionary expenses."""

    def test_discretionary_reduced_below_threshold(self):
        plan = _base_plan(
            life_expectancy=3,  # need 2+ years so lookback has history
            income_streams=[
                IncomeData(id="inc1", name="Salary", annual_amount=60_000),
            ],
            expenses=[
                ExpenseData(
                    id="exp_e", name="Rent", annual_amount=12_000,
                    category="essential",
                ),
                ExpenseData(
                    id="exp_d", name="Dining", annual_amount=6_000,
                    category="discretionary",
                ),
            ],
            spending_rules=SpendingRulesData(
                flex_threshold=0.10,   # trigger when return < 10%
                flex_reduction=0.20,   # cut discretionary by 20%
                lookback_years=1,
            ),
            accounts={
                # Only zero-growth checking so portfolio return = 0%
                "chk": AccountInfo(balance=100_000, account_type="checking"),
            },
        )
        result = run_simulation(plan)

        # Year index 1 has 1 year of history (year 0 return was 0% < 10%)
        snap = result.yearly_snapshots[1]
        assert snap.flex_spending_reduction > 0

        # The essential expense should be unchanged; discretionary reduced
        cf = snap.cash_flow
        assert cf is not None
        by_name = {e.name: e.amount for e in cf.expenses}
        if "Dining" in by_name:
            # 6000 * 0.80 = 4800
            assert by_name["Dining"] == pytest.approx(4_800, rel=0.05)


class TestTransfersNotCountedAsExpenses:
    """Transfers appear in cash_flow.transfers, not in expenses."""

    def test_roth_conversion_in_transfers(self):
        plan = _base_plan(
            income_streams=[
                IncomeData(id="inc1", name="Salary", annual_amount=80_000),
            ],
            accounts={
                "trad": AccountInfo(balance=50_000, account_type="traditional_ira"),
                "roth": AccountInfo(balance=10_000, account_type="roth_ira"),
                "chk": AccountInfo(balance=10_000, account_type="checking"),
            },
            priorities=[
                PriorityData(
                    priority_rank=1,
                    target_account_id="roth",
                    source_account_id="trad",
                    max_annual_amount=10_000,
                    priority_type="roth_conversion",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None

        # Transfers should be populated
        assert len(cf.transfers) > 0
        transfer_names = {
            (t.source_account_id, t.target_account_id) for t in cf.transfers
        }
        assert ("trad", "roth") in transfer_names

        # Transfers must NOT appear in expenses
        expense_names = {e.name for e in cf.expenses}
        assert "roth_conversion" not in expense_names
        assert "transfer" not in expense_names

    def test_regular_transfer_in_transfers(self):
        plan = _base_plan(
            income_streams=[
                IncomeData(id="inc1", name="Salary", annual_amount=80_000),
            ],
            accounts={
                "chk": AccountInfo(balance=20_000, account_type="checking"),
                "sav": AccountInfo(balance=5_000, account_type="savings"),
            },
            priorities=[
                PriorityData(
                    priority_rank=1,
                    target_account_id="sav",
                    source_account_id="chk",
                    max_annual_amount=5_000,
                    priority_type="transfer",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None

        # Transfer should be present
        assert len(cf.transfers) > 0
        transfer_pairs = {
            (t.source_account_id, t.target_account_id) for t in cf.transfers
        }
        assert ("chk", "sav") in transfer_pairs

        # Transfer must NOT appear in expenses
        expense_names = {e.name for e in cf.expenses}
        assert "transfer" not in expense_names
