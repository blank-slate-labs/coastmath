"""Employer contributions are taxed by destination and by who funds them.

Employer money deposited into a Roth 401(k) is income in the contribution year
and basis when withdrawn; pre-tax employer money is not income. "Employer"
contributions funded from self-employment income are paid from profit,
deducted up to the Pub. 560 limit and reported as payroll funding, not extra
income.

Expected values come from the cited rules and published 2026 tables, not
from engine output. Plans use zero growth and inflation so each figure can be
checked by hand.
"""

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)
from tests.engine_support import year_snapshot

ZERO = AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0)


def _plan(**overrides) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1986, filing_status="single",
        life_expectancy=45, start_year=2026, assumptions=ZERO,
    )
    values.update(overrides)
    return PlanData(**values)


# ---------------------------------------------------------------------------
# Employer money deposited into a Roth 401(k)
# SECURE 2.0 sec. 604; IRS Notice 2024-2, section L.
# ---------------------------------------------------------------------------


def _employer_plan(target_type: str, employer_rate: float) -> PlanData:
    """$100K salary in 2026 only; 2027 spends $10K from the 401(k) at age 41."""
    return _plan(
        milestones=[MilestoneData("quit", "Quit", "date", trigger_date="2027-01-01")],
        income_streams=[IncomeData("pay", "Salary", 100_000, end_milestone_id="quit")],
        accounts={"cash": AccountInfo(0, "checking"), "k": AccountInfo(0, target_type)},
        priorities=[PriorityData(1, "k", priority_type="income_percent",
                                 source_income_id="pay", employer_match_rate=employer_rate)],
        drawdown_order=[DrawdownEntryData(1, "cash")],
        expenses=[ExpenseData("spend", "From 401(k)", 10_000, start_milestone_id="quit",
                              inflation_linked=False, specific_funding_source_ids=["k"])],
    )


class TestRothEmployerContributions:
    def test_roth_employer_money_is_income_in_the_contribution_year(self):
        base = year_snapshot(run_simulation(_employer_plan("roth_401k", 0.0)), 2026)
        roth = year_snapshot(run_simulation(_employer_plan("roth_401k", 0.10)), 2026)
        # Taxable income moves from $83,900 to $93,900, inside the 2026
        # single 22% bracket ($50,400-$105,700): +22% x $10,000.
        assert roth.federal_tax - base.federal_tax == pytest.approx(2_200.0)
        # Not FICA wages, and the deposit never passed through cash.
        assert roth.fica_tax == pytest.approx(base.fica_tax)
        assert roth.accounts["k"] == pytest.approx(10_000.0)
        assert base.accounts["cash"] - roth.accounts["cash"] == pytest.approx(2_200.0)

    def test_taxed_roth_employer_money_is_basis_when_withdrawn(self):
        withdrawal_year = year_snapshot(run_simulation(_employer_plan("roth_401k", 0.10)), 2027)
        assert withdrawal_year.taxes == pytest.approx(0.0)
        assert withdrawal_year.early_withdrawal_penalty == pytest.approx(0.0)
        assert withdrawal_year.accounts["k"] == pytest.approx(0.0)

    def test_pre_tax_employer_money_is_not_income_when_contributed(self):
        base = year_snapshot(run_simulation(_employer_plan("traditional_401k", 0.0)), 2026)
        pretax = year_snapshot(run_simulation(_employer_plan("traditional_401k", 0.10)), 2026)
        assert pretax.federal_tax == pytest.approx(base.federal_tax)
        assert pretax.accounts["cash"] == pytest.approx(base.accounts["cash"])
        assert pretax.accounts["k"] == pytest.approx(10_000.0)

    def test_only_roth_employer_money_adds_the_warning(self):
        text = "Employer contributions to a Roth 401(k) are taxed as income"
        roth = run_simulation(_employer_plan("roth_401k", 0.10)).metadata.warnings
        pretax = run_simulation(_employer_plan("traditional_401k", 0.10)).metadata.warnings
        assert any(text in warning for warning in roth)
        assert not any(text in warning for warning in pretax)


# ---------------------------------------------------------------------------
# "employer" contributions funded by self-employment income
# Pub. 560 rate table for the self-employed; Treas. Reg. 1.199A-3(b)(1)(vi).
# ---------------------------------------------------------------------------

# $100,000 net profit: SE earnings 92,350; SE tax 14,129.55; deductible half
# 7,064.775. Pub. 560 limit = 20% x (100,000 - 7,064.775) = 18,587.045.
SE_TAX = 14_129.55
PROFIT_SHARING_LIMIT = 18_587.045


