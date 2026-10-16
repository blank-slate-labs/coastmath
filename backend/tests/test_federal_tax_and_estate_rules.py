"""Federal income and estate tax rules at their boundaries.

The senior deduction phases out per spouse; the non-itemizer gift deduction
enters the itemize choice and AMT; AMT keeps the full preferential amount when
the deduction absorbs ordinary income; NIIT nets the deductible capital loss;
the effective rate's denominator includes a taxable Roth conversion; joint
rates end two years after a death; state death taxes and the IRC 691(c)
deduction reduce the federal estate tax; and spouses who die in the same year
leave two estates.

Expected values come from the cited rules and published tables, not from
engine output.
"""

import uuid

import pytest

from coastmath.engine.estate_tax import calculate_estate_breakdown
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
)

ZERO = AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0)


def _plan(**kw) -> PlanData:
    values = dict(plan_id=str(uuid.uuid4()), birth_year=1980, birth_month=1, filing_status="single",
                  life_expectancy=50, start_year=2026, assumptions=ZERO)
    values.update(kw)
    return PlanData(**values)


# ---------------------------------------------------------------------------
# Senior deduction phase-out for joint filers
# IRC 151(d)(5); 2025 Schedule 1-A, Part V, lines 34-37.
# ---------------------------------------------------------------------------


class TestSeniorDeductionPhaseOut:
    @pytest.mark.parametrize("magi, expected", [
        (150_000, 12_000), (200_000, 6_000), (249_000, 120), (260_000, 0),
    ])
    def test_each_spouse_amount_is_reduced_separately(self, magi, expected):
        result = calculate(magi, 0, "married_filing_jointly", holder_age=70, spouse_age=68, tax_year=2026)
        assert result.senior_deduction == pytest.approx(expected)

    def test_federal_tax_near_the_joint_endpoint(self):
        # 249,000 - (32,200 + 2 x 1,650) - 120 = 213,380 taxable:
        # 2,480 + 9,120 + 24,332 + 24% x 1,980 = 36,407.20.
        result = calculate(249_000, 0, "married_filing_jointly", holder_age=70, spouse_age=68, tax_year=2026)
        assert result.federal == pytest.approx(36_407.20)


# ---------------------------------------------------------------------------
# The non-itemizer gift deduction in the itemize choice
# 26 USC 170(p), 170(b)(1)(I); IRC 56(b)(1)(E).
# ---------------------------------------------------------------------------


class TestNonItemizerGiftDeduction:
    @staticmethod
    def _joint(income: float, mortgage_interest: float | None, gift: float):
        itemized = None if mortgage_interest is None else {"mortgage_interest": mortgage_interest}
        return calculate(income, 0, "married_filing_jointly", tax_year=2026, itemized_deductions=itemized,
                         charitable_deduction=gift if itemized is not None else 0.0,
                         charitable_direct_cash=gift)

    def test_standard_plus_gift_beats_slightly_larger_itemized_deductions(self):
        result = self._joint(100_000, 31_000, 2_000)
        # Itemized 31,000 + (2,000 - 0.5% x 100,000) = 32,500 < 32,200 + 2,000.
        assert result.deduction_used == "standard"
        assert result.deduction_amount == pytest.approx(34_200)
        assert result.federal == pytest.approx(2_480 + 0.12 * (65_800 - 24_800))

    def test_itemizing_wins_only_above_standard_plus_gift(self):
        result = self._joint(100_000, 33_000, 2_000)
        assert result.deduction_used == "itemized"
        assert result.deduction_amount == pytest.approx(34_500)

    def test_gift_deduction_is_allowed_for_amt(self):
        without = self._joint(300_000, None, 0)
        with_gift = self._joint(300_000, None, 2_000)
        # AMTI 300,000 vs 298,000 above the 140,200 joint exemption: 26% band.
        assert without.amt - with_gift.amt == pytest.approx(0.26 * 2_000)


# ---------------------------------------------------------------------------
# AMT preferential amount when the deduction absorbs
# ordinary income. Form 6251 line 13 is the full qualified dividends and net
# capital gain; lines 19-21 give the 0% room only above ordinary taxable
# income. 2026: single 0%/15% to $49,450/$545,500, joint $98,900/$613,700.
# ---------------------------------------------------------------------------


