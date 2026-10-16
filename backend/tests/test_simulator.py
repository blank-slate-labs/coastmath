"""Tests for the main simulation loop (run_simulation)."""

import uuid

import pytest

from coastmath.engine.amortization import calculate_fixed_payment
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate as calc_tax
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    MilestoneData,
    PriorityData,
    RealAssetData,
    SimState,
)
from tests.engine_support import minimal_plan

# ---------------------------------------------------------------------------
# Basic operation
# ---------------------------------------------------------------------------


class TestBasicSimulation:
    def test_empty_plan_runs(self):
        """A plan with no income/expenses/accounts should produce snapshots with zeros."""
        plan = minimal_plan(start_year=2025, life_expectancy=93, birth_year=1990)
        result = run_simulation(plan)
        # 1990 + 93 = 2083, range(2025, 2083) = 58 years
        assert len(result.yearly_snapshots) == 58
        assert result.metadata.success is True
        assert result.metadata.failure_year is None
        for snap in result.yearly_snapshots:
            assert snap.gross_income == 0
            assert snap.taxes == 0
            assert snap.net_worth == 0

    def test_metadata_fields(self):
        plan = minimal_plan(start_year=2025, birth_year=1990, life_expectancy=92)
        result = run_simulation(plan)
        assert result.metadata.start_year == 2025
        assert result.metadata.end_year == 2081  # last simulated year
        assert isinstance(result.metadata.plan_id, uuid.UUID)

    def test_age_calculation(self):
        plan = minimal_plan(start_year=2025, birth_year=1990, life_expectancy=92)
        result = run_simulation(plan)
        first = result.yearly_snapshots[0]
        assert first.year == 2025
        assert first.age == 35  # 2025 - 1990


# ---------------------------------------------------------------------------
# Income
# ---------------------------------------------------------------------------


class TestIncome:
    def test_basic_income(self):
        """Flat income with no growth should appear as gross_income each year."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        assert snap.gross_income == 100_000

    def test_income_growth(self):
        """Income should compound at growth_rate from start_year."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000, growth_rate=0.05),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        # Year 0: 100k, Year 1: 105k
        assert result.yearly_snapshots[0].gross_income == 100_000
        assert abs(result.yearly_snapshots[1].gross_income - 105_000) < 0.01

    def test_income_growth_stops_at_nominal_cap(self):
        plan = minimal_plan(
            income_streams=[
                IncomeData(
                    id="sal",
                    name="Salary",
                    annual_amount=100_000,
                    growth_rate=0.10,
                    growth_cap=115_000,
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )

        result = run_simulation(plan)

        assert result.yearly_snapshots[0].gross_income == 100_000
        assert result.yearly_snapshots[1].gross_income == pytest.approx(110_000)
        assert result.yearly_snapshots[2].gross_income == pytest.approx(115_000)
        assert result.yearly_snapshots[3].gross_income == pytest.approx(115_000)

    def test_income_growth_cap_can_track_inflation(self):
        plan = minimal_plan(
            income_streams=[
                IncomeData(
                    id="sal",
                    name="Salary",
                    annual_amount=100_000,
                    growth_rate=0.20,
                    growth_cap=105_000,
                    growth_cap_inflation_linked=True,
                ),
            ],
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )

        snapshots = run_simulation(plan).yearly_snapshots

        assert snapshots[0].gross_income == pytest.approx(100_000)
        assert snapshots[1].gross_income == pytest.approx(105_000 * 1.03)
        assert snapshots[2].gross_income == pytest.approx(105_000 * 1.03**2)

    def test_income_withholding(self):
        """Withholding should reduce net cash flow but not gross income."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(
                    id="sal", name="Salary", annual_amount=100_000,
                    withholding_percent=0.25,
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        assert snap.gross_income == 100_000
        # Net cash = (100k - 0 - 25k) + (25k - actual_tax) - 0
        # = 100k - actual_tax
        # Taxes should be less than withholding for 100k single filer


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------


class TestExpenses:
    def test_standard_expense_reduces_cash_flow(self):
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000),
            ],
            expenses=[
                ExpenseData(id="rent", name="Rent", annual_amount=24_000, inflation_linked=False),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        assert snap.expenses == 24_000

    def test_inflation_linked_expense(self):
        """Inflation-linked expenses grow with inflation_factor each year."""
        plan = minimal_plan(
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=200_000),
            ],
            expenses=[
                ExpenseData(id="rent", name="Rent", annual_amount=24_000, inflation_linked=True),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        # Year 0: 24_000 * 1.0 (inflation_factor starts at 1)
        assert result.yearly_snapshots[0].expenses == 24_000
        # Year 1: 24_000 * 1.03 (after one inflate step)
        assert abs(result.yearly_snapshots[1].expenses - 24_000 * 1.03) < 0.01

    def test_payroll_deduction(self):
        """Payroll deductions are tracked in expenses and reduce taxable income."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000),
            ],
            expenses=[
                ExpenseData(
                    id="401k", name="401k Contribution",
                    annual_amount=10_000,
                    is_payroll_deduction=True,
                    inflation_linked=False,
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Expenses should include payroll deductions
        assert snap.expenses == 10_000

    def test_specific_funding_source(self):
        """Expenses with specific_funding_source_id draw from the named account."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=50_000),
            ],
            expenses=[
                ExpenseData(
                    id="hsa", name="HSA Expense",
                    annual_amount=5_000,
                    specific_funding_source_id="hsa_acct",
                    inflation_linked=False,
                ),
            ],
            accounts={
                "checking": AccountInfo(balance=0, account_type="checking"),
                "hsa_acct": AccountInfo(balance=20_000, account_type="brokerage"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # HSA expense should have drawn from hsa_acct, not from cash flow
        assert snap.accounts["hsa_acct"] == 20_000 - 5_000

    def test_custom_growth_rate_stops_at_nominal_cap(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=2000,
            life_expectancy=33,
            expenses=[
                ExpenseData(
                    id="living",
                    name="Living",
                    annual_amount=24_000,
                    inflation_linked=False,
                    growth_rate=0.05,
                    growth_cap=30_000,
                ),
            ],
            accounts={"cash": AccountInfo(balance=1_000_000, account_type="checking")},
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
        )

        snapshots = {s.year: s for s in run_simulation(plan).yearly_snapshots}

        assert snapshots[2026].expenses == pytest.approx(24_000)
        assert snapshots[2027].expenses == pytest.approx(25_200)  # 24,000 x 1.05
        # 24,000 x 1.05^4 = 29,172.15, still under the cap; 1.05^5 would be 30,630.76.
        assert snapshots[2030].expenses == pytest.approx(29_172.15)
        assert snapshots[2031].expenses == pytest.approx(30_000)
        assert snapshots[2032].expenses == pytest.approx(30_000)

    def test_custom_growth_cap_can_track_inflation(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=2000,
            life_expectancy=30,
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(
                    id="living",
                    name="Living",
                    annual_amount=24_000,
                    inflation_linked=False,
                    growth_rate=0.10,
                    growth_cap=25_000,
                    growth_cap_inflation_linked=True,
                ),
            ],
            accounts={"cash": AccountInfo(balance=1_000_000, account_type="checking")},
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
        )

        snapshots = {s.year: s for s in run_simulation(plan).yearly_snapshots}

        assert snapshots[2026].expenses == pytest.approx(24_000)
        # Uncapped growth (26,400 in 2027, 29,040 in 2028) passes the inflated cap
        # (25,750 in 2027, 26,522.50 in 2028), so the cap sets the amount.
        assert snapshots[2027].expenses == pytest.approx(25_000 * 1.03)
        assert snapshots[2028].expenses == pytest.approx(25_000 * 1.03**2)

    def test_recurring_expense_occurs_on_interval_and_grows_per_occurrence(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=2000,
            life_expectancy=55,
            milestones=[
                MilestoneData(
                    id="roof_start",
                    name="Roof replacement starts",
                    trigger_type="date",
                    trigger_date="2034-01-01",
                ),
            ],
            expenses=[
                ExpenseData(
                    id="roof",
                    name="Roof replacement",
                    annual_amount=40_000,
                    start_milestone_id="roof_start",
                    inflation_linked=False,
                    recurrence_years=15,
                    recurrence_growth_rate=0.10,
                ),
            ],
            accounts={"cash": AccountInfo(balance=1_000_000, account_type="checking")},
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
        )

        snapshots = {s.year: s for s in run_simulation(plan).yearly_snapshots}

        assert snapshots[2033].expenses == 0
        assert snapshots[2034].expenses == pytest.approx(40_000)
        assert snapshots[2035].expenses == 0
        assert snapshots[2048].expenses == 0
        # Second occurrence, 15 years on: 40,000 x 1.10.
        assert snapshots[2049].expenses == pytest.approx(44_000)


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------


class TestMilestones:
    def test_age_milestone_activates_income(self):
        """Income bounded by an age milestone should only appear after trigger."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            milestones=[
                MilestoneData(id="retire", name="Retirement", trigger_type="age", trigger_value=65),
            ],
            income_streams=[
                IncomeData(
                    id="ss", name="Social Security", annual_amount=30_000,
                    start_milestone_id="retire",
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        # Age 65 = year 2055, index = 2055 - 2025 = 30
        for snap in result.yearly_snapshots[:30]:
            assert snap.gross_income == 0, f"Year {snap.year} should have no income"
        # Year 30 (age 65) should have income
        assert result.yearly_snapshots[30].gross_income > 0

    def test_expense_multiple_and_relative_retirement_stop_income(self):
        plan = minimal_plan(
            birth_year=2000,
            start_year=2025,
            life_expectancy=27,
            milestones=[
                MilestoneData(
                    id="fi",
                    name="FI",
                    trigger_type="expense_multiple",
                    metric="liquid_net_worth",
                    expense_multiple=20,
                ),
                MilestoneData(
                    id="retire",
                    name="Retirement",
                    trigger_type="relative",
                    relative_to_id="fi",
                    offset_years=0,
                ),
            ],
            income_streams=[
                IncomeData(
                    id="salary",
                    name="Salary",
                    annual_amount=100_000,
                    end_milestone_id="retire",
                ),
            ],
            expenses=[
                ExpenseData(
                    id="living",
                    name="Living",
                    annual_amount=100_000,
                    inflation_linked=False,
                ),
            ],
            accounts={
                "portfolio": AccountInfo(
                    balance=2_000_001,
                    account_type="taxable_brokerage",
                    cost_basis=2_000_001,
                ),
            },
            drawdown_order=[
                DrawdownEntryData(rank=1, source_account_id="portfolio"),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.0,
                "capital_gains_tax_rate": 0.0,
            },
        )

        first, second = run_simulation(plan).yearly_snapshots

        assert first.gross_income == 100_000
        assert second.gross_income == 0
        assert second.milestones_triggered == ["fi", "retire"]

    def test_milestone_ends_income(self):
        """Income with an end milestone should stop after trigger."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            milestones=[
                MilestoneData(id="retire", name="Retirement", trigger_type="age", trigger_value=40),
            ],
            income_streams=[
                IncomeData(
                    id="sal", name="Salary", annual_amount=100_000,
                    end_milestone_id="retire",
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        # Age 40 = year 2030, index 5. Income active years 0..4 (age 35..39).
        # At age 40, end milestone triggers so income deactivates.
        assert result.yearly_snapshots[0].gross_income == 100_000
        # After age 40 milestone triggers, income should stop
        for snap in result.yearly_snapshots:
            if snap.age > 40:
                assert snap.gross_income == 0, f"Year {snap.year} age {snap.age} should have no income"


# ---------------------------------------------------------------------------
# Market growth
# ---------------------------------------------------------------------------


class TestMarketGrowth:
    def test_investment_accounts_grow(self):
        """Brokerage accounts should grow at stock_growth_rate."""
        plan = minimal_plan(
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.07),
            accounts={"brok": AccountInfo(balance=100_000, account_type="brokerage")},
        )
        result = run_simulation(plan)
        # After year 0: 100_000 * 1.07 = 107_000
        assert abs(result.yearly_snapshots[0].accounts["brok"] - 107_000) < 0.01

    def test_checking_no_growth(self):
        """Checking accounts should not grow."""
        plan = minimal_plan(
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.07),
            accounts={"chk": AccountInfo(balance=50_000, account_type="checking")},
        )
        result = run_simulation(plan)
        assert result.yearly_snapshots[0].accounts["chk"] == 50_000

    def test_savings_no_growth(self):
        """Savings accounts should not grow."""
        plan = minimal_plan(
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.07),
            accounts={"sav": AccountInfo(balance=50_000, account_type="savings")},
        )
        result = run_simulation(plan)
        assert result.yearly_snapshots[0].accounts["sav"] == 50_000

    def test_monthly_cash_flow_mode_grows_contributions_during_year(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=2000,
            life_expectancy=27,
            income_streams=[
                IncomeData(id="salary", name="Salary", annual_amount=120_000),
            ],
            priorities=[
                PriorityData(priority_rank=1, target_account_id="taxable"),
            ],
            assumptions=AssumptionData(
                inflation_rate=0.0,
                stock_growth_rate=0.06,
                stock_dividend_yield=0.025,
            ),
            accounts={
                "taxable": AccountInfo(
                    balance=0,
                    account_type="taxable_brokerage",
                    cost_basis=0,
                ),
            },
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.0,
                "capital_gains_tax_rate": 0.0,
                "cash_flow_frequency": "monthly",
            },
        )

        snapshot = run_simulation(plan).yearly_snapshots[0]
        expected_growth = sum(10_000 * 1.085 ** (m / 12) for m in range(12)) - 120_000

        assert snapshot.accounts["taxable"] == pytest.approx(
            120_000 + expected_growth,
        )
        assert snapshot.investment_growth == pytest.approx(expected_growth)
        assert snapshot.capital_gains_tax == 0

    def test_monthly_cash_flow_mode_removes_growth_after_withdrawals(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=1966,
            life_expectancy=61,
            expenses=[
                ExpenseData(
                    id="living",
                    name="Living",
                    annual_amount=120_000,
                    inflation_linked=False,
                ),
            ],
            assumptions=AssumptionData(
                inflation_rate=0.0,
                stock_growth_rate=0.06,
                stock_dividend_yield=0.025,
            ),
            accounts={
                "taxable": AccountInfo(
                    balance=500_000,
                    account_type="taxable_brokerage",
                    cost_basis=500_000,
                ),
            },
            drawdown_order=[
                DrawdownEntryData(rank=1, source_account_id="taxable"),
            ],
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.0,
                "capital_gains_tax_rate": 0.0,
                "cash_flow_frequency": "monthly",
            },
        )

        snapshot = run_simulation(plan).yearly_snapshots[0]
        # Independent monthly annuity: total annual return is 8.5%.
        monthly_rate = 1.085 ** (1 / 12) - 1
        ending = 500_000.0
        for _ in range(12):
            ending = ending * (1 + monthly_rate) - 10_000
        foregone_growth = 500_000 * 1.085 - 120_000 - ending

        assert snapshot.accounts["taxable"] == pytest.approx(
            500_000 * 1.085 - 120_000 - foregone_growth,
        )
        assert snapshot.investment_growth == pytest.approx(
            42_500 - foregone_growth,
        )

    def test_taxable_dividend_is_reinvested_and_increases_cost_basis(self):
        state = SimState(
            year=2026,
            accounts={
                "taxable": AccountInfo(
                    balance=100_000,
                    account_type="taxable_brokerage",
                    cost_basis=100_000,
                ),
            },
        )

        dividends, interest = state.apply_growth(
            stock_growth_rate=0.06,
            stock_dividend_yield=0.025,
        )

        assert dividends == pytest.approx(2_500)
        assert interest == 0
        assert state.accounts["taxable"].balance == pytest.approx(108_500)
        assert state.accounts["taxable"].cost_basis == pytest.approx(102_500)
        assert state.capital_gains_this_year == 0
        assert state.qualified_dividends_this_year == pytest.approx(2_500)

    def test_taxable_dividend_flows_through_capital_gains_tax(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=2000,
            life_expectancy=27,
            assumptions=AssumptionData(
                inflation_rate=0.0,
                stock_growth_rate=0.06,
                stock_dividend_yield=0.025,
            ),
            accounts={
                "taxable": AccountInfo(
                    balance=100_000,
                    account_type="taxable_brokerage",
                    cost_basis=100_000,
                ),
                "cash": AccountInfo(balance=1_000, account_type="savings"),
            },
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.30,
                "capital_gains_tax_rate": 0.15,
            },
        )

        snapshot = run_simulation(plan).yearly_snapshots[0]

        assert snapshot.gross_income == pytest.approx(2_500)
        assert snapshot.capital_gains_tax == pytest.approx(375)
        assert snapshot.accounts["taxable"] == pytest.approx(108_500)
        assert snapshot.accounts["cash"] == pytest.approx(625)
        assert snapshot.net_worth == pytest.approx(109_125)

    def test_cash_yield_is_spendable_ordinary_income_without_double_deposit(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=2000,
            life_expectancy=27,
            assumptions=AssumptionData(
                inflation_rate=0.0,
                stock_growth_rate=0.0,
                cash_yield_rate=0.0005,
            ),
            accounts={"savings": AccountInfo(balance=60_000, account_type="savings")},
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.30,
                "capital_gains_tax_rate": 0.15,
            },
        )

        snapshot = run_simulation(plan).yearly_snapshots[0]

        assert snapshot.gross_income == pytest.approx(30)
        assert snapshot.federal_tax == pytest.approx(9)
        assert snapshot.accounts["savings"] == pytest.approx(60_021)

    def test_crypto_receives_price_growth_but_no_stock_dividend(self):
        plan = minimal_plan(
            assumptions=AssumptionData(
                inflation_rate=0.0,
                stock_growth_rate=0.06,
                stock_dividend_yield=0.025,
            ),
            accounts={
                "crypto": AccountInfo(balance=25_000, account_type="cryptocurrency"),
            },
        )

        snapshot = run_simulation(plan).yearly_snapshots[0]

        assert snapshot.accounts["crypto"] == pytest.approx(26_500)
        assert snapshot.gross_income == 0


# ---------------------------------------------------------------------------
# Drawdown and failure
# ---------------------------------------------------------------------------


class TestDrawdown:
    def test_deficit_triggers_drawdown(self):
        """When expenses exceed income, accounts should be drawn down."""
        plan = minimal_plan(
            expenses=[
                ExpenseData(id="rent", name="Rent", annual_amount=50_000, inflation_linked=False),
            ],
            accounts={"brok": AccountInfo(balance=200_000, account_type="brokerage")},
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="brok")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # No income, 50k expense → deficit of 50k + taxes (taxes on 0 income = 0)
        # Net cash = (0 - 0 - 0) + (0 - 0) - 50_000 = -50_000
        assert snap.accounts["brok"] < 200_000

    def test_failure_year_when_exhausted(self):
        """Plan should report failure when all accounts run out."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            expenses=[
                ExpenseData(id="rent", name="Rent", annual_amount=100_000, inflation_linked=False),
            ],
            accounts={"brok": AccountInfo(balance=200_000, account_type="brokerage")},
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="brok")],
        )
        result = run_simulation(plan)
        assert result.metadata.success is False
        assert result.metadata.failure_year is not None
        assert result.metadata.failure_year >= 2025


