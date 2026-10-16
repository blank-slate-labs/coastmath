"""Age-based federal deductions: IRC 63(f) additional standard deduction and
the 2025-2028 IRC 151(d)(5) senior deduction (Pub. L. 119-21)."""

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    PlanData,
    PriorityData,
)

BASE_SINGLE = 16_100.0
BASE_MFJ = 32_200.0


class TestAdditionalStandardDeduction:
    def test_single_filer_gets_larger_amount_at_65(self) -> None:
        young = calculate(60_000, 0, "single", holder_age=64, tax_year=2026)
        aged = calculate(60_000, 0, "single", holder_age=65, tax_year=2026)
        assert young.standard_deduction == pytest.approx(BASE_SINGLE)
        assert aged.standard_deduction == pytest.approx(BASE_SINGLE + 2_050)

    def test_joint_return_counts_each_spouse(self) -> None:
        one = calculate(100_000, 0, "married_filing_jointly", holder_age=66, spouse_age=60, tax_year=2026)
        two = calculate(100_000, 0, "married_filing_jointly", holder_age=66, spouse_age=70, tax_year=2026)
        assert one.standard_deduction == pytest.approx(BASE_MFJ + 1_650)
        assert two.standard_deduction == pytest.approx(BASE_MFJ + 2 * 1_650)

    def test_spouse_ignored_on_single_return(self) -> None:
        result = calculate(60_000, 0, "single", holder_age=60, spouse_age=70, tax_year=2026)
        assert result.standard_deduction == pytest.approx(BASE_SINGLE)
        assert result.senior_deduction == 0.0

    def test_unknown_age_takes_nothing(self) -> None:
        result = calculate(60_000, 0, "single", tax_year=2026)
        assert result.standard_deduction == pytest.approx(BASE_SINGLE)
        assert result.senior_deduction == 0.0

    def test_addition_is_indexed_with_inflation(self) -> None:
        result = calculate(60_000, 0, "single", holder_age=70, tax_year=2026, inflation_factor=1.5)
        assert result.standard_deduction == pytest.approx((BASE_SINGLE + 2_050) * 1.5)

    def test_itemizer_keeps_senior_deduction_but_not_age_standard_addition(self) -> None:
        itemized = {"mortgage_interest": 30_000, "property_tax": 8_000}
        result = calculate(120_000, 0, "single", holder_age=70, tax_year=2026, itemized_deductions=itemized)
        assert result.deduction_used == "itemized"
        # 38,000 itemized + 3,300 senior deduction (6,000 - 6% x 45,000)
        assert result.senior_deduction == pytest.approx(3_300)
        assert result.deduction_amount == pytest.approx(38_000 + 3_300)


class TestSeniorDeduction:
    def test_full_amount_below_threshold(self) -> None:
        result = calculate(60_000, 0, "single", holder_age=65, tax_year=2026)
        assert result.senior_deduction == pytest.approx(6_000)
        assert result.taxable_income == pytest.approx(60_000 - BASE_SINGLE - 2_050 - 6_000)

    def test_phases_down_at_six_percent_of_excess_magi(self) -> None:
        result = calculate(125_000, 0, "single", holder_age=70, tax_year=2026)
        assert result.senior_deduction == pytest.approx(6_000 - 0.06 * 50_000)
        gone = calculate(200_000, 0, "single", holder_age=70, tax_year=2026)
        assert gone.senior_deduction == 0.0

    def test_joint_threshold_and_two_seniors(self) -> None:
        # Schedule 1-A Part V reduces each spouse's $6,000 separately.
        result = calculate(170_000, 0, "married_filing_jointly", holder_age=70, spouse_age=68, tax_year=2026)
        assert result.senior_deduction == pytest.approx(2 * (6_000 - 0.06 * 20_000))

    def test_joint_deduction_is_gone_at_250k_with_two_seniors(self) -> None:
        nearly = calculate(249_000, 0, "married_filing_jointly", holder_age=70, spouse_age=68, tax_year=2026)
        gone = calculate(250_000, 0, "married_filing_jointly", holder_age=70, spouse_age=68, tax_year=2026)
        assert nearly.senior_deduction == pytest.approx(2 * 60)
        assert gone.senior_deduction == 0.0

    def test_joint_return_with_one_senior(self) -> None:
        result = calculate(200_000, 0, "married_filing_jointly", holder_age=70, spouse_age=60, tax_year=2026)
        assert result.senior_deduction == pytest.approx(6_000 - 0.06 * 50_000)

    def test_not_available_before_2025_or_after_2028(self) -> None:
        for year in (2024, 2029):
            result = calculate(60_000, 0, "single", holder_age=70, tax_year=year)
            assert result.senior_deduction == 0.0
            assert result.standard_deduction == pytest.approx(BASE_SINGLE + 2_050)

    def test_married_filing_separately_ineligible(self) -> None:
        result = calculate(60_000, 0, "married_filing_separately", holder_age=70, tax_year=2026)
        assert result.senior_deduction == 0.0
        assert result.standard_deduction == pytest.approx(BASE_SINGLE + 1_650)

    def test_thresholds_are_not_indexed(self) -> None:
        indexed = calculate(125_000, 0, "single", holder_age=70, tax_year=2026, inflation_factor=2.0)
        assert indexed.senior_deduction == pytest.approx(6_000 - 0.06 * 50_000)

    def test_added_back_for_amt_when_itemizing(self) -> None:
        itemized = {"mortgage_interest": 30_000}
        aged = calculate(120_000, 0, "single", holder_age=70, tax_year=2026, itemized_deductions=itemized)
        young = calculate(120_000, 0, "single", holder_age=40, tax_year=2026, itemized_deductions=itemized)
        # Tentative minimum tax is computed on the same AMTI for both filers.
        assert aged.amt == pytest.approx(young.amt)


class TestSimulatorPassesAges:
    @staticmethod
    def _run(birth_year: int, filing_status: str = "single", spouse_birth_year: int | None = None):
        plan = PlanData(
            plan_id=str(uuid.uuid4()),
            birth_year=birth_year,
            filing_status=filing_status,
            life_expectancy=(2030 - birth_year),
            start_year=2026,
            spouse_birth_year=spouse_birth_year,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            income_streams=[IncomeData("p", "Pension", 60_000, is_earned_income=False)],
            accounts={"chk": AccountInfo(0, "checking")},
            priorities=[PriorityData(1, "chk")],
        )
        return run_simulation(plan).yearly_snapshots

    def test_retiree_gets_age_deductions_and_lower_tax(self) -> None:
        young = self._run(1980)[0]
        aged = self._run(1955)[0]
        assert young.standard_deduction == pytest.approx(BASE_SINGLE)
        assert aged.standard_deduction == pytest.approx(BASE_SINGLE + 2_050)
        # 2,050 + 6,000 of income leaves the 12% bracket.
        assert young.federal_tax - aged.federal_tax == pytest.approx((2_050 + 6_000) * 0.12, abs=1)

    def test_senior_deduction_expires_after_2028_in_projection(self) -> None:
        snaps = self._run(1955)
        by_year = {s.year: s for s in snaps}
        # The $6,000 IRC 151(d)(5) deduction ends with 2028.
        assert by_year[2029].federal_tax - by_year[2028].federal_tax == pytest.approx(6_000 * 0.12, abs=1)

    def test_spouse_age_counts_on_joint_return(self) -> None:
        snap = self._run(1980, "married_filing_jointly", spouse_birth_year=1958)[0]
        assert snap.standard_deduction == pytest.approx(BASE_MFJ + 1_650)
