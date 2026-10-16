"""Withdrawal strategies, SEPP payments and gifts are timed within the year.

A withdrawal strategy starting mid-year replaces only the months from its start
month, including the withdrawal-plus-income mode; SEPP payments are sized on
the prior year-end balance; and a gift is paid from the year's cash in a
surplus year, while a deficit sells the shares reserved for it before any
tax-target withdrawals.

Expected values come from the cited rules and published tables, not from
engine output.
"""

import uuid

import pytest

from coastmath.engine.sepp import calculate_sepp
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    CharityData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
    SEPPSettingsData,
)
from coastmath.engine.withdrawal_strategy import WithdrawalStrategySpec

ZERO = AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0)


def _plan(**kw) -> PlanData:
    values = dict(plan_id=str(uuid.uuid4()), birth_year=1980, birth_month=1, filing_status="single",
                  life_expectancy=50, start_year=2026, assumptions=ZERO)
    values.update(kw)
    return PlanData(**values)


# ---------------------------------------------------------------------------
# A withdrawal strategy starting mid-year replaces only
# the months from its start month. $1M Roth, $60K/yr planned, 4% constant
# dollar; the start-year portfolio is $866,666.67, so the strategy is
# $34,666.67/yr.
# ---------------------------------------------------------------------------


def _strategy_spending(spec, **kw):
    p = _plan(birth_year=1970, life_expectancy=90,
              accounts={"roth": AccountInfo(1_000_000, "roth_ira")},
              drawdown_order=[DrawdownEntryData(1, "roth")],
              milestones=[MilestoneData(id="retire", name="Retire", trigger_type="date",
                                        trigger_date="2028-10-01")],
              expenses=[ExpenseData("living", "Living", 60_000, category="discretionary")],
              tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0}, **kw)
    return {s.year: s for s in run_simulation(p, withdrawal_strategy=spec).yearly_snapshots}


class TestStrategyStartMonth:
    def test_october_milestone(self):
        snaps = _strategy_spending(WithdrawalStrategySpec("constant_dollar", 0.04, start_milestone_id="retire"))
        # January-September planned ($45,000) + October-December strategy.
        assert snaps[2028].expenses == pytest.approx(45_000 + 34_666.67 * 3 / 12, abs=0.01)
        assert snaps[2028].strategy_spending == pytest.approx(53_666.67, abs=0.01)
        assert snaps[2028].planned_expenses == pytest.approx(60_000)
        assert snaps[2029].expenses == pytest.approx(34_666.67, abs=0.01)
        flows = {f.name: f.amount for f in snaps[2028].cash_flow.expenses}
        assert flows == {"Living": pytest.approx(45_000), "Strategy spending": pytest.approx(8_666.67, abs=0.01)}

    def test_start_age_uses_birthday_month(self):
        snaps = _strategy_spending(WithdrawalStrategySpec("constant_dollar", 0.04, start_age=58), birth_month=7)
        assert snaps[2028].expenses == pytest.approx(30_000 + 34_666.67 / 2, abs=0.01)

    def test_start_before_plan_is_full_year(self):
        snaps = _strategy_spending(WithdrawalStrategySpec("constant_dollar", 0.04, start_age=50), birth_month=7)
        assert snaps[2026].expenses == pytest.approx(40_000)


# ---------------------------------------------------------------------------
# A mid-year strategy start combined with "withdrawal_plus_income". In the
# start year the plan saves its own surplus for the months before the start;
# only the prorated withdrawal is spent on top. $120K salary ends at an October 2028
# retirement, $60K/yr spending: the 2026-2027 surplus leaves $1.12M, so the
# 4% strategy is $44,800/yr, $11,200 for October-December.
# ---------------------------------------------------------------------------


def _income_mode_year(retire_date):
    p = _plan(birth_year=1970, life_expectancy=90,
              accounts={"cash": AccountInfo(0, "checking"), "roth": AccountInfo(1_000_000, "roth_ira")},
              drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "roth")],
              milestones=[MilestoneData(id="retire", name="Retire", trigger_type="date", trigger_date=retire_date)],
              income_streams=[IncomeData("pay", "Salary", 120_000, end_milestone_id="retire",
                                         tax_category="employment")],
              expenses=[ExpenseData("living", "Living", 60_000, category="discretionary")],
              tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0})
    spec = WithdrawalStrategySpec("constant_dollar", 0.04, start_milestone_id="retire",
                                  income_handling="withdrawal_plus_income")
    return {s.year: s for s in run_simulation(p, withdrawal_strategy=spec).yearly_snapshots}


class TestIncomeModeStartYear:
    def test_october_start_saves_the_pre_start_surplus(self):
        snaps = _income_mode_year("2028-10-01")
        s = snaps[2028]
        assert s.expenses == pytest.approx(45_000 + 11_200)
        assert s.strategy_spending == pytest.approx(45_000 + 11_200)
        # $90,000 of salary less $56,200 spent is saved: $120,000 + $33,800.
        assert s.accounts["cash"] == pytest.approx(153_800)
        flows = {f.name: f.amount for f in s.cash_flow.expenses}
        assert flows == {"Living": pytest.approx(45_000), "Strategy spending": pytest.approx(11_200)}

    def test_later_years_spend_withdrawal_plus_income(self):
        # From 2029 there is no income: spending is the $44,800 withdrawal.
        assert _income_mode_year("2028-10-01")[2029].expenses == pytest.approx(44_800)

    def test_january_start_is_a_full_strategy_year(self):
        assert _income_mode_year("2028-01-01")[2028].expenses == pytest.approx(44_800)