def _self_employed_plan(employer_rate: float, employee_rate: float = 0.0, **overrides) -> PlanData:
    values = dict(
        income_streams=[IncomeData("biz", "Consulting", 100_000, tax_category="self_employment")],
        accounts={"cash": AccountInfo(0, "checking"), "k": AccountInfo(0, "traditional_401k")},
        priorities=[PriorityData(1, "k", priority_type="income_percent", source_income_id="biz",
                                 employee_rate=employee_rate, employer_match_rate=employer_rate)],
        drawdown_order=[DrawdownEntryData(1, "cash")],
    )
    values.update(overrides)
    return _plan(**values)


class TestSelfEmployedEmployerContributions:
    def test_contribution_is_paid_from_profit_and_deducted_up_to_the_pub_560_limit(self):
        year = run_simulation(_self_employed_plan(0.20)).yearly_snapshots[0]
        # AGI 100,000 - 7,064.775 - 18,587.045 = 74,348.18; taxable before QBI
        # 58,248.18. QBI 74,348.18 -> deduction min(14,869.64, 11,649.64).
        # Taxable 46,598.544: 1,240 + 12% x 34,198.544 = 5,343.825.
        assert year.accounts["k"] == pytest.approx(PROFIT_SHARING_LIMIT)
        assert year.federal_tax == pytest.approx(5_343.825)
        assert year.fica_tax == pytest.approx(SE_TAX)  # SE tax ignores the deduction
        assert year.accounts["cash"] == pytest.approx(100_000 - SE_TAX - 5_343.825 - PROFIT_SHARING_LIMIT)

    def test_contribution_below_the_limit_is_taken_as_requested(self):
        year = run_simulation(_self_employed_plan(0.10)).yearly_snapshots[0]
        # AGI 82,935.225; taxable before QBI 66,835.225; QBI deduction
        # min(16,587.045, 13,367.045). Taxable 53,468.18:
        # 5,800 + 22% x 3,068.18 = 6,475.00.
        assert year.accounts["k"] == pytest.approx(10_000.0)
        assert year.federal_tax == pytest.approx(6_475.0, abs=0.01)
        assert year.accounts["cash"] == pytest.approx(100_000 - SE_TAX - 6_475.0 - 10_000, abs=0.01)

    def test_net_worth_rises_only_by_the_tax_saved(self):
        without = run_simulation(_self_employed_plan(0.0)).yearly_snapshots[0]
        with_plan = run_simulation(_self_employed_plan(0.20)).yearly_snapshots[0]
        # Without the plan: taxable 61,468.18 -> 8,235.00 federal tax.
        assert without.federal_tax == pytest.approx(8_235.0, abs=0.01)
        assert with_plan.net_worth - without.net_worth == pytest.approx(8_235.0 - 5_343.825, abs=0.01)

    def test_cash_flow_reports_payroll_funding_not_extra_income(self):
        flow = run_simulation(_self_employed_plan(0.20)).yearly_snapshots[0].cash_flow
        assert flow.gross_income == pytest.approx(100_000.0)
        assert not any("Employer" in source.name for source in flow.income_sources)
        assert flow.payroll_deductions == pytest.approx(PROFIT_SHARING_LIMIT)
        assert [(c.source, c.category, round(c.amount, 3)) for c in flow.contributions
                if c.account_id == "k"] == [("payroll", "pretax", round(PROFIT_SHARING_LIMIT, 3))]

    def test_roth_destination_leaves_cash_without_a_deduction(self):
        base = run_simulation(_self_employed_plan(0.0)).yearly_snapshots[0]
        roth = run_simulation(_self_employed_plan(0.10, accounts={
            "cash": AccountInfo(0, "checking"), "k": AccountInfo(0, "roth_401k")})).yearly_snapshots[0]
        assert roth.accounts["k"] == pytest.approx(10_000.0)
        assert roth.federal_tax == pytest.approx(base.federal_tax)
        assert base.accounts["cash"] - roth.accounts["cash"] == pytest.approx(10_000.0)

    def test_self_employed_deferrals_do_not_reduce_w2_wages_for_local_tax(self):
        plan = _plan(
            state_code="MO", local_tax={"jurisdiction": "mo_kansas_city"},
            income_streams=[IncomeData("pay", "Salary", 50_000),
                            IncomeData("biz", "Consulting", 50_000, tax_category="self_employment")],
            accounts={"cash": AccountInfo(0, "checking"), "k": AccountInfo(0, "traditional_401k")},
            priorities=[PriorityData(1, "k", priority_type="income_percent", source_income_id="biz",
                                     employee_rate=0.20)],
            drawdown_order=[DrawdownEntryData(1, "cash")],
        )
        year = run_simulation(plan).yearly_snapshots[0]
        # Kansas City earnings tax: 1% of W-2 wages plus business profit.
        assert year.accounts["k"] == pytest.approx(10_000.0)
        assert year.local_tax == pytest.approx(1_000.0)