class TestAmtWithDeductionAbsorbedGains:
    def test_single_gain_only(self):
        r = calculate(0.0, 0.0, "single", capital_gains=1_000_000, tax_year=2026)
        # Regular: $983,900 of gains after the $16,100 deduction.
        regular = (545_500 - 49_450) * .15 + (983_900 - 545_500) * .20
        # AMTI $1M, exemption fully phased out; all $1M is line 13 gain.
        tentative = (545_500 - 49_450) * .15 + (1_000_000 - 545_500) * .20
        assert r.amt == pytest.approx(tentative)
        assert r.federal + r.capital_gains_tax - regular == pytest.approx(3_220.00)

    def test_joint_both_over_65(self):
        r = calculate(0.0, 0.0, "married_filing_jointly", capital_gains=1_500_000,
                      holder_age=66, spouse_age=66, tax_year=2026)
        # $35,500 standard deduction (32,200 + 2 x 1,650); senior deduction phased out.
        regular = (613_700 - 98_900) * .15 + (1_464_500 - 613_700) * .20
        assert r.federal + r.capital_gains_tax - regular == pytest.approx(7_100.00)

    def test_ordinary_income_above_deduction_unchanged(self):
        # With ordinary income above the deduction no gain is absorbed, so
        # line 13 equals the taxable gain and nothing changes.
        r = calculate(200_000, 0.0, "single", earned_income=200_000,
                      capital_gains=100_000, tax_year=2026)
        assert r.amt < r.federal + r.capital_gains_tax


# ---------------------------------------------------------------------------
# NIIT nets the deductible capital loss. Form 8960
# line 5a takes the Form 1040 line 7 loss, at most $3,000 (IRC 1211(b)).
# ---------------------------------------------------------------------------


class TestNiitWithCapitalLoss:
    def test_loss_reduces_net_investment_income(self):
        r = calculate(300_000, 0.0, "single", capital_gains=-10_000,
                      net_investment_income=5_000, earned_income=295_000, tax_year=2026)
        assert r.niit == pytest.approx(0.038 * (5_000 - 3_000))
        assert r.capital_loss_carryforward == pytest.approx(7_000)

    def test_loss_larger_than_other_income_gives_zero(self):
        r = calculate(300_000, 0.0, "single", capital_gains=-10_000,
                      net_investment_income=2_000, earned_income=298_000, tax_year=2026)
        assert r.niit == 0.0

    def test_gain_unchanged(self):
        r = calculate(300_000, 0.0, "single", capital_gains=10_000,
                      net_investment_income=5_000, earned_income=295_000, tax_year=2026)
        assert r.niit == pytest.approx(0.038 * 15_000)


# ---------------------------------------------------------------------------
# The effective rate's denominator includes the taxable
# Roth conversion whose tax is in its numerator.
# ---------------------------------------------------------------------------


class TestEffectiveRateWithConversion:
    def test_conversion_in_denominator(self):
        p = _plan(birth_year=1976, life_expectancy=52,
                  assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0,
                                             bond_return_rate=0, cash_yield_rate=0.01),
                  expenses=[ExpenseData("live", "Living", 40_000, inflation_linked=False)],
                  accounts={"cash": AccountInfo(100_000, "savings"),
                            "ira": AccountInfo(500_000, "traditional_ira"),
                            "roth": AccountInfo(0, "roth_ira")},
                  priorities=[PriorityData(1, "roth", priority_type="roth_conversion",
                                           source_account_id="ira", max_annual_amount=50_000)],
                  drawdown_order=[DrawdownEntryData(1, "cash")])
        s = run_simulation(p).yearly_snapshots[0]
        # $1,000 interest + $50,000 conversion, $16,100 deduction:
        # 10% x 12,400 + 12% x 22,500 = 3,940.
        assert s.taxes == pytest.approx(3_940.00, abs=0.01)
        assert s.gross_income == pytest.approx(1_000.00, abs=0.01)
        assert s.effective_rate == pytest.approx(3_940 / 51_000, abs=1e-6)


# ---------------------------------------------------------------------------
# Legacy mode applied married_filing_jointly forever
# after a death. IRC 2(a)(1) allows joint rates for at most the two years
# after the death year; later years are single.
# ---------------------------------------------------------------------------