# ---------------------------------------------------------------------------
# SEPP payments are sized on the prior year-end balance
# (Notice 2022-6), not after this year's growth, and agree with
# /sepp-preview. $1M IRA, 10% growth, age 50, 5% interest.
# ---------------------------------------------------------------------------


class TestSeppBalanceTiming:
    @pytest.mark.parametrize(("method", "expected"), [
        # 1M x 0.05 / (1 - 1.05^-36.2), Single Life Table factor 36.2 at 50.
        ("fixed_amortization", 60_312.23),
        ("rmd_method", 1_000_000 / 36.2),
    ])
    def test_first_payment(self, method, expected):
        p = _plan(birth_year=1976, life_expectancy=60,
                  assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.10, bond_return_rate=0.0),
                  accounts={"cash": AccountInfo(0, "checking"), "ira": AccountInfo(1_000_000, "traditional_ira")},
                  drawdown_order=[DrawdownEntryData(1, "cash")],
                  sepp_settings=SEPPSettingsData(enabled=True, method=method, source_account_id="ira",
                                                 start_age=50, interest_rate=0.05),
                  tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0})
        s = run_simulation(p).yearly_snapshots[0]
        sepp = sum(f.amount for f in s.cash_flow.income_sources if f.source == "sepp")
        assert sepp == pytest.approx(expected, abs=0.01)
        assert sepp == pytest.approx(calculate_sepp(1_000_000, 50, method, 0.05), abs=0.01)


# ---------------------------------------------------------------------------
# A gift in a surplus year is paid from the year's cash,
# not by selling brokerage shares. $200K salary, $100K spending, $20K gift,
# empty checking, $500K brokerage with $100K basis.
# ---------------------------------------------------------------------------


def _gift_year(salary, spending, **kw):
    p = _plan(income_streams=[IncomeData("pay", "Salary", salary, tax_category="employment")] if salary else [],
              expenses=[ExpenseData("live", "Living", spending, inflation_linked=False)],
              charity_entities=[CharityData("g", "Gift", "direct", 20_000)],
              accounts={"chk": AccountInfo(0, "checking"),
                        "brk": AccountInfo(500_000, "taxable_brokerage", cost_basis=100_000)},
              priorities=[PriorityData(1, "brk", allocation_mode="remaining")], **kw)
    return run_simulation(p).yearly_snapshots[0]


class TestCharityInSurplusYear:
    def test_surplus_pays_the_gift(self):
        s = _gift_year(200_000, 100_000, drawdown_order=[DrawdownEntryData(1, "chk"), DrawdownEntryData(2, "brk")])
        assert sum(d.amount for d in s.cash_flow.drawdowns if d.account_id == "brk") == 0.0
        assert s.capital_gains_tax == 0.0
        assert {e.name: e.amount for e in s.cash_flow.expenses}["Gift"] == pytest.approx(20_000)

    def test_deficit_sells_reserved_shares_without_a_withdrawal_order(self):
        # No income and no saved order: the gift is still sold from brokerage,
        # realizing 80% gain on $20,000 (basis $100K of $500K).
        s = _gift_year(0, 0)
        assert sum(d.amount for d in s.cash_flow.drawdowns if d.account_id == "brk") == pytest.approx(20_000)
        assert s.unfunded_expenses == 0.0
        assert s.accounts["brk"] == pytest.approx(480_000)


# ---------------------------------------------------------------------------
# Gift funding combined with tax-target withdrawals. A deficit first sells the
# shares reserved for the gift (gifts are funded before the tax-target pass);
# the pass then covers only the rest of the deficit.
# ---------------------------------------------------------------------------


class TestGiftDeficitWithTaxTarget:
    def test_gift_sale_precedes_the_tax_target_pass(self):
        p = _plan(birth_year=1964, life_expectancy=63, state_code="FL",
                  accounts={"broker": AccountInfo(500_000, "taxable_brokerage", cost_basis=250_000),
                            "ira": AccountInfo(500_000, "traditional_ira")},
                  drawdown_order=[DrawdownEntryData(1, "broker"), DrawdownEntryData(2, "ira")],
                  expenses=[ExpenseData("living", "Living", 80_000)],
                  charity_entities=[CharityData("g", "Gift", "direct", 20_000)],
                  tax_settings={"tax_target": {"kind": "federal_bracket", "bracket_rate": .12, "avoid_niit": True},
                                "blend_drawdown_to_tax_target": True})
        s = run_simulation(p).yearly_snapshots[0]
        assert {d.account_id: d.amount for d in s.cash_flow.drawdowns} == {"broker": pytest.approx(100_000)}
        # The $20,000 gift sale is not a tax-target withdrawal.
        assert s.tax_target_blended_withdrawals == pytest.approx(80_000)
        assert s.unfunded_expenses == 0.0
        assert s.expenses == pytest.approx(100_000)