# ---------------------------------------------------------------------------
# Waterfall surplus allocation
# ---------------------------------------------------------------------------


class TestSurplus:
    def test_surplus_allocated_to_priority_accounts(self):
        """Surplus after taxes/expenses should flow to priority accounts."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000),
            ],
            accounts={
                "ira": AccountInfo(balance=0, account_type="brokerage"),
                "brok": AccountInfo(balance=0, account_type="brokerage"),
            },
            priorities=[
                PriorityData(priority_rank=1, target_account_id="ira", max_annual_amount=6_500),
                PriorityData(priority_rank=2, target_account_id="brok"),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # IRA should get up to 6500
        assert snap.accounts["ira"] == 6_500
        # Brokerage gets the rest of surplus
        assert snap.accounts["brok"] > 0


# ---------------------------------------------------------------------------
# Pro-rating
# ---------------------------------------------------------------------------


class TestProrating:
    def test_income_prorated_in_start_year(self):
        """Income starting mid-year should be pro-rated."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            milestones=[
                MilestoneData(id="start_job", name="Start Job", trigger_type="age", trigger_value=35),
            ],
            income_streams=[
                IncomeData(
                    id="sal", name="Salary", annual_amount=120_000,
                    start_milestone_id="start_job",
                    start_month=7,  # July start
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        # Age 35 = 2025, milestone triggers year 0. start_month=7 → 6/12 = 0.5
        snap = result.yearly_snapshots[0]
        assert abs(snap.gross_income - 60_000) < 0.01  # 120k * 0.5


# ---------------------------------------------------------------------------
# Real asset appreciation
# ---------------------------------------------------------------------------


class TestRealAssetAppreciation:
    def test_no_real_assets_unchanged(self):
        """Plans without real assets should behave identically to before."""
        plan = minimal_plan(
            accounts={"chk": AccountInfo(balance=10_000, account_type="checking")},
        )
        result = run_simulation(plan)
        for snap in result.yearly_snapshots:
            assert snap.real_assets_value == 0.0
            assert snap.liabilities_balance == 0.0
            assert snap.net_worth == snap.accounts.get("chk", 0.0)

    def test_single_asset_appreciates(self):
        """A real asset should compound at its annual_appreciation_rate."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=93,
            real_assets=[
                RealAssetData(id="house", name="House", current_value=300_000, annual_appreciation_rate=0.05),
            ],
        )
        result = run_simulation(plan)
        # After year 0: 300_000 * 1.05
        assert abs(result.yearly_snapshots[0].real_assets_value - 300_000 * 1.05) < 0.01
        # After year 1: 300_000 * 1.05^2
        assert abs(result.yearly_snapshots[1].real_assets_value - 300_000 * 1.05 ** 2) < 0.01

    def test_real_assets_included_in_net_worth(self):
        """Net worth should include liquid accounts + real assets."""
        plan = minimal_plan(
            accounts={"brok": AccountInfo(balance=100_000, account_type="checking")},
            real_assets=[
                RealAssetData(id="house", name="House", current_value=200_000, annual_appreciation_rate=0.0),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # 0% appreciation → value stays 200k, checking stays 100k
        assert abs(snap.real_assets_value - 200_000) < 0.01
        assert abs(snap.net_worth - 300_000) < 0.01

    def test_multiple_assets_different_rates(self):
        """Multiple real assets should each appreciate independently."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=93,
            real_assets=[
                RealAssetData(id="house", name="House", current_value=300_000, annual_appreciation_rate=0.05),
                RealAssetData(id="land", name="Land", current_value=100_000, annual_appreciation_rate=0.02),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        expected = 300_000 * 1.05 + 100_000 * 1.02
        assert abs(snap.real_assets_value - expected) < 0.01


# ---------------------------------------------------------------------------
# Liability payments
# ---------------------------------------------------------------------------


class TestLiabilityPayments:
    def test_liability_payment_reduces_balance(self):
        """Mortgage balance should decrease each year via amortization."""
        principal = 200_000.0
        rate = 0.06
        term = 360  # 30-year mortgage
        monthly_pmt = calculate_fixed_payment(principal, rate, term)

        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=93,
            liabilities=[
                LiabilityData(
                    id="mortgage",
                    name="Mortgage",
                    principal_balance=principal,
                    interest_rate=rate,
                    term_months=term,
                    monthly_payment=monthly_pmt,
                ),
            ],
        )
        result = run_simulation(plan)
        y0 = result.yearly_snapshots[0]
        y1 = result.yearly_snapshots[1]
        # Balance should decrease over time
        assert y0.liabilities_balance < principal
        assert y1.liabilities_balance < y0.liabilities_balance

    def test_liability_payment_reduces_net_cash(self):
        """Liability payments should reduce net cash flow."""
        principal = 100_000.0
        rate = 0.05
        term = 360
        monthly_pmt = calculate_fixed_payment(principal, rate, term)
        annual_pmt_approx = monthly_pmt * 12  # ~$6,442

        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=100_000, withholding_percent=0.0),
            ],
            liabilities=[
                LiabilityData(
                    id="loan",
                    name="Loan",
                    principal_balance=principal,
                    interest_rate=rate,
                    term_months=term,
                    monthly_payment=monthly_pmt,
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Net cash should be reduced by approximately the annual payment
        # Without liability: net_cash ~ 100k - taxes
        # With liability: net_cash ~ 100k - taxes - ~6442
        assert snap.net_cash_flow < 100_000  # reduced by taxes + liability
        # The liability payment is roughly monthly_pmt * 12
        assert snap.net_cash_flow < (100_000 - annual_pmt_approx + 1000)

    def test_liability_in_net_worth(self):
        """Liabilities balance should subtract from net worth."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            accounts={"checking": AccountInfo(balance=500_000, account_type="checking")},
            liabilities=[
                LiabilityData(
                    id="loan",
                    name="Loan",
                    principal_balance=200_000,
                    interest_rate=0.05,
                    monthly_payment=1_073.64,
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Net worth = liquid_assets - liabilities_balance
        assert snap.liabilities_balance > 0
        assert snap.net_worth < 500_000  # reduced by remaining liability

    def test_liability_with_offset_account(self):
        """Offset account should reduce interest paid on the liability."""
        principal = 200_000.0
        rate = 0.06
        term = 360
        monthly_pmt = calculate_fixed_payment(principal, rate, term)

        # Without offset
        plan_no_offset = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            liabilities=[
                LiabilityData(
                    id="mortgage",
                    name="Mortgage",
                    principal_balance=principal,
                    interest_rate=rate,
                    term_months=term,
                    monthly_payment=monthly_pmt,
                ),
            ],
        )

        # With offset — 50k in savings reduces effective balance for interest
        plan_with_offset = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            accounts={"savings": AccountInfo(balance=50_000, account_type="savings")},
            liabilities=[
                LiabilityData(
                    id="mortgage",
                    name="Mortgage",
                    principal_balance=principal,
                    interest_rate=rate,
                    term_months=term,
                    monthly_payment=monthly_pmt,
                    offset_account_id="savings",
                ),
            ],
        )

        result_no = run_simulation(plan_no_offset)
        result_yes = run_simulation(plan_with_offset)

        # With offset, more principal is paid -> lower remaining balance after year 1
        assert result_yes.yearly_snapshots[0].liabilities_balance < result_no.yearly_snapshots[0].liabilities_balance

    def test_liability_linked_asset_costs(self):
        """Property tax + maintenance from linked asset should reduce net cash."""
        plan_no_costs = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=100_000, withholding_percent=0.0),
            ],
            real_assets=[
                RealAssetData(
                    id="house", name="House", current_value=400_000,
                    annual_property_tax=0, annual_maintenance=0,
                ),
            ],
            liabilities=[
                LiabilityData(
                    id="mortgage", name="Mortgage",
                    principal_balance=300_000, interest_rate=0.05,
                    monthly_payment=1_610.46,
                    linked_asset_id="house",
                ),
            ],
        )
        plan_with_costs = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=100_000, withholding_percent=0.0),
            ],
            real_assets=[
                RealAssetData(
                    id="house", name="House", current_value=400_000,
                    annual_property_tax=4_000, annual_maintenance=2_000,
                ),
            ],
            liabilities=[
                LiabilityData(
                    id="mortgage", name="Mortgage",
                    principal_balance=300_000, interest_rate=0.05,
                    monthly_payment=1_610.46,
                    linked_asset_id="house",
                ),
            ],
        )
        snap_no = run_simulation(plan_no_costs).yearly_snapshots[0]
        snap_yes = run_simulation(plan_with_costs).yearly_snapshots[0]
        # With property tax + maintenance, net cash should be ~$6000 lower
        assert abs((snap_no.net_cash_flow - snap_yes.net_cash_flow) - 6_000) < 1.0

    def test_no_liabilities_unchanged(self):
        """Plans without liabilities should behave exactly as before."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            accounts={"checking": AccountInfo(balance=100_000, account_type="checking")},
        )
        result = run_simulation(plan)
        for snap in result.yearly_snapshots:
            assert snap.liabilities_balance == 0.0


# ---------------------------------------------------------------------------
# Asset carrying costs (30.2.1)
# ---------------------------------------------------------------------------


class TestAssetCarryingCosts:
    def test_percentage_carrying_costs_use_start_of_year_value(self):
        """Percentage tax, upkeep, and insurance use the opening asset value."""
        plan = minimal_plan(
            start_year=2025, birth_year=1990, life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=100_000,
                           withholding_percent=0.0),
            ],
            real_assets=[
                RealAssetData(
                    id="house", name="House", current_value=100_000,
                    annual_appreciation_rate=0.10,
                    property_tax_rate=0.01,
                    maintenance_rate=0.02,
                    insurance_rate=0.03,
                ),
            ],
        )

        first = run_simulation(plan).yearly_snapshots[0]

        assert first.real_assets_value == pytest.approx(110_000)
        assert first.expenses == pytest.approx(6_000)
        carrying_costs = [
            item.amount
            for item in first.cash_flow.expenses
            if "property tax & upkeep" in item.name
        ]
        assert carrying_costs == pytest.approx([6_000])

    def test_scheduled_sale_pays_linked_debt_and_deposits_net_proceeds(self):
        """A scheduled sale converts the asset to cash without changing net worth."""
        plan = minimal_plan(
            start_year=2025, birth_year=1990, life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            real_assets=[
                RealAssetData(
                    id="car", name="Car", current_value=100_000,
                    annual_appreciation_rate=0.0,
                    property_tax_rate=0.01,
                    sale_year=2026,
                    sale_month=1,
                    liquidation_target_account_id="checking",
                ),
            ],
            liabilities=[
                LiabilityData(
                    id="car_loan", name="Car Loan",
                    principal_balance=30_000, interest_rate=0.0,
                    monthly_payment=0.0, linked_asset_id="car",
                ),
            ],
        )

        result = run_simulation(plan)
        before_sale = result.yearly_snapshots[0]
        sold = result.yearly_snapshots[1]

        assert before_sale.net_worth == pytest.approx(69_000)  # the unfunded property tax remains owed
        assert sold.real_assets_value == 0
        assert sold.liabilities_balance == 0
        assert sold.accounts["checking"] == pytest.approx(70_000)
        assert sold.unfunded_expenses == pytest.approx(1_000)
        assert sold.net_worth == pytest.approx(before_sale.net_worth)
        assert not any(
            "property tax & upkeep" in item.name
            for item in sold.cash_flow.expenses
        )

    def test_carrying_costs_no_liability(self):
        """Asset with property tax and NO liability should reduce net_cash."""
        plan = minimal_plan(
            start_year=2025, birth_year=1990, life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=100_000,
                           withholding_percent=0.0),
            ],
            real_assets=[
                RealAssetData(id="cabin", name="Cabin", current_value=200_000,
                              annual_appreciation_rate=0.0,
                              annual_property_tax=8_000,
                              annual_maintenance=2_000),
            ],
        )
        plan_none = minimal_plan(
            start_year=2025, birth_year=1990, life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=100_000,
                           withholding_percent=0.0),
            ],
        )
        result = run_simulation(plan)
        result_none = run_simulation(plan_none)
        # Year 0: inflation_factor=1.0, costs = 10k
        diff_0 = result_none.yearly_snapshots[0].net_cash_flow - result.yearly_snapshots[0].net_cash_flow
        assert abs(diff_0 - 10_000) < 1.0
        # Year 1: inflation_factor=1.03, costs = 10.3k
        diff_1 = result_none.yearly_snapshots[1].net_cash_flow - result.yearly_snapshots[1].net_cash_flow
        assert abs(diff_1 - 10_300) < 1.0
        # Expenses snapshot includes asset carrying costs
        assert result.yearly_snapshots[0].expenses > 0

    def test_carrying_costs_continue_after_mortgage_payoff(self):
        """Carrying costs must continue after a short mortgage is paid off."""
        plan = minimal_plan(
            start_year=2025, birth_year=1990, life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=200_000,
                           withholding_percent=0.0),
            ],
            real_assets=[
                RealAssetData(id="house", name="House", current_value=400_000,
                              annual_appreciation_rate=0.0,
                              annual_property_tax=5_000,
                              annual_maintenance=3_000),
            ],
            liabilities=[
                LiabilityData(id="mortgage", name="Mortgage",
                              principal_balance=10_000, interest_rate=0.05,
                              monthly_payment=10_000, linked_asset_id="house"),
            ],
        )
        result = run_simulation(plan)
        snap5 = result.yearly_snapshots[5]
        cost_items = [e for e in snap5.cash_flow.expenses
                      if "property tax" in e.name.lower()]
        assert len(cost_items) == 1
        assert abs(cost_items[0].amount - 8_000) < 1.0

    def test_auto_liquidated_asset_stops_carrying_costs(self):
        """An auto-liquidated asset should stop incurring carrying costs."""
        plan = minimal_plan(
            start_year=2025, birth_year=1990, life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(id="big_exp", name="Big Expense",
                            annual_amount=50_000, inflation_linked=False,
                            specific_funding_source_id="checking"),
            ],
            accounts={
                "checking": AccountInfo(balance=10_000,
                                        account_type="checking"),
            },
            real_assets=[
                RealAssetData(id="land", name="Vacant Land",
                              current_value=100_000,
                              annual_appreciation_rate=0.0,
                              annual_property_tax=3_000,
                              annual_maintenance=1_000,
                              auto_liquidate_on_depletion=True,
                              liquidation_target_account_id="checking"),
            ],
        )
        result = run_simulation(plan)
        liquidation_year_idx = None
        for i, snap in enumerate(result.yearly_snapshots):
            if snap.real_assets_value == 0.0:
                liquidation_year_idx = i
                break
        assert liquidation_year_idx is not None, \
            "Land should have been auto-liquidated"
        later = liquidation_year_idx + 1
        for snap in result.yearly_snapshots[later:later + 3]:
            cost_items = [e for e in snap.cash_flow.expenses
                          if "property tax" in e.name.lower()]
            assert len(cost_items) == 0, \
                f"Carrying costs should stop after liquidation (year {snap.year})"


