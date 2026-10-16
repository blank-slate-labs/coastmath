"""FIRE feedback regressions with independently balanced cash ledgers."""
import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
)


def retirement_plan(**overrides):
    values = dict(plan_id="00000000-0000-0000-0000-000000000001", start_year=2026,
                  birth_year=1960, life_expectancy=67, filing_status="single",
                  assumptions=AssumptionData(0, 0, 0),
                  accounts={"ira": AccountInfo(1000000, "traditional_ira", name="Retirement")},
                  drawdown_order=[DrawdownEntryData(1, "ira")],
                  expenses=[ExpenseData("spend", "Living", 80000)],
                  tax_settings={"mode": "flat", "ordinary_income_tax_rate": .2})
    values.update(overrides)
    return PlanData(**values)


@pytest.mark.parametrize("age", [46, 66, 76])
@pytest.mark.parametrize("withholding", [0, .1, .3])
def test_retirement_cash_sources_are_counted_once(age, withholding):
    s = run_simulation(retirement_plan(birth_year=2026-age, life_expectancy=age+1,
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": .2,
                      "tax_deferred_withholding_rate": withholding})).yearly_snapshots[0]
    cf = s.cash_flow
    assert cf.gross_income == pytest.approx(sum(i.amount for i in cf.income_sources))
    receipts = cf.gross_income + sum(d.amount for d in cf.drawdowns) + cf.tax_delta
    uses = (sum(e.amount for e in cf.expenses) + cf.tax_withheld
            + cf.early_withdrawal_penalty + sum(c.amount for c in cf.contributions))
    assert receipts == pytest.approx(uses, abs=.02)
    assert s.net_worth == pytest.approx(1000000 - 80000 - s.taxes, abs=.02)
    assert len(cf.drawdowns) == 1
    assert cf.drawdowns[0].account_id == "ira"
    assert cf.drawdowns[0].account_name == "Retirement"
    assert cf.drawdowns[0].amount > .005
    mandatory = sum(i.amount for i in cf.income_sources if i.source in {"rmd", "sepp"})
    assert mandatory + sum(d.amount for d in cf.drawdowns) == pytest.approx(1000000 - s.accounts["ira"], abs=.02)
    if age == 76:
        assert mandatory > 0
    assert s.effective_rate == pytest.approx(s.taxes / s.gross_income)
    assert s.taxes == pytest.approx(s.federal_tax + s.state_tax + s.local_tax
        + s.capital_gains_tax + s.fica_tax + s.niit_tax + s.early_withdrawal_penalty)


def test_reinvested_dividends_are_not_unallocated_spendable_surplus():
    s = run_simulation(retirement_plan(accounts={"b": AccountInfo(300000, "taxable_brokerage", cost_basis=300000)},
        income_streams=[IncomeData("pay", "Pay", 150000)], drawdown_order=[DrawdownEntryData(1, "b")],
        assumptions=AssumptionData(0, 0, 0, stock_dividend_yield=.02),
        priorities=[PriorityData(1, "b", allocation_mode="remaining")])).yearly_snapshots[0]
    cf = s.cash_flow
    # Opening balance yields $6K; new deposits also earn monthly dividends.
    factor = sum(1.02 ** (month / 12) for month in range(12)) / 12 - 1
    expected_dividends = 6000 + 38800 * factor
    assert sum(c.amount for c in cf.contributions if c.source == "reinvestment") == pytest.approx(expected_dividends)
    # Additional reinvested dividends require a small tax-funding withdrawal.
    assert sum(d.amount for d in cf.drawdowns) == pytest.approx((expected_dividends - 6000) * .2)
    assert cf.gross_income + sum(d.amount for d in cf.drawdowns) + cf.tax_delta == pytest.approx(cf.tax_withheld + sum(e.amount for e in cf.expenses)
        + sum(c.amount for c in cf.contributions), abs=.02)
    assert not any(c.source == "default_sink" for c in cf.contributions)


def test_remaining_rule_receives_final_tax_refund_without_reusing_caps():
    result = run_simulation(retirement_plan(accounts={"t": AccountInfo(0, "traditional_401k"),
        "b": AccountInfo(0, "taxable_brokerage"), "cash": AccountInfo(0, "checking")},
        assumptions=AssumptionData(0, .1, 0), life_expectancy=68,
        income_streams=[IncomeData("pay", "Pay", 150000)],
        priorities=[PriorityData(1, "t", 10000), PriorityData(2, "b", allocation_mode="remaining")]
    ))
    s = result.yearly_snapshots[0]
    factor = sum(1.1 ** (month / 12) for month in range(12)) / 12
    assert s.accounts["t"] == pytest.approx(10000 * factor)
    assert s.accounts["b"] == pytest.approx(30000 * factor + 2000)
    assert s.accounts["cash"] == 0
    assert sum(c.amount for c in s.cash_flow.contributions if c.priority_rank == 2) == pytest.approx(32000)
    # The 2k year-end refund earns no first-year growth, then earns the
    # brokerage's 10% return next year along with the other 30k invested.
    assert result.yearly_snapshots[1].accounts["b"] == pytest.approx(s.accounts["b"] * 1.1 + 30000 * factor + 2000)
    assert result.yearly_snapshots[1].accounts["t"] == pytest.approx(s.accounts["t"] * 1.1 + 10000 * factor)


def test_spouse_accounts_without_partner_are_flagged_without_rewriting_inputs():
    p = retirement_plan(accounts={"r": AccountInfo(1000000, "roth_ira", owner="spouse")},
                        drawdown_order=[DrawdownEntryData(1, "r")])
    result = run_simulation(p)
    assert any(w.startswith("Household mismatch:") for w in result.metadata.warnings)
    assert p.accounts["r"].owner == "spouse"
