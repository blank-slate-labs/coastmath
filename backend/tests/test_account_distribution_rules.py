"""Distributions from HSAs and IRAs follow the owner, the age and the calendar.

HSA withdrawals beyond modeled medical costs are income plus the 20% penalty
before 65; the early-withdrawal penalty applies only to the months before
59 1/2; a SEPP series from a partner-owned IRA follows that owner; the
opening-year RMD credits withdrawals already taken; generated cash is spent
before retirement accounts; and the withdrawal comparison reports annual real
rates after a partial opening year.

Expected values come from the cited rules and published 2026 tables, not
from engine output. Plans use zero growth and inflation so each figure can be
checked by hand.
"""

import uuid

import pytest
from pydantic import ValidationError

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    SEPPSettingsData,
)
from coastmath.engine.waterfall import share_of_year_before_age
from coastmath.engine.withdrawal_comparison import compare_withdrawal_strategies
from coastmath.schemas.year_to_date import YearToDateTax

ZERO = AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0)


def _plan(**overrides) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1986, filing_status="single",
        life_expectancy=45, start_year=2026, assumptions=ZERO,
    )
    values.update(overrides)
    return PlanData(**values)


# ---------------------------------------------------------------------------
# HSA withdrawals beyond modeled medical costs
# IRC 223(f)(2), (f)(4); IRS Publication 969.
# ---------------------------------------------------------------------------


def _hsa_plan(birth_year: int, balance: float, spending: float, **overrides) -> PlanData:
    values = dict(
        birth_year=birth_year, life_expectancy=2026 - birth_year + 1,
        accounts={"hsa": AccountInfo(balance, "hsa")},
        drawdown_order=[DrawdownEntryData(1, "hsa")],
        expenses=[ExpenseData("living", "Living", spending, inflation_linked=False)],
    )
    values.update(overrides)
    return _plan(**values)


class TestHsaWithdrawals:
    def test_non_medical_shortfall_is_income_plus_twenty_percent_before_65(self):
        year = run_simulation(_hsa_plan(1986, 100_000, 30_000)).yearly_snapshots[0]
        # 0.8 W = 30,000 + tax(W); tax(W) = 1,240 + 12% x (W - 16,100 - 12,400)
        # -> W = 27,820 / 0.68 = 40,911.76.
        withdrawal = 27_820 / 0.68
        assert 100_000 - year.accounts["hsa"] == pytest.approx(withdrawal, abs=0.01)
        assert year.early_withdrawal_penalty == pytest.approx(0.2 * withdrawal, abs=0.01)
        assert year.federal_tax == pytest.approx(1_240 + 0.12 * (withdrawal - 28_500), abs=0.01)
        assert year.gross_income == pytest.approx(withdrawal, abs=0.01)

    def test_modeled_medicare_premiums_are_reimbursed_untaxed_after_65(self):
        plan = _hsa_plan(1959, 50_000, 10_000, healthcare_settings={
            "enabled": True, "medicare_enabled": True, "medicare_part_b": True,
            "medicare_part_d": False, "medicare_apply_irmaa": False})
        year = run_simulation(plan).yearly_snapshots[0]
        part_b = 202.90 * 12  # 2026 standard Part B premium
        # Part B is qualified; the $10,000 of living costs is income with no
        # additional tax at 67, inside the standard and senior deductions.
        assert 50_000 - year.accounts["hsa"] == pytest.approx(10_000 + part_b)
        assert year.gross_income == pytest.approx(10_000)
        assert year.early_withdrawal_penalty == pytest.approx(0.0)
        assert year.taxes == pytest.approx(0.0)

    def test_spending_funded_directly_from_the_hsa_stays_untaxed(self):
        plan = _hsa_plan(1986, 50_000, 0, drawdown_order=[], expenses=[
            ExpenseData("care", "Dental work", 5_000, inflation_linked=False,
                        specific_funding_source_ids=["hsa"])])
        year = run_simulation(plan).yearly_snapshots[0]
        assert year.accounts["hsa"] == pytest.approx(45_000)
        assert year.taxes == pytest.approx(0.0)

    def test_warning_only_when_hsa_money_is_taxed(self):
        text = "HSA withdrawals beyond the year's modeled medical costs are taxed"
        taxed = run_simulation(_hsa_plan(1986, 100_000, 30_000)).metadata.warnings
        untaxed = run_simulation(_hsa_plan(1986, 50_000, 0, drawdown_order=[], expenses=[
            ExpenseData("care", "Dental work", 5_000, inflation_linked=False,
                        specific_funding_source_ids=["hsa"])])).metadata.warnings
        assert any(text in warning for warning in taxed)
        assert not any(text in warning for warning in untaxed)