# ---------------------------------------------------------------------------
# RMD integration
# ---------------------------------------------------------------------------


class TestRMDIntegration:
    def test_rmd_withdrawn_at_age_73(self):
        """Traditional IRA should have RMD withdrawn starting at age 73."""
        # birth_year=1950, start_year=2023 → age 73. life_expectancy=80 → end 2030.
        plan = minimal_plan(
            birth_year=1950,
            start_year=2023,
            life_expectancy=80,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "ira": AccountInfo(balance=500_000, account_type="traditional_ira"),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Age 73, divisor 26.5 → RMD = 500_000 / 26.5 ≈ 18_867.92
        expected_rmd = 500_000 / 26.5
        # IRA balance should decrease by RMD amount
        assert abs(snap.accounts["ira"] - (500_000 - expected_rmd)) < 1.0
        # RMD flows into net cash and then surplus → checking gets the after-tax amount
        assert snap.accounts["checking"] > 0

    def test_rmd_withholding_reduces_spendable_distribution(self):
        plan = minimal_plan(
            birth_year=1950,
            start_year=2023,
            life_expectancy=74,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "ira": AccountInfo(balance=500_000, account_type="traditional_ira"),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.0,
                "capital_gains_tax_rate": 0.0,
                "tax_deferred_withholding_rate": 0.20,
                "settlement_lag_years": 1,
            },
        )

        snap = run_simulation(plan).yearly_snapshots[0]
        expected_rmd = 500_000 / 26.5

        assert snap.cash_flow.tax_withheld == pytest.approx(expected_rmd * 0.20)
        assert snap.cash_flow.tax_delta == pytest.approx(expected_rmd * 0.20)
        assert snap.accounts["checking"] == pytest.approx(expected_rmd * 0.80)

    def test_no_rmd_below_age_73(self):
        """Traditional IRA should NOT have RMD if owner is under 73."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "ira": AccountInfo(balance=500_000, account_type="traditional_ira"),
            },
        )
        result = run_simulation(plan)
        # Age 35, well below 73 — no RMD, balance unchanged
        assert result.yearly_snapshots[0].accounts["ira"] == 500_000

    def test_rmd_on_401k(self):
        """Traditional 401k accounts should also trigger RMDs at age 73+."""
        plan = minimal_plan(
            birth_year=1950,
            start_year=2025,
            life_expectancy=80,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "k401": AccountInfo(balance=300_000, account_type="traditional_401k"),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Age 75, divisor 24.6 → RMD = 300_000 / 24.6 ≈ 12_195.12
        expected_rmd = 300_000 / 24.6
        assert abs(snap.accounts["k401"] - (300_000 - expected_rmd)) < 1.0

    def test_inherited_ira_rmd_edb(self):
        """EDB inherited IRA should take RMDs using IRS Single Life Table."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "inherited": AccountInfo(
                    balance=200_000,
                    account_type="traditional_ira",
                    inherited_year=2023,
                    beneficiary_type="edb",
                ),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # beneficiary_age = 2025 - 1990 = 35, Single Life Table divisor = 50.5
        # RMD = 200_000 / 50.5 ≈ 3960.40
        expected_rmd = 200_000 / 50.5
        assert abs(snap.accounts["inherited"] - (200_000 - expected_rmd)) < 1.0

    def test_inherited_roth_rmd_is_not_taxable_income(self):
        """Inherited Roth RMDs distribute cash but do not create ordinary tax."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "inherited_roth": AccountInfo(
                    balance=200_000,
                    account_type="roth_ira",
                    inherited_year=2023,
                    beneficiary_type="edb",
                ),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]

        expected_rmd = 200_000 / 50.5
        assert snap.accounts["inherited_roth"] == pytest.approx(200_000 - expected_rmd, abs=1.0)
        assert snap.accounts["checking"] == pytest.approx(expected_rmd, abs=1.0)
        assert snap.taxes == 0.0

    def test_inherited_ira_rmd_non_edb_no_annual(self):
        """Non-EDB inherited IRA: no annual RMDs, full distribution at year 10."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "inherited": AccountInfo(
                    balance=200_000,
                    account_type="traditional_ira",
                    inherited_year=2023,
                    beneficiary_type="non_edb",
                ),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        # Year 1 (2025): no RMD for non-EDB
        snap = result.yearly_snapshots[0]
        assert snap.accounts["inherited"] == pytest.approx(200_000, abs=1.0)

    def test_roth_ira_no_rmd(self):
        """Roth IRA should NOT trigger RMDs (not in RMD account types)."""
        plan = minimal_plan(
            birth_year=1950,
            start_year=2023,
            life_expectancy=80,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "roth": AccountInfo(balance=500_000, account_type="roth_ira"),
            },
        )
        result = run_simulation(plan)
        # No RMD on Roth — balance unchanged
        assert result.yearly_snapshots[0].accounts["roth"] == 500_000

    def test_rmd_included_in_tax(self):
        """RMD income should be passed to the tax engine and increase taxes."""
        # Compare taxes with and without RMD-eligible accounts
        base_plan = minimal_plan(
            birth_year=1950,
            start_year=2023,
            life_expectancy=76,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            income_streams=[IncomeData(id="ss", name="SS", annual_amount=30_000)],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        rmd_plan = minimal_plan(
            birth_year=1950,
            start_year=2023,
            life_expectancy=76,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            income_streams=[IncomeData(id="ss", name="SS", annual_amount=30_000)],
            accounts={
                "checking": AccountInfo(balance=0, account_type="checking"),
                "ira": AccountInfo(balance=500_000, account_type="traditional_ira"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        base_result = run_simulation(base_plan)
        rmd_result = run_simulation(rmd_plan)
        # Plan with RMD should pay more taxes due to rmd_income
        assert rmd_result.yearly_snapshots[0].taxes > base_result.yearly_snapshots[0].taxes

    def test_spouse_owned_ira_uses_spouse_age_for_rmd(self):
        """Spouse-owned traditional IRA should use spouse's age/birth_year for RMD.

        Spouse born 1950 (RMD start age 72), holder born 1955 (RMD start age 73).
        In 2025: spouse is 75 (past RMD age), holder is 70 (below theirs).
        Spouse-owned IRA should take RMD; holder-owned IRA should not.
        """
        plan = minimal_plan(
            birth_year=1955,
            start_year=2025,
            life_expectancy=90,
            spouse_birth_year=1950,
            spouse_life_expectancy=90,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "spouse_ira": AccountInfo(
                    balance=500_000, account_type="traditional_ira", owner="spouse",
                ),
                "holder_ira": AccountInfo(
                    balance=500_000, account_type="traditional_ira", owner="self",
                ),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]  # year=2025

        # Spouse age = 2025 - 1950 = 75, divisor 24.6 → RMD = 500_000 / 24.6
        expected_spouse_rmd = 500_000 / 24.6
        assert abs(snap.accounts["spouse_ira"] - (500_000 - expected_spouse_rmd)) < 1.0

        # Holder age = 2025 - 1955 = 70, below RMD start age (73) → no RMD
        assert snap.accounts["holder_ira"] == 500_000

    def test_holder_owned_ira_unaffected_by_spouse(self):
        """Holder-owned IRA uses holder's age regardless of spouse birth year."""
        plan = minimal_plan(
            birth_year=1950,
            start_year=2025,
            life_expectancy=80,
            spouse_birth_year=1970,  # younger spouse
            spouse_life_expectancy=90,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "holder_ira": AccountInfo(
                    balance=300_000, account_type="traditional_ira", owner="self",
                ),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Holder age = 75, divisor 24.6 → same as non-spouse test
        expected_rmd = 300_000 / 24.6
        assert abs(snap.accounts["holder_ira"] - (300_000 - expected_rmd)) < 1.0

    def test_joint_owned_account_uses_holder_age(self):
        """Joint-owned accounts use the plan holder's age for RMDs.

        Joint RMD attribution is not owner-split in this engine (see 31.3.3).
        """
        plan = minimal_plan(
            birth_year=1955,
            start_year=2025,
            life_expectancy=90,
            spouse_birth_year=1950,
            spouse_life_expectancy=90,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "joint_ira": AccountInfo(
                    balance=500_000, account_type="traditional_ira", owner="joint",
                ),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Holder age = 70, below RMD start age (73 for birth_year=1955) → no RMD
        assert snap.accounts["joint_ira"] == 500_000

    def test_spouse_accounts_use_survivor_age_after_partner_death(self):
        """The death year owes the decedent's RMD; survivor age applies from the next January.

        IRS Pub. 590-B, "Year of owner's death": a spouse who becomes owner in
        the year of death takes the deceased owner's RMD for that year, not one
        figured on their own life expectancy.
        """
        # Spouse dies in 2025 (born 1950, life_expectancy=75 → 1950+75=2025).
        # Holder born 1955, start year 2024 (first year before spouse death).
        plan = minimal_plan(
            birth_year=1955,
            start_year=2024,
            life_expectancy=90,
            spouse_birth_year=1950,
            spouse_life_expectancy=75,  # spouse dies at year 2025
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            accounts={
                "spouse_ira": AccountInfo(
                    balance=500_000, account_type="traditional_ira", owner="spouse",
                ),
                "checking": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        snaps = {s.year: s for s in run_simulation(plan).yearly_snapshots}

        # 2024: spouse age 74 (start age 72), Uniform Lifetime divisor 25.5.
        # 500,000 / 25.5 = 19,607.84 → 480,392.16
        assert snaps[2024].accounts["spouse_ira"] == pytest.approx(480_392.16, abs=0.01)

        # 2025: death year, after the spouse's RBD (April 1, 2023). The
        # decedent's RMD at age 75, divisor 24.6:
        # 480,392.16 / 24.6 = 19,528.14 → 460,864.02
        assert snaps[2025].accounts["spouse_ira"] == pytest.approx(460_864.02, abs=0.01)

        # 2026-2027: survivor ages 71-72, below their start age 73 → no RMD.
        assert snaps[2027].accounts["spouse_ira"] == pytest.approx(460_864.02, abs=0.01)

        # 2028: survivor age 73 → RMD on the survivor's own divisor (26.5).
        # 460,864.02 / 26.5 = 17,391.09 → 443,472.93
        assert snaps[2028].accounts["spouse_ira"] == pytest.approx(443_472.93, abs=0.01)

    def test_partner_death_year_rmd_uses_decedent_age_on_joint_return(self):
        """Legacy death year takes the decedent's RMD, not the survivor's."""
        plan = minimal_plan(
            birth_year=1960, birth_month=6,
            filing_status="married_filing_jointly", life_expectancy=75, start_year=2026,
            spouse_birth_year=1945, spouse_birth_month=6, spouse_life_expectancy=82,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
            accounts={
                "sira": AccountInfo(balance=1_000_000, account_type="traditional_ira", owner="spouse"),
                "chk": AccountInfo(balance=0, account_type="checking"),
            },
        )
        snaps = {s.year: s for s in run_simulation(plan).yearly_snapshots}
        # 2026, spouse 81: 1,000,000 / 19.4 = 51,546.39
        assert snaps[2026].gross_income == pytest.approx(51_546.39, abs=0.01)
        # 2027 death year, spouse would be 82: 948,453.61 / 18.5 = 51,267.76
        assert snaps[2027].gross_income == pytest.approx(51_267.76, abs=0.01)
        # 2028: survivor 68, below their start age 75 → no RMD.
        assert snaps[2028].gross_income == pytest.approx(0.0, abs=0.01)

    def test_partner_death_before_rbd_owes_no_death_year_rmd(self):
        """Death before the required beginning date owes no RMD that year.

        IRS Pub. 590-B: "there is no required minimum distribution in the year
        of the owner's death" if the owner died before the RBD. The survivor,
        already past RMD age, owes none as owner until the following year.
        """
        # Spouse born March 1953 (start age 73, RBD April 1, 2027) dies
        # March 1, 2027 (life_expectancy 74): before the RBD.
        plan = minimal_plan(
            birth_year=1950, start_year=2026, life_expectancy=90,
            spouse_birth_year=1953, spouse_birth_month=3, spouse_life_expectancy=74,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
            accounts={
                "sira": AccountInfo(balance=500_000, account_type="traditional_ira", owner="spouse"),
                "chk": AccountInfo(balance=0, account_type="checking"),
            },
        )
        snaps = {s.year: s for s in run_simulation(plan).yearly_snapshots}
        # 2026: spouse 73, first RMD year: 500,000 / 26.5 = 18,867.92 → 481,132.08
        assert snaps[2026].accounts["sira"] == pytest.approx(481_132.08, abs=0.01)
        # 2027: died before the RBD → no RMD (survivor age 77 is not used).
        assert snaps[2027].accounts["sira"] == pytest.approx(481_132.08, abs=0.01)
        # 2028: survivor 78, divisor 22.0: 481,132.08 / 22.0 = 21,869.64 → 459,262.44
        assert snaps[2028].accounts["sira"] == pytest.approx(459_262.44, abs=0.01)


# ---------------------------------------------------------------------------
# Auto-liquidation of real assets
# ---------------------------------------------------------------------------


class TestAutoLiquidation:
    def test_no_liquidation_when_positive_liquid_nw(self):
        """Assets should NOT be liquidated when liquid net worth is positive."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            accounts={"checking": AccountInfo(balance=100_000, account_type="checking")},
            real_assets=[
                RealAssetData(
                    id="house", name="House", current_value=300_000,
                    annual_appreciation_rate=0.0,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
            ],
        )
        result = run_simulation(plan)
        # House should still be in real_assets_value throughout
        for snap in result.yearly_snapshots[:5]:
            assert snap.real_assets_value == 300_000

    def test_liquidation_on_negative_liquid_nw(self):
        """Asset should be sold when liquid accounts go negative."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(
                    id="big_exp", name="Big Expense", annual_amount=50_000,
                    inflation_linked=False,
                    specific_funding_source_id="checking",
                ),
            ],
            accounts={"checking": AccountInfo(balance=10_000, account_type="checking")},
            real_assets=[
                RealAssetData(
                    id="land", name="Land", current_value=200_000,
                    annual_appreciation_rate=0.0,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Specific funding source draws 50k from 10k checking → -40k liquid nw
        # Liquidation should sell land (200k) and deposit to checking
        # checking = 10k - 50k + 200k = 160k
        assert snap.real_assets_value == 0.0  # land sold
        assert snap.accounts["checking"] > 0  # checking restored

    def test_non_primary_liquidated_first(self):
        """Non-primary assets should be sold before primary residence."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(
                    id="exp", name="Expense", annual_amount=80_000,
                    inflation_linked=False,
                    specific_funding_source_id="checking",
                ),
            ],
            accounts={"checking": AccountInfo(balance=10_000, account_type="checking")},
            real_assets=[
                RealAssetData(
                    id="house", name="Primary", current_value=400_000,
                    annual_appreciation_rate=0.0,
                    is_primary_residence=True,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
                RealAssetData(
                    id="cabin", name="Cabin", current_value=150_000,
                    annual_appreciation_rate=0.0,
                    is_primary_residence=False,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Deficit = 80k - 10k = -70k. Cabin (150k) covers it.
        # Primary should NOT be sold.
        assert snap.real_assets_value == 400_000  # only primary remains

    def test_primary_residence_exclusion_single(self):
        """Single filer gets $250k primary residence capital gains exclusion."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            filing_status="single",
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(
                    id="exp", name="Expense", annual_amount=600_000,
                    inflation_linked=False,
                    specific_funding_source_id="checking",
                ),
            ],
            accounts={"checking": AccountInfo(balance=10_000, account_type="checking")},
            real_assets=[
                RealAssetData(
                    id="house", name="Primary", current_value=200_000,
                    annual_appreciation_rate=1.5,  # appreciates to 500k
                    is_primary_residence=True,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # House appreciates: 200k * (1 + 1.5) = 500k sale price
        # Raw gain = 500k - 200k = 300k
        # Primary exclusion (single) = 250k
        # Taxable gain = 300k - 250k = 50k
        assert snap.real_assets_value == 0.0  # house sold

    def test_primary_residence_exclusion_married(self):
        """Married filing jointly gets $500k primary residence exclusion."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            filing_status="married_filing_jointly",
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(
                    id="exp", name="Expense", annual_amount=600_000,
                    inflation_linked=False,
                    specific_funding_source_id="checking",
                ),
            ],
            accounts={"checking": AccountInfo(balance=10_000, account_type="checking")},
            real_assets=[
                RealAssetData(
                    id="house", name="Primary", current_value=200_000,
                    annual_appreciation_rate=1.5,  # 200k → 500k after appreciation
                    is_primary_residence=True,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Raw gain = 500k - 200k = 300k, exclusion = 500k → taxable = 0
        assert snap.real_assets_value == 0.0

    def test_linked_liability_payoff(self):
        """Linked mortgage should be paid off from sale proceeds."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(
                    id="exp", name="Expense", annual_amount=50_000,
                    inflation_linked=False,
                    specific_funding_source_id="checking",
                ),
            ],
            accounts={"checking": AccountInfo(balance=5_000, account_type="checking")},
            real_assets=[
                RealAssetData(
                    id="house", name="House", current_value=300_000,
                    annual_appreciation_rate=0.0,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
            ],
            liabilities=[
                LiabilityData(
                    id="mortgage", name="Mortgage",
                    principal_balance=100_000, interest_rate=0.05,
                    monthly_payment=536.82,
                    linked_asset_id="house",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # House sold for 300k, mortgage ~100k paid off, net ~200k deposited
        assert snap.real_assets_value == 0.0
        assert snap.liabilities_balance < 1.0  # mortgage paid off
        # Net proceeds = 300k - ~100k mortgage = ~200k, plus original 5k - 50k expense
        assert snap.accounts["checking"] > 100_000

    def test_stops_when_liquid_nw_restored(self):
        """Should only liquidate enough assets to restore liquid net worth >= 0."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(
                    id="exp", name="Expense", annual_amount=60_000,
                    inflation_linked=False,
                    specific_funding_source_id="checking",
                ),
            ],
            accounts={"checking": AccountInfo(balance=10_000, account_type="checking")},
            real_assets=[
                RealAssetData(
                    id="lot1", name="Lot 1", current_value=100_000,
                    annual_appreciation_rate=0.0,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
                RealAssetData(
                    id="lot2", name="Lot 2", current_value=100_000,
                    annual_appreciation_rate=0.0,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Deficit = 60k - 10k = -50k. First lot (100k) covers it.
        # Second lot should NOT be sold.
        assert snap.real_assets_value == 100_000  # one lot remains

    def test_capital_gains_tracked(self):
        """Capital gains from liquidation should be tracked for tax purposes."""
        # Use a non-primary asset so no exclusion applies
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            filing_status="single",
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            expenses=[
                ExpenseData(
                    id="exp", name="Expense", annual_amount=200_000,
                    inflation_linked=False,
                    specific_funding_source_id="checking",
                ),
            ],
            accounts={"checking": AccountInfo(balance=10_000, account_type="checking")},
            real_assets=[
                RealAssetData(
                    id="rental", name="Rental", current_value=100_000,
                    annual_appreciation_rate=1.0,  # 100k → 200k
                    is_primary_residence=False,
                    auto_liquidate_on_depletion=True,
                    liquidation_target_account_id="checking",
                ),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        # Asset appreciates 100k → 200k, sold for 200k
        # Capital gain = 200k - 100k = 100k, no exclusion
        # The tax bill should reflect capital gains (taxes > 0 even with no income)
        assert snap.taxes > 0
        assert snap.real_assets_value == 0.0


# ---------------------------------------------------------------------------
# Tax settlement timing
# ---------------------------------------------------------------------------


class TestTaxSettlementTiming:
    def test_one_year_lag_applies_current_tax_balance_next_year(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=2000,
            life_expectancy=28,
            income_streams=[
                IncomeData(
                    id="salary",
                    name="Salary",
                    annual_amount=100_000,
                    withholding_percent=0.25,
                ),
            ],
            accounts={"cash": AccountInfo(balance=0, account_type="savings")},
            priorities=[PriorityData(priority_rank=1, target_account_id="cash")],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.30,
                "capital_gains_tax_rate": 0.15,
                "settlement_lag_years": 1,
            },
        )

        first, second = run_simulation(plan).yearly_snapshots

        assert first.taxes == pytest.approx(30_000)
        assert first.cash_flow.tax_delta == pytest.approx(-5_000)
        assert first.accounts["cash"] == pytest.approx(75_000)
        assert second.accounts["cash"] == pytest.approx(145_000)

    def test_lagged_capital_gains_tax_does_not_force_same_year_drawdown(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=1966,
            life_expectancy=62,
            expenses=[
                ExpenseData(
                    id="living",
                    name="Living",
                    annual_amount=80_000,
                    inflation_linked=False,
                ),
            ],
            accounts={
                "taxable": AccountInfo(
                    balance=500_000,
                    account_type="taxable_brokerage",
                    cost_basis=250_000,
                ),
            },
            drawdown_order=[
                DrawdownEntryData(rank=1, source_account_id="taxable"),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.30,
                "capital_gains_tax_rate": 0.15,
                "settlement_lag_years": 1,
            },
        )

        first, second = run_simulation(plan).yearly_snapshots

        assert sum(item.amount for item in first.cash_flow.drawdowns) == pytest.approx(80_000)
        assert first.capital_gains_tax == pytest.approx(6_000)
        assert first.cash_flow.tax_delta == pytest.approx(-6_000)
        assert sum(item.amount for item in second.cash_flow.drawdowns) == pytest.approx(86_000)

    def test_drawdown_withholding_grosses_up_distribution_and_tax_balance(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=1966,
            life_expectancy=62,
            expenses=[
                ExpenseData(
                    id="living",
                    name="Living",
                    annual_amount=90_000,
                    inflation_linked=False,
                ),
            ],
            accounts={
                "taxable": AccountInfo(
                    balance=200_000,
                    account_type="taxable_brokerage",
                    cost_basis=100_000,
                ),
            },
            drawdown_order=[
                DrawdownEntryData(rank=1, source_account_id="taxable"),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.30,
                "capital_gains_tax_rate": 0.15,
                "taxable_withholding_rate": 0.10,
                "settlement_lag_years": 1,
            },
        )

        first = run_simulation(plan).yearly_snapshots[0]

        expected_gross = 90_000 / (1.0 - 0.10 * 0.50)
        expected_gain = expected_gross * 0.50
        expected_withholding = expected_gain * 0.10
        expected_tax = expected_gain * 0.15

        assert sum(item.amount for item in first.cash_flow.drawdowns) == pytest.approx(
            expected_gross,
        )
        assert first.cash_flow.tax_withheld == pytest.approx(expected_withholding)
        assert first.cash_flow.tax_delta == pytest.approx(
            expected_withholding - expected_tax,
        )
        assert first.accounts["taxable"] == pytest.approx(200_000 - expected_gross)


# ---------------------------------------------------------------------------
# Post-waterfall incremental tax (11.1.1 regression)
# ---------------------------------------------------------------------------


class TestPostWaterfallTax:
    """Incremental tax from Roth conversions/capital gains must be deducted."""

    def test_roth_conversion_tax_deducted_from_accounts(self):
        """Roth conversion tax should be drawn from accounts, not ignored.

        Regression: post-waterfall tax was computed but never subtracted
        from any account.
        """
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            filing_status="single",
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=50_000),
            ],
            accounts={
                "trad": AccountInfo(balance=100_000, account_type="traditional_ira"),
                "roth": AccountInfo(balance=0, account_type="roth_ira"),
                "checking": AccountInfo(balance=50_000, account_type="checking"),
            },
            priorities=[
                PriorityData(
                    priority_rank=1,
                    priority_type="roth_conversion",
                    source_account_id="trad",
                    target_account_id="roth",
                    max_annual_amount=100_000,
                ),
            ],
            drawdown_order=[
                DrawdownEntryData(rank=1, source_account_id="checking"),
            ],
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]

        # Roth conversion adds to taxable income → taxes increase
        assert snap.taxes > 0

        # Traditional should be emptied (100k converted)
        assert snap.accounts["trad"] == 0.0
        # Roth should receive the full conversion
        assert snap.accounts["roth"] == 100_000

        # The incremental tax must be withdrawn from checking.
        # Without the fix, checking would still have the full surplus.
        # With the fix, checking is reduced by the incremental tax.
        # Tax on 50k income alone vs 50k + 100k conversion differs.
        # The incremental tax should make checking < what it would be
        # if only base income tax were deducted.

        base_tax = calc_tax(50_000, 0.0, "single").total_tax
        full_tax = calc_tax(50_000, 0.0, "single", roth_conversions=100_000).total_tax
        incremental = full_tax - base_tax
        assert incremental > 0

        # Checking balance should reflect the incremental tax drawdown.
        # Starting: 50k checking + 50k income - base_tax - expenses(0) = surplus
        # Then incremental tax drawn from checking.
        expected_max_checking = 50_000 + 50_000 - base_tax
        assert snap.accounts["checking"] < expected_max_checking
        # Specifically, it should be reduced by approximately the incremental tax
        assert snap.accounts["checking"] <= expected_max_checking - incremental + 1.0


# ---------------------------------------------------------------------------
# Social Security COLA (29.2.1)
# ---------------------------------------------------------------------------


class TestSocialSecurityCOLA:
    """SS streams with growth_rate=0 should receive automatic inflation COLA."""

    def test_ss_cola_with_inflation(self):
        """SS benefit should grow with cumulative inflation, not stay flat.

        Plan: 3% inflation, SS $30k starting at age 45 (10 years after sim
        start for birth_year=1990, start_year=2025).  First SS year's amount
        should equal 30_000 * 1.03**10, and subsequent years keep growing ~3%.
        """
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
            milestones=[
                MilestoneData(id="claim_ss", name="Claim SS", trigger_type="age", trigger_value=45),
            ],
            income_streams=[
                IncomeData(
                    id="ss", name="Social Security", annual_amount=30_000,
                    start_milestone_id="claim_ss",
                    is_social_security=True,
                    growth_rate=None,
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)

        # Age 45 = year 2035, index 10.  Inflation compounds 10 times
        # before income starts (step 11 inflates *after* each year's snapshot).
        # Year 0 (2025): inflation_factor starts at 1.0, inflated to 1.03 at end
        # Year 9 (2034): inflation_factor = 1.03^9 at start, inflated to 1.03^10
        # Year 10 (2035): inflation_factor = 1.03^10 at start -> SS amount uses it
        snap_first_ss = result.yearly_snapshots[10]
        expected_first = 30_000 * 1.03 ** 10
        assert abs(snap_first_ss.gross_income - expected_first) < 1.0, (
            f"First SS year: expected ~{expected_first:.2f}, got {snap_first_ss.gross_income:.2f}"
        )

        # Next year should grow by another ~3%
        snap_second_ss = result.yearly_snapshots[11]
        expected_second = 30_000 * 1.03 ** 11
        assert abs(snap_second_ss.gross_income - expected_second) < 1.0, (
            f"Second SS year: expected ~{expected_second:.2f}, got {snap_second_ss.gross_income:.2f}"
        )

    def test_ss_explicit_growth_rate_honored(self):
        """SS stream with an explicit non-zero growth_rate should use compound
        formula, not the inflation COLA path."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(
                    id="ss", name="Social Security", annual_amount=30_000,
                    is_social_security=True,
                    growth_rate=0.05,  # explicit override
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)

        # Year 0: 30_000 (growth_rate=5%, years_elapsed=0 -> factor 1.0)
        assert abs(result.yearly_snapshots[0].gross_income - 30_000) < 1.0
        # Year 1: 30_000 * 1.05
        assert abs(result.yearly_snapshots[1].gross_income - 30_000 * 1.05) < 1.0
        # NOT 30_000 * 1.03 (the inflation path)

    def test_non_ss_zero_growth_stays_flat(self):
        """Non-SS stream with growth_rate=0 must NOT receive inflation COLA."""
        plan = minimal_plan(
            birth_year=1990,
            start_year=2025,
            life_expectancy=92,
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(
                    id="pension", name="Pension", annual_amount=40_000,
                    is_social_security=False,
                    growth_rate=0.0,
                ),
            ],
            accounts={"checking": AccountInfo(balance=0, account_type="checking")},
            priorities=[PriorityData(priority_rank=1, target_account_id="checking")],
        )
        result = run_simulation(plan)

        # Should stay flat at 40_000 every year (no COLA leak)
        for i in range(5):
            snap = result.yearly_snapshots[i]
            assert abs(snap.gross_income - 40_000) < 1.0, (
                f"Year {i}: non-SS income should be 40000, got {snap.gross_income:.2f}"
            )


# ---------------------------------------------------------------------------
# Default cash sink (30.1.2)
# ---------------------------------------------------------------------------


class TestDefaultCashSink:
    """Leftover surplus after waterfall priorities should be banked in a
    default cash sink account (checking → savings → taxable_brokerage)."""

    def test_zero_priorities_surplus_banks_in_checking(self):
        """Income > expenses with ZERO priorities → checking balance rises."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000),
            ],
            accounts={
                "chk": AccountInfo(balance=0, account_type="checking"),
            },
            priorities=[],
            drawdown_order=[],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )
        result = run_simulation(plan)
        snap0 = result.yearly_snapshots[0]
        # After-tax surplus should land in checking.  With ~$100k single
        # income, federal + FICA taxes are ~$21k, so checking should be ~$79k.
        chk_balance = snap0.accounts.get("chk", 0.0)
        assert chk_balance > 70_000, (
            f"Checking should receive surplus, got {chk_balance:.2f}"
        )
        # Net worth must equal checking balance (only liquid account)
        assert abs(snap0.net_worth - chk_balance) < 1.0

    def test_capped_priority_remainder_goes_to_sink(self):
        """Priority capped at $5k with large surplus → $5k to target, rest to sink."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000),
            ],
            accounts={
                "chk": AccountInfo(balance=0, account_type="checking"),
                "ira": AccountInfo(balance=0, account_type="roth_ira"),
            },
            priorities=[
                PriorityData(
                    priority_rank=1,
                    target_account_id="ira",
                    max_annual_amount=5_000,
                ),
            ],
            drawdown_order=[],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )
        result = run_simulation(plan)
        snap0 = result.yearly_snapshots[0]
        ira_balance = snap0.accounts.get("ira", 0.0)
        chk_balance = snap0.accounts.get("chk", 0.0)
        # IRA should receive exactly $5k (the capped priority)
        assert abs(ira_balance - 5_000) < 1.0, (
            f"IRA should be 5000, got {ira_balance:.2f}"
        )
        # Checking should receive the remainder (surplus - 5k - taxes)
        assert chk_balance > 65_000, (
            f"Checking should receive leftover surplus, got {chk_balance:.2f}"
        )
        # Total net worth = ira + checking
        assert abs(snap0.net_worth - (ira_balance + chk_balance)) < 1.0

    def test_no_cash_account_drops_surplus(self):
        """Only retirement accounts (no cash-like) → unchanged behavior, no crash."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000),
            ],
            accounts={
                "ira": AccountInfo(balance=10_000, account_type="traditional_ira"),
            },
            priorities=[],
            drawdown_order=[],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )
        result = run_simulation(plan)
        # Should not crash and IRA balance stays at initial value (no deposits)
        snap0 = result.yearly_snapshots[0]
        ira_balance = snap0.accounts.get("ira", 0.0)
        assert abs(ira_balance - 10_000) < 1.0, (
            f"IRA should be unchanged at 10000, got {ira_balance:.2f}"
        )
        assert result.metadata.success is True

    def test_savings_used_when_no_checking(self):
        """Savings account is chosen as sink when no checking exists."""
        plan = minimal_plan(
            income_streams=[
                IncomeData(id="sal", name="Salary", annual_amount=100_000),
            ],
            accounts={
                "sav": AccountInfo(balance=0, account_type="savings"),
                "ira": AccountInfo(balance=0, account_type="traditional_ira"),
            },
            priorities=[],
            drawdown_order=[],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )
        result = run_simulation(plan)
        snap0 = result.yearly_snapshots[0]
        sav_balance = snap0.accounts.get("sav", 0.0)
        assert sav_balance > 70_000, (
            f"Savings should receive surplus when no checking, got {sav_balance:.2f}"
        )


# ---------------------------------------------------------------------------
# Cash-flow reconciliation (30.3.1)
# ---------------------------------------------------------------------------


class TestCashFlowReconciliation:
    """Verify cash-flow expense reporting matches snapshot totals.

    Strongest identity tested:
        snapshot.expenses == payroll_deductions + sum(cf_expenses amounts)

    payroll_deductions is tracked as a dedicated scalar on CashFlowBreakdown
    (not in the expenses list), so the cf_expenses list covers all non-payroll
    expense components: standard expenses, specific-funded expenses, asset
    carrying costs, liability payments, charitable outflows, and QCDs.

    We also assert that every liability with active payments has a named
    entry in cf_expenses, and every charitable entity with a withdrawal has
    one too.
    """

    def test_cf_expenses_reconcile_with_snapshot(self):
        """sum(cf_expenses) + payroll_deductions == snapshot.expenses for a plan
        that exercises liabilities, charitable giving (DAF), and standard expenses."""
        principal = 200_000.0
        rate = 0.06
        term = 360
        monthly_pmt = calculate_fixed_payment(principal, rate, term)

        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=93,
            income_streams=[
                IncomeData(id="job", name="Salary", annual_amount=120_000, withholding_percent=0.20),
            ],
            expenses=[
                ExpenseData(id="rent", name="Rent", annual_amount=24_000, category="essential"),
                ExpenseData(id="hsa", name="HSA", annual_amount=3_000, is_payroll_deduction=True),
            ],
            accounts={
                "chk": AccountInfo(balance=500_000, account_type="checking"),
            },
            liabilities=[
                LiabilityData(
                    id="mortgage", name="Home Mortgage",
                    principal_balance=principal, interest_rate=rate,
                    term_months=term, monthly_payment=monthly_pmt,
                ),
            ],
            charity_entities=[
                CharityData(id="daf1", name="Community Foundation", entity_type="daf", annual_amount=5_000),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )
        result = run_simulation(plan)

        for snap in result.yearly_snapshots[:5]:  # spot-check first 5 years
            cf = snap.cash_flow
            assert cf is not None, f"Year {snap.year} missing cash_flow"
            cf_sum = sum(e.amount for e in cf.expenses)
            expected = snap.expenses
            assert cf_sum + cf.payroll_deductions == pytest.approx(expected, abs=1.0), (
                f"Year {snap.year}: cf_expenses sum ({cf_sum:.2f}) + "
                f"payroll ({cf.payroll_deductions:.2f}) != snapshot.expenses ({expected:.2f})"
            )

    def test_liability_entries_present_in_cf_expenses(self):
        """Every liability with active payments must appear as a named cf_expenses entry."""
        principal = 50_000.0
        rate = 0.04
        term = 120
        monthly_pmt = calculate_fixed_payment(principal, rate, term)

        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=93,
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=80_000, withholding_percent=0.0),
            ],
            accounts={"chk": AccountInfo(balance=100_000, account_type="checking")},
            liabilities=[
                LiabilityData(
                    id="car", name="Car Loan",
                    principal_balance=principal, interest_rate=rate,
                    term_months=term, monthly_payment=monthly_pmt,
                ),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        expense_names = [e.name for e in snap.cash_flow.expenses]
        assert "Car Loan" in expense_names, (
            f"Liability 'Car Loan' missing from cf_expenses: {expense_names}"
        )
        car_entry = next(e for e in snap.cash_flow.expenses if e.name == "Car Loan")
        assert car_entry.amount > 0
        assert car_entry.category == "essential"

    def test_charitable_entries_present_in_cf_expenses(self):
        """DAF/direct charitable outflows must appear in cf_expenses."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1990,
            life_expectancy=93,
            income_streams=[
                IncomeData(id="job", name="Job", annual_amount=100_000, withholding_percent=0.0),
            ],
            accounts={"chk": AccountInfo(balance=200_000, account_type="checking")},
            charity_entities=[
                CharityData(id="daf1", name="Red Cross DAF", entity_type="daf", annual_amount=10_000),
                CharityData(id="dir1", name="Local Shelter", entity_type="direct", annual_amount=2_000),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        expense_names = [e.name for e in snap.cash_flow.expenses]
        assert "Red Cross DAF" in expense_names
        assert "Local Shelter" in expense_names
        daf_entry = next(e for e in snap.cash_flow.expenses if e.name == "Red Cross DAF")
        assert daf_entry.amount == pytest.approx(10_000, abs=1.0)
        assert daf_entry.category == "discretionary"
        direct_entry = next(e for e in snap.cash_flow.expenses if e.name == "Local Shelter")
        assert direct_entry.amount == pytest.approx(2_000, abs=1.0)

    def test_qcd_entry_present_in_cf_expenses(self):
        """QCD outflow appears in cf_expenses as a discretionary expense."""
        plan = minimal_plan(
            start_year=2025,
            birth_year=1952,  # age 73 in 2025 — RMDs required
            life_expectancy=76,
            income_streams=[
                IncomeData(id="pension", name="Pension", annual_amount=30_000, withholding_percent=0.0),
            ],
            accounts={
                "ira": AccountInfo(balance=500_000, account_type="traditional_ira"),
                "chk": AccountInfo(balance=50_000, account_type="checking"),
            },
            charity_entities=[
                CharityData(id="qcd1", name="Charity QCD", entity_type="qcd", annual_amount=8_000),
            ],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        expense_names = [e.name for e in snap.cash_flow.expenses]
        assert "QCD to charity" in expense_names, (
            f"QCD missing from cf_expenses: {expense_names}"
        )
        qcd_entry = next(e for e in snap.cash_flow.expenses if e.name == "QCD to charity")
        assert qcd_entry.amount == pytest.approx(8_000, abs=1.0)
        assert qcd_entry.category == "discretionary"


class TestPayrollContributionIntegration:
    def test_partial_first_year_annualizes_magi_for_roth_eligibility(self):
        plan = minimal_plan(
            start_year=2026,
            first_year_fraction=0.25,
            birth_year=2000,
            life_expectancy=27,
            filing_status="married_filing_jointly",
            income_streams=[
                IncomeData(id="salary", name="Salary", annual_amount=285_000),
            ],
            priorities=[
                PriorityData(priority_rank=1, target_account_id="roth"),
                PriorityData(priority_rank=2, target_account_id="taxable"),
            ],
            accounts={
                "roth": AccountInfo(balance=0, account_type="roth_ira"),
                "taxable": AccountInfo(
                    balance=0,
                    account_type="taxable_brokerage",
                    cost_basis=0,
                ),
            },
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.0,
                "capital_gains_tax_rate": 0.0,
            },
        )

        snapshot = run_simulation(plan).yearly_snapshots[0]

        assert snapshot.gross_income == pytest.approx(71_250)
        assert snapshot.accounts["roth"] == 0
        assert snapshot.accounts["taxable"] == pytest.approx(71_250)

    def test_employee_deferral_reduces_taxable_cash_but_not_expense_metric(self):
        plan = minimal_plan(
            start_year=2026,
            birth_year=2000,
            life_expectancy=27,
            filing_status="married_filing_jointly",
            income_streams=[
                IncomeData(id="salary", name="Salary", annual_amount=110_000),
            ],
            priorities=[
                PriorityData(
                    priority_rank=1,
                    target_account_id="401k",
                    priority_type="income_percent",
                    source_income_id="salary",
                    employee_rate=0.06,
                    employer_match_rate=0.04,
                ),
            ],
            accounts={
                "401k": AccountInfo(balance=0, account_type="traditional_401k"),
                "cash": AccountInfo(balance=0, account_type="savings"),
            },
            tax_settings={
                "mode": "flat",
                "ordinary_income_tax_rate": 0.24,
                "capital_gains_tax_rate": 0.20,
            },
        )

        snapshot = run_simulation(plan).yearly_snapshots[0]

        assert snapshot.gross_income == pytest.approx(114_400)  # 110,000 salary + 4,400 match
        assert snapshot.federal_tax == pytest.approx(24_816)  # 24% of 114,400 - 11,000 pre-tax
        assert snapshot.expenses == 0
        assert snapshot.accounts["401k"] == pytest.approx(11_000)
        assert snapshot.accounts["cash"] == pytest.approx(78_584)
        assert snapshot.net_worth == pytest.approx(89_584)
        assert snapshot.cash_flow is not None
        assert snapshot.cash_flow.payroll_deductions == pytest.approx(6_600)
        assert snapshot.cash_flow.contributions[0].amount == pytest.approx(6_600)
        assert snapshot.cash_flow.contributions[1].amount == pytest.approx(4_400)



class TestAdvancedExpenseControls:
    """Regression examples for custom growth, caps, recurrence and specific funding."""

    def _base(self, expenses, accounts=None, drawdown=None):
        return minimal_plan(
            start_year=2026, birth_year=1990, life_expectancy=50,
            milestones=[], expenses=expenses,
            accounts=accounts or {"cash": AccountInfo(balance=5_000_000, account_type="checking")},
            drawdown_order=drawdown or [DrawdownEntryData(rank=1, source_account_id="cash")],
            assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0, bond_return_rate=0.0),
        )

    def test_custom_growth_is_capped_by_an_inflation_linked_ceiling(self):
        plan = self._base([
            ExpenseData(id="tuition", name="Tuition", annual_amount=30_000,
                        growth_rate=0.08, growth_cap=33_000, growth_cap_inflation_linked=True),
        ])
        snaps = run_simulation(plan).yearly_snapshots
        # Year 0: 30k. Year 1: 32.4k (< 33k*1.03). Year 2: 34.99k > cap 33k*1.03^2=35.0k? no -> 34.99k
        # Year 3: 37.79k > cap 36.06k -> capped.
        assert snaps[0].expenses == pytest.approx(30_000)
        assert snaps[1].expenses == pytest.approx(30_000 * 1.08)
        assert snaps[3].expenses == pytest.approx(33_000 * 1.03 ** 3)
        assert snaps[10].expenses == pytest.approx(33_000 * 1.03 ** 10)

    def test_custom_growth_without_cap_ignores_inflation_setting(self):
        plan = self._base([
            ExpenseData(id="rent", name="Rent", annual_amount=24_000, inflation_linked=True, growth_rate=0.05),
        ])
        snaps = run_simulation(plan).yearly_snapshots
        assert snaps[4].expenses == pytest.approx(24_000 * 1.05 ** 4)

    def test_fixed_nominal_expense_does_not_grow(self):
        plan = self._base([
            ExpenseData(id="loan", name="Loan", annual_amount=12_000, inflation_linked=False),
        ])
        snaps = run_simulation(plan).yearly_snapshots
        assert snaps[0].expenses == snaps[9].expenses == pytest.approx(12_000)

    def test_recurring_expense_combines_growth_cap_and_per_occurrence_change(self):
        plan = self._base([
            ExpenseData(id="car", name="Car", annual_amount=40_000, growth_rate=0.02, growth_cap=45_000,
                        recurrence_years=5, recurrence_growth_rate=0.10),
        ])
        snaps = run_simulation(plan).yearly_snapshots
        assert snaps[0].expenses == pytest.approx(40_000)
        assert snaps[1].expenses == 0 and snaps[4].expenses == 0
        # Occurrence 1 (year 5): min(40k*1.02^5, 45k) * 1.10
        assert snaps[5].expenses == pytest.approx(min(40_000 * 1.02 ** 5, 45_000) * 1.10)
        # Occurrence 2 (year 10): growth 40k*1.02^10=48.8k -> capped at 45k, then *1.10^2
        assert snaps[10].expenses == pytest.approx(45_000 * 1.10 ** 2)

    def test_specific_funding_source_draws_only_from_the_named_account(self):
        plan = self._base(
            [ExpenseData(id="tuition", name="Tuition", annual_amount=50_000, inflation_linked=False,
                         specific_funding_source_id="529")],
            accounts={
                "cash": AccountInfo(balance=1_000_000, account_type="checking"),
                "529": AccountInfo(balance=200_000, account_type="taxable_brokerage", cost_basis=200_000),
            },
        )
        snaps = run_simulation(plan).yearly_snapshots
        assert snaps[0].accounts["529"] == pytest.approx(150_000)
        assert snaps[0].accounts["cash"] == pytest.approx(1_000_000)
        assert snaps[0].expenses == pytest.approx(50_000)
        # Once the named account is empty the expense is still owed: the
        # remainder falls back to general cash flow and the drawdown order.
        assert snaps[3].accounts["529"] == pytest.approx(0)
        assert snaps[3].accounts["cash"] == pytest.approx(1_000_000)
        assert snaps[4].accounts["cash"] == pytest.approx(950_000)



def test_circular_relative_milestones_never_fire_and_do_not_hang():
    """The API rejects cycles, but stateless requests can still carry them; the
    engine must complete and report both milestones as never reached."""
    plan = minimal_plan(
        start_year=2026, birth_year=1990, life_expectancy=40,
        milestones=[
            MilestoneData(id="a", name="A", trigger_type="relative", relative_to_id="b", offset_years=1),
            MilestoneData(id="b", name="B", trigger_type="relative", relative_to_id="a", offset_years=1),
        ],
        expenses=[], accounts={"cash": AccountInfo(balance=10_000, account_type="checking")},
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
    )
    result = run_simulation(plan)
    assert {o.id: o.year for o in result.metadata.milestone_outcomes} == {"a": None, "b": None}



def test_gain_harvest_is_tax_free_in_zero_bracket_and_shields_later_withdrawals():
    """Harvesting inside the 0% bracket costs nothing now and lowers the gain
    realised by later sales; the account balance is unaffected."""
    def make(harvest: bool):
        priorities = [PriorityData(priority_rank=1, priority_type="gain_harvest", source_account_id="brok",
                                   conversion_mode="fill_bracket", bracket_ceiling_rate=0.0)] if harvest else []
        return minimal_plan(
            start_year=2026, birth_year=1966, life_expectancy=64, filing_status="single",
            milestones=[], income_streams=[],
            expenses=[ExpenseData(id="living", name="Living", annual_amount=30_000, inflation_linked=False)],
            accounts={"brok": AccountInfo(balance=400_000, account_type="taxable_brokerage", cost_basis=100_000)},
            drawdown_order=[DrawdownEntryData(rank=1, source_account_id="brok")],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
            priorities=priorities,
        )

    base = run_simulation(make(False)).yearly_snapshots
    harv = run_simulation(make(True)).yearly_snapshots
    assert harv[0].harvested_gains > 0
    # The harvest itself sits in the 0% bracket; the small tax that remains comes
    # from gains realised by the year's later withdrawals stacking above it.
    assert harv[0].capital_gains_tax < 0.15 * harv[0].harvested_gains * 0.1
    # No cash moved by the harvest itself; only the small stacking tax leaves the account.
    assert harv[0].accounts["brok"] >= base[0].accounts["brok"] - harv[0].capital_gains_tax - 1.0
    # With a 400k balance and 100k basis, later years keep harvesting until basis catches up;
    # total lifetime capital gains tax must not rise and balances must not fall.
    # Only the stacking effect of later withdrawals is taxed; the harvest itself is free.
    assert sum(s.capital_gains_tax for s in harv) < 0.02 * sum(s.harvested_gains for s in harv)
    # In this zero-growth toy the base already pays no gains tax, so harvesting
    # cannot add value; the only difference is the small stacking tax paid.
    assert harv[-1].net_worth == pytest.approx(base[-1].net_worth - sum(s.capital_gains_tax for s in harv), abs=1.0)
    assert sum(s.harvested_gains for s in harv) <= 300_000 + 1.0


def _harvest_with_social_security_plan(**rule):
    return minimal_plan(
        start_year=2026, birth_year=1959, birth_month=1, life_expectancy=70, filing_status="single",
        milestones=[],
        income_streams=[
            IncomeData(id="ss", name="SS", annual_amount=30_000, tax_category="social_security", claiming_age=62),
            IncomeData(id="pen", name="Pension", annual_amount=20_000, tax_category="qualified_pension"),
        ],
        expenses=[ExpenseData(id="living", name="Living", annual_amount=30_000, inflation_linked=False)],
        accounts={"cash": AccountInfo(balance=50_000, account_type="checking"),
                  "brok": AccountInfo(balance=1_000_000, account_type="taxable_brokerage", cost_basis=200_000)},
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash"),
                        DrawdownEntryData(rank=2, source_account_id="brok")],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        priorities=[PriorityData(priority_rank=1, priority_type="gain_harvest", source_account_id="brok",
                                 conversion_mode="fill_bracket", **rule)],
    )


def test_zero_percent_gain_harvest_counts_its_own_social_security_inclusion():
    """The harvest raises provisional income, so taxable Social
    Security rises with it (IRC 86). Room must be solved post-harvest.

    Single, 67 in 2026: SS 30,000, pension 20,000. Deductions are 16,100
    standard + 2,050 IRC 63(f) + 6,000 senior = 24,150 while AGI <= 75,000.
    Once the gain lifts provisional income enough, taxable SS hits its cap of
    0.85 x 30,000 = 25,500 (Pub. 915), so ordinary taxable income is
    20,000 + 25,500 - 24,150 = 21,350 and the 0% band (49,450, Rev. Proc.
    2025-32) leaves 49,450 - 21,350 = 28,100 of gain. AGI is then 73,600, under
    the 75,000 senior phase-out. Ordinary tax: 1,240 + 0.12 x (21,350 - 12,400).
    """
    snap = run_simulation(_harvest_with_social_security_plan(bracket_ceiling_rate=0.0)).yearly_snapshots[0]
    assert snap.harvested_gains == pytest.approx(28_100, abs=0.01)
    assert snap.capital_gains_tax == pytest.approx(0.0, abs=0.01)
    assert snap.deduction_amount == pytest.approx(24_150)
    assert snap.federal_tax == pytest.approx(1_240 + 0.12 * 8_950, abs=0.01)


def test_gain_harvest_magi_cap_counts_its_own_social_security_inclusion():
    """With a 15% ceiling the band is not binding; a 70,000 MAGI cap
    is. MAGI = 20,000 pension + 25,500 taxable SS (capped once the gain is
    large) + gain, so the gain is 70,000 - 45,500 = 24,500, not the
    pre-harvest 70,000 - 25,350 = 44,650."""
    snap = run_simulation(_harvest_with_social_security_plan(
        bracket_ceiling_rate=0.15, magi_cap=70_000)).yearly_snapshots[0]
    assert snap.harvested_gains == pytest.approx(24_500, abs=0.01)
