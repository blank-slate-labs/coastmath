"""Regression tests for two projection-engine accounting corrections.

1. Pre-tax contributions funded from after-tax cash in the savings
   waterfall reduce taxable income (deductible IRA, solo 401(k), HSA).
2. Income and custom expense growth compound from the plan's start year,
   so a stream entered in today's dollars that begins later is carried
   forward to its start date.
"""

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionCurveData,
    AssumptionData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)


def _plan(**overrides) -> PlanData:
    base = dict(
        plan_id=str(uuid.uuid4()),
        birth_year=1980,
        filing_status="single",
        life_expectancy=65,
        start_year=2026,
        assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0),
    )
    base.update(overrides)
    return PlanData(**base)


class TestWaterfallPreTaxDeduction:
    @staticmethod
    def _first_year(account_type: str, contribute: bool):
        priorities = [PriorityData(1, "chk")]
        if contribute:
            priorities = [PriorityData(1, "acct", max_annual_amount=7_000), PriorityData(2, "chk")]
        plan = _plan(
            income_streams=[IncomeData("s", "Salary", 100_000)],
            accounts={"chk": AccountInfo(0, "checking"), "acct": AccountInfo(0, account_type)},
            priorities=priorities,
        )
        return run_simulation(plan).yearly_snapshots[0]

    @pytest.mark.parametrize("account_type", ["traditional_ira", "traditional_401k", "hsa"])
    def test_pre_tax_contribution_reduces_federal_tax(self, account_type: str) -> None:
        without = self._first_year(account_type, contribute=False)
        with_contribution = self._first_year(account_type, contribute=True)
        deposited = with_contribution.accounts["acct"]
        assert deposited > 0
        # Taxable income of 83,900 sits in the 22% bracket before and after.
        expected_saving = deposited * 0.22
        assert without.federal_tax - with_contribution.federal_tax == pytest.approx(expected_saving, abs=1)
        # Cash is conserved: the refund lands in the cash account.
        assert sum(with_contribution.accounts.values()) - sum(without.accounts.values()) == pytest.approx(expected_saving, abs=1)

    def test_roth_ira_contribution_is_not_deducted(self) -> None:
        without = self._first_year("roth_ira", contribute=False)
        with_roth = self._first_year("roth_ira", contribute=True)
        assert with_roth.accounts["acct"] == pytest.approx(7_000)
        assert with_roth.federal_tax == pytest.approx(without.federal_tax)


class TestGrowthCompoundsFromPlanStart:
    RETIRE = MilestoneData("ret", "Retire", "age", trigger_value=60)

    def _income_plan(self, growth_rate: float) -> PlanData:
        return _plan(
            milestones=[self.RETIRE],
            income_streams=[IncomeData(
                "pen", "Pension", 30_000, start_milestone_id="ret",
                growth_rate=growth_rate, is_earned_income=False,
            )],
            accounts={"chk": AccountInfo(0, "checking")},
            priorities=[PriorityData(1, "chk")],
        )

    def test_future_income_is_carried_forward_to_its_start(self) -> None:
        snaps = {s.age: s for s in run_simulation(self._income_plan(0.03)).yearly_snapshots}
        assert snaps[59].gross_income == 0
        assert snaps[60].gross_income == pytest.approx(30_000 * 1.03 ** 14)
        assert snaps[61].gross_income == pytest.approx(30_000 * 1.03 ** 15)

    def test_zero_growth_means_fixed_nominal_amount(self) -> None:
        snaps = {s.age: s for s in run_simulation(self._income_plan(0.0)).yearly_snapshots}
        assert snaps[60].gross_income == pytest.approx(30_000)
        assert snaps[64].gross_income == pytest.approx(30_000)

    def test_currently_active_income_is_unchanged(self) -> None:
        plan = _plan(
            income_streams=[IncomeData("s", "Salary", 100_000, growth_rate=0.05)],
            accounts={"chk": AccountInfo(0, "checking")},
            priorities=[PriorityData(1, "chk")],
        )
        snaps = run_simulation(plan).yearly_snapshots
        assert snaps[0].gross_income == pytest.approx(100_000)
        assert snaps[1].gross_income == pytest.approx(105_000)

    @pytest.mark.parametrize("owner", ["self", "spouse"])
    @pytest.mark.parametrize("growth_rate,curve_rate,expected_rate", [
        (None, None, 0.03),
        (None, 0.05, 0.05),
        (0.0, None, 0.0),
    ])
    def test_blank_earned_income_follows_wage_curve_or_inflation(
        self, owner: str, growth_rate: float | None,
        curve_rate: float | None, expected_rate: float,
    ) -> None:
        plan = _plan(
            spouse_birth_year=1982 if owner == "spouse" else None,
            spouse_life_expectancy=65 if owner == "spouse" else None,
            income_streams=[IncomeData(
                "salary", "Salary", 100_000, owner=owner,
                growth_rate=growth_rate, is_earned_income=True,
            )],
            assumption_curves=(
                [AssumptionCurveData("wage_growth", fixed_rate=curve_rate)]
                if curve_rate is not None else []
            ),
        )
        snapshots = run_simulation(plan).yearly_snapshots
        assert snapshots[0].gross_income == pytest.approx(100_000)
        assert snapshots[1].gross_income == pytest.approx(100_000 * (1 + expected_rate))

    def test_future_expense_with_custom_growth_is_carried_forward(self) -> None:
        plan = _plan(
            milestones=[self.RETIRE],
            expenses=[ExpenseData("c", "Care", 30_000, start_milestone_id="ret", growth_rate=0.05)],
            accounts={"chk": AccountInfo(5_000_000, "checking")},
            priorities=[PriorityData(1, "chk")],
        )
        snaps = {s.age: s for s in run_simulation(plan).yearly_snapshots}
        assert snaps[59].expenses == 0
        assert snaps[60].expenses == pytest.approx(30_000 * 1.05 ** 14)

    def test_recurring_expense_cadence_still_counts_from_activation(self) -> None:
        plan = _plan(
            milestones=[self.RETIRE],
            expenses=[ExpenseData(
                "car", "Car", 20_000, start_milestone_id="ret",
                inflation_linked=False, recurrence_years=3,
            )],
            accounts={"chk": AccountInfo(5_000_000, "checking")},
            priorities=[PriorityData(1, "chk")],
        )
        snaps = {s.age: s for s in run_simulation(plan).yearly_snapshots}
        assert snaps[60].expenses == pytest.approx(20_000)
        assert snaps[61].expenses == 0
        assert snaps[62].expenses == 0
        assert snaps[63].expenses == pytest.approx(20_000)