@pytest.mark.parametrize("age, birth_month, threshold, fraction, expected", [
    (59, 1, 59.5, 1.0, 6 / 12),     # 59.5 reached in July
    (59, 6, 59.5, 1.0, 11 / 12),    # reached in December
    (59, 7, 59.5, 1.0, 1.0),        # reached next January
    (59, None, 59.5, 1.0, 1.0),     # unknown month counts as July
    (60, 1, 59.5, 1.0, 0.0),
    (65, 3, 65, 1.0, 2 / 12),       # 65 in March: January-February before
    (59, 6, 59.5, 0.25, 2 / 3),     # October start: October-November before
])
def test_share_of_year_before_age(age, birth_month, threshold, fraction, expected):
    assert share_of_year_before_age(age, birth_month, threshold, fraction) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Month share of the age-59 year before 59.5
# IRC 72(t)(1), (t)(2)(A)(i).
# ---------------------------------------------------------------------------


def test_june_birth_pays_the_penalty_on_eleven_months_at_59():
    plan = _plan(
        birth_year=1967, birth_month=6, life_expectancy=60,
        accounts={"ira": AccountInfo(100_000, "traditional_ira")},
        drawdown_order=[DrawdownEntryData(1, "ira")],
        expenses=[ExpenseData("living", "Living", 12_000, inflation_linked=False)],
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0},
    )
    year = run_simulation(plan).yearly_snapshots[0]
    rate = 0.10 * 11 / 12  # 59.5 arrives in December
    withdrawal = 12_000 / (1 - rate)
    assert 100_000 - year.accounts["ira"] == pytest.approx(withdrawal)
    assert year.early_withdrawal_penalty == pytest.approx(withdrawal * rate)


# ---------------------------------------------------------------------------
# SEPP from a partner-owned IRA follows the owner
# IRC 72(t)(2)(A)(iv), (t)(4); IRS Notice 2022-6.
# ---------------------------------------------------------------------------


class TestSeppOwner:
    # Single Life Table (2022), age 46: 40.0; fixed amortization at 5%.
    PAYMENT = 500_000 * 0.05 / (1 - 1.05 ** -40.0)

    @staticmethod
    def _sepp_plan(**overrides) -> PlanData:
        values = dict(
            birth_year=1974, birth_month=1, filing_status="married_filing_jointly",
            spouse_birth_year=1981, spouse_birth_month=1, spouse_life_expectancy=90,
            life_expectancy=70,
            accounts={"cash": AccountInfo(0, "checking"),
                      "ira": AccountInfo(500_000, "traditional_ira", owner="spouse")},
            drawdown_order=[DrawdownEntryData(1, "cash")],
            sepp_settings=SEPPSettingsData(enabled=True, source_account_id="ira",
                                           method="fixed_amortization", start_age=46, interest_rate=0.05),
        )
        values.update(overrides)
        return _plan(**values)

    @staticmethod
    def _sepp(snapshot) -> float:
        return sum(flow.amount for flow in snapshot.cash_flow.income_sources if flow.source == "sepp")

    def test_series_uses_the_partner_owners_age_and_end_date(self):
        rows = {row.year: row for row in run_simulation(self._sepp_plan()).yearly_snapshots}
        assert self._sepp(rows[2026]) == 0  # the partner is 45
        assert self._sepp(rows[2027]) == pytest.approx(self.PAYMENT)
        assert self._sepp(rows[2039]) == pytest.approx(self.PAYMENT)
        # The partner reaches 59.5 in July 2040: January-June payments only.
        assert self._sepp(rows[2040]) == pytest.approx(self.PAYMENT / 2)
        assert self._sepp(rows[2041]) == 0
        assert all(row.early_withdrawal_penalty == 0 for row in rows.values())

    def test_series_stops_when_the_owner_dies(self):
        rows = {row.year: row for row in run_simulation(
            self._sepp_plan(spouse_life_expectancy=55)).yearly_snapshots}
        assert self._sepp(rows[2035]) == pytest.approx(self.PAYMENT)
        assert self._sepp(rows[2036]) == 0


# ---------------------------------------------------------------------------
# Opening-year RMD after withdrawals already taken
# Treas. Reg. 1.401(a)(9)-5; Uniform Lifetime Table (2022), age 75: 24.6.
# ---------------------------------------------------------------------------