class TestJointFilingAfterDeath:
    def test_joint_rates_end_after_two_years(self):
        p = _plan(birth_year=1960, filing_status="married_filing_jointly", life_expectancy=75,
                  spouse_birth_year=1960, spouse_life_expectancy=66,
                  income_streams=[IncomeData("pen", "Pension", 100_000, is_earned_income=False)],
                  accounts={"cash": AccountInfo(0, "checking")},
                  estate_settings=EstateSettingsData(filing_status_after_death="married_filing_jointly"))
        result = run_simulation(p)
        taxes = {s.year: s.federal_tax for s in result.yearly_snapshots}
        # Spouse dies in 2026; 2027-2028 keep joint rates, 2029 is single.
        assert taxes[2027] == pytest.approx(taxes[2028])
        assert taxes[2029] > taxes[2028]
        assert any("qualifying surviving spouse" in w for w in result.metadata.warnings)


# ---------------------------------------------------------------------------
# State death taxes are deductible for federal estate tax
# IRC 2058; IRC 691(c).
# ---------------------------------------------------------------------------


class TestStateDeathTaxDeduction:
    SETTINGS = dict(state_estate_tax_enabled=True, state_estate_exemption=2_000_000,
                    state_estate_tax_rate=0.16)

    def test_federal_taxable_estate_is_reduced_by_state_tax(self):
        result = calculate_estate_breakdown(30_000_000, 0.0, EstateSettingsData(**self.SETTINGS), 2026)
        # State: 16% x (30M - 2M) = 4.48M. Federal: 40% x (30M - 4.48M - 15M).
        assert result.state_estate_tax == pytest.approx(4_480_000)
        assert result.federal_taxable_estate == pytest.approx(10_520_000)
        assert result.federal_estate_tax == pytest.approx(4_208_000)
        assert result.net_legacy == pytest.approx(30_000_000 - 4_480_000 - 4_208_000)

    def test_without_state_tax_the_federal_result_is_unchanged(self):
        result = calculate_estate_breakdown(30_000_000, 0.0, EstateSettingsData(), 2026)
        assert result.federal_estate_tax == pytest.approx(0.40 * 15_000_000)

    def test_marital_deduction_still_defers_both_taxes(self):
        result = calculate_estate_breakdown(30_000_000, 0.0, EstateSettingsData(**self.SETTINGS), 2026,
                                            marital_deduction=True)
        assert result.estate_tax == 0.0

    def test_691c_deduction_uses_tax_recomputed_without_ird(self):
        settings = EstateSettingsData(**self.SETTINGS, heir_income_tax_rate=0.37)
        result = calculate_estate_breakdown(30_000_000, 0.0, settings, 2026, pretax_balance=5_000_000)
        # Without the $5M of IRD, the state tax shrinks by 16%, so federal tax
        # falls by 40% x 5M x (1 - 0.16) = 1.68M.
        assert result.heir_income_tax_deduction_691c == pytest.approx(1_680_000)
        assert result.heir_income_tax == pytest.approx(0.37 * (5_000_000 - 1_680_000))


# ---------------------------------------------------------------------------
# Spouses who die in the same year leave two estates,
# each with a basic exclusion ($15M in 2030 at 0% inflation): 40% x
# ($40M - $30M) = $4.0M, the same as with a death one year earlier.
# ---------------------------------------------------------------------------


class TestSameYearDeathsEstate:
    @pytest.mark.parametrize(("spouse_life_expectancy", "portability"), [
        (70, True), (70, False), (69, True)])
    def test_two_exclusions(self, spouse_life_expectancy, portability):
        p = _plan(birth_year=1960, filing_status="married_filing_jointly", life_expectancy=70,
                  spouse_birth_year=1960, spouse_birth_month=1,
                  spouse_life_expectancy=spouse_life_expectancy,
                  accounts={"cash": AccountInfo(40_000_000, "checking", owner="joint")},
                  drawdown_order=[DrawdownEntryData(1, "cash")],
                  estate_settings=EstateSettingsData(household_lifecycle="last_survivor_calendar_year_end",
                                                     portability_election=portability))
        estate = run_simulation(p).metadata.net_legacy
        expected = 4_000_000 if portability or spouse_life_expectancy == 70 else 10_000_000
        assert estate.federal_estate_tax == pytest.approx(expected)
        if spouse_life_expectancy == 70:
            assert estate.federal_exemption == pytest.approx(30_000_000)
            assert estate.dsue_amount == 0