class TestOpeningYearRmd:
    @staticmethod
    def _rmd_plan(opening: float, taken: float, **overrides) -> PlanData:
        values = dict(
            birth_year=1951, life_expectancy=77, first_year_fraction=0.25,
            accounts={"cash": AccountInfo(0, "checking"), "ira": AccountInfo(opening, "traditional_ira")},
            drawdown_order=[DrawdownEntryData(1, "cash")],
            tax_settings={"year_to_date": {"tax_year": 2026, "gross_income": taken,
                                           "distributions_by_account": {"ira": taken}}},
        )
        values.update(overrides)
        return _plan(**values)

    @staticmethod
    def _rmd(snapshot) -> float:
        return sum(flow.amount for flow in snapshot.cash_flow.income_sources if flow.source == "rmd")

    def test_withdrawals_already_taken_count_toward_the_minimum(self):
        # $960,000 today after $40,000 in January: December 31 was $1,000,000.
        year = run_simulation(self._rmd_plan(960_000, 40_000)).yearly_snapshots[0]
        assert self._rmd(year) == pytest.approx(1_000_000 / 24.6 - 40_000)

    def test_a_satisfied_minimum_takes_nothing_more(self):
        year = run_simulation(self._rmd_plan(959_000, 41_000)).yearly_snapshots[0]
        assert self._rmd(year) == 0.0
        assert year.accounts["ira"] == pytest.approx(959_000)

    def test_without_history_the_full_minimum_is_due(self):
        year = run_simulation(self._rmd_plan(1_000_000, 0, tax_settings={})).yearly_snapshots[0]
        assert self._rmd(year) == pytest.approx(1_000_000 / 24.6)

    def test_a_required_full_payout_is_not_reduced(self):
        # Ten-year election for a 2016 death: the balance is due in 2026.
        plan = self._rmd_plan(50_000, 5_000, accounts={
            "cash": AccountInfo(0, "checking"),
            "ira": AccountInfo(50_000, "traditional_ira", inherited_year=2016, beneficiary_type="edb",
                               inheritance_settings={"distribution_method": "ten_year"})})
        year = run_simulation(plan).yearly_snapshots[0]
        assert self._rmd(year) == pytest.approx(50_000)
        assert year.accounts["ira"] == pytest.approx(0.0)

    def test_year_to_date_schema_accepts_nonnegative_withdrawals(self):
        history = YearToDateTax.model_validate({"tax_year": 2026, "distributions_by_account": {"ira": 40_000}})
        assert history.distributions_by_account == {"ira": 40_000}
        with pytest.raises(ValidationError):
            YearToDateTax.model_validate({"tax_year": 2026, "distributions_by_account": {"ira": -1}})


# ---------------------------------------------------------------------------
# Generated cash funds shortfalls before saved accounts
# ---------------------------------------------------------------------------


def test_generated_cash_is_spent_before_retirement_accounts():
    plan = _plan(
        milestones=[MilestoneData("quit", "Quit", "date", trigger_date="2027-01-01")],
        income_streams=[IncomeData("pay", "Salary", 80_000, end_milestone_id="quit")],
        accounts={"ira": AccountInfo(100_000, "traditional_ira")},
        drawdown_order=[DrawdownEntryData(1, "ira")],
        expenses=[ExpenseData("living", "Living", 30_000, inflation_linked=False)],
    )
    rows = {row.year: row for row in run_simulation(plan).yearly_snapshots}
    # 2026: 80,000 - (8,770 federal + 6,120 FICA) - 30,000 = 35,110 banked.
    assert rows[2026].accounts["unallocated_cash"] == pytest.approx(35_110.0)
    assert rows[2027].accounts == pytest.approx({"ira": 100_000.0, "unallocated_cash": 5_110.0})
    assert rows[2027].taxes == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Withdrawal comparison in a partial opening year
# ---------------------------------------------------------------------------


def test_comparison_reports_annual_real_rates_after_a_partial_opening_year():
    plan = _plan(
        birth_year=1956, life_expectancy=80, first_year_fraction=0.25,
        assumptions=AssumptionData(inflation_rate=0.03, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts={"cash": AccountInfo(0, "checking"), "brokerage": AccountInfo(1_000_000, "taxable_brokerage")},
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "brokerage")],
        expenses=[ExpenseData("living", "Living", 40_000)],
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0},
    )
    out = compare_withdrawal_strategies(plan, methods=["constant_dollar"], initial_rate=0.04,
                                        start_milestone_id=None, start_age=None)
    rule = out.strategies[0]
    # Constant dollars in plan-start dollars: 4% of $1,000,000 every year,
    # including the October-December opening year at its annual rate.
    assert rule.first_year_spending == pytest.approx(40_000)
    assert rule.min_real_spending == pytest.approx(40_000)
    assert rule.max_real_spending == pytest.approx(40_000)
    assert rule.real_spending_drawdown == pytest.approx(0.0, abs=1e-9)
    assert [point["real"] for point in out.planned.spending_path[:3]] == pytest.approx([40_000] * 3)
    # The lifetime total is what was spent: a quarter of a year, then full years.
    years = len(out.planned.spending_path)
    assert out.planned.total_real_spending == pytest.approx(40_000 * (0.25 + years - 1))
