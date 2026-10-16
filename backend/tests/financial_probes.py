"""Independent financial-engine probes: hand-derived expectations for ledger,
tax-year, ownership and funding cases (tests/test_financial_accuracy.py).

Run from backend/ with ``python -m tests.financial_probes`` to print every row.
MISMATCH is a finding, not an assertion that the current output is correct.
Flat 20% tax examples intentionally isolate accounting from US tax brackets.
"""
from __future__ import annotations

import json
import math

from coastmath.engine.amortization import calculate_fixed_payment, calculate_year
from coastmath.engine.cost_basis import calculate_gain_on_withdrawal
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
    RealAssetData,
    SimState,
)
from coastmath.engine.waterfall import allocate_surplus


def plan(**overrides):
    values = dict(
        plan_id="00000000-0000-0000-0000-000000000001", birth_year=1966,
        filing_status="single", life_expectancy=61, start_year=2026,
        assumptions=AssumptionData(0, 0, 0),
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": .2,
                      "capital_gains_tax_rate": .2},
        accounts={"cash": AccountInfo(100000, "checking")},
        drawdown_order=[DrawdownEntryData(1, "cash")],
    )
    values.update(overrides)
    return PlanData(**values)


def first(p):
    return run_simulation(p).yearly_snapshots[0]


def run_probes():
    rows = []

    def record(name, actual, expected, reason, control=False):
        matches = (actual == expected if isinstance(expected, bool)
                   else math.isclose(actual, expected, abs_tol=.02, rel_tol=0))
        rows.append(dict(name=name, actual=actual, expected=expected,
                         status="MATCH" if matches else "MISMATCH",
                         control=control, expectation=reason))

    ira = {"ira": AccountInfo(100000, "traditional_ira")}
    order = [DrawdownEntryData(1, "ira")]
    for withholding in [0, .2]:
        p = plan(accounts=ira, drawdown_order=order,
                 expenses=[ExpenseData("e", "Spending", 8000)],
                 tax_settings={"mode": "flat", "ordinary_income_tax_rate": .2,
                               "tax_deferred_withholding_rate": withholding})
        record(f"IRA same-year withholding {withholding}", first(p).net_worth,
               90000, "8000 / (1 - .20) = 10000 gross withdrawal; withholding is a tax payment.",
               control=withholding == 0)

    p = plan(accounts={"cash": AccountInfo(0, "checking")},
             real_assets=[RealAssetData("a", "Asset", 100000,
                 annual_appreciation_rate=0, auto_liquidate_on_depletion=True,
                 liquidation_target_account_id="cash")],
             expenses=[ExpenseData("e", "Spending", 30000)])
    record("Auto-liquidation must pay spending", first(p).net_worth, 70000,
           "100000 sale proceeds minus 30000 spending; zero growth, debt and gains.")

    p = plan(accounts={"ira": AccountInfo(10000, "traditional_ira")},
             drawdown_order=order, expenses=[ExpenseData("e", "Spending", 9000)])
    record("Unfunded tax must fail", run_simulation(p).metadata.success, False,
           "10000 pretax assets can fund only 8000 spending at 20% tax, not 9000.")

    p = plan(accounts={"cash": AccountInfo(0, "checking"),
                       "r": AccountInfo(0, "roth_401k")},
             income_streams=[IncomeData("pay", "Salary", 100000)],
             priorities=[PriorityData(1, "r", priority_type="income_percent",
                         source_income_id="pay", employee_rate=.1)])
    record("Roth payroll income tax", first(p).taxes, 20000,
           "Roth employee contributions do not reduce the 100000 ordinary tax base.")

    p = plan(accounts=ira, drawdown_order=order,
             expenses=[ExpenseData("e", "Spending", 20000,
                                   specific_funding_source_id="ira")])
    record("Specific-source IRA spending", first(p).net_worth, 75000,
           "20000 net spending requires 25000 gross pretax distribution at 20% tax.")

    p = plan(life_expectancy=62,
             real_assets=[RealAssetData("a", "Investment asset", 100000,
                 annual_appreciation_rate=.1, sale_year=2027, sale_month=1,
                 liquidation_target_account_id="cash")])
    r = run_simulation(p)
    record("Scheduled sale recognizes gain", r.yearly_snapshots[1].taxes, 2000,
           "Assume initial adjusted basis 100000: sale at 110000 creates 10000 gain at 20%.")

    p = plan(income_streams=[IncomeData("pay", "Salary", 100000)],
             tax_settings={"mode": "flat", "ordinary_income_tax_rate": .2,
                           "settlement_lag_years": 1})
    record("Net worth includes accrued tax payable", first(p).net_worth, 180000,
           "100000 opening cash + 100000 pay - 20000 accrued tax; cash may remain 200000.")

    p = plan(accounts={"ira": AccountInfo(10000, "traditional_ira")},
             drawdown_order=order, expenses=[ExpenseData("e", "Spending", 11200)],
             assumptions=AssumptionData(0, .12, 0),
             tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0,
                           "cash_flow_frequency": "monthly"})
    monthly = 1.12 ** (1 / 12) - 1
    balance = 10000
    for _ in range(12):
        balance = balance * (1 + monthly) - 11200 / 12
    record("Monthly withdrawals detect depletion", run_simulation(p).metadata.success,
           False, f"Independent monthly recurrence ends at {balance:.6f}; shortfall must fail.")

    state = SimState(2026, accounts={"r1": AccountInfo(0, "roth_ira"),
                                    "r2": AccountInfo(0, "roth_ira")})
    allocation = allocate_surplus(20000, [PriorityData(1, "r1"), PriorityData(2, "r2")],
                                  state, age=35, filing_status="single", modified_agi=50000)
    record("Same-owner combined IRA contribution limit", sum(allocation.values()),
           7500, "2026 under-50 limit is shared across all traditional and Roth IRAs; assume sufficient compensation.")

    p = plan(filing_status="married_filing_jointly", tax_settings=None,
             spouse_birth_year=1966,
             income_streams=[IncomeData("a", "Self salary", 100000),
                             IncomeData("b", "Spouse salary", 100000, owner="spouse")])
    record("Two-earner FICA", first(p).fica_tax, 15300,
           "Each worker earns less than the SS wage base: 2 * 100000 * (.062 + .0145).")

    p = plan(income_streams=[IncomeData("a", "Salary", 120000)], tax_settings=None)
    full_tax = first(p).taxes
    p.first_year_fraction = .5
    # New inputs state the history that the original audit could not encode.
    p.tax_settings = {"year_to_date": {"tax_year": 2026, "gross_income": 60000,
        "w2_income_by_owner": {"self": 60000}, "tax_paid": 9610}}
    partial_tax = first(p).taxes - 9610
    record("Midyear tax with prior earnings and payments", partial_tax,
           full_tax - 9610,
           "Specified scenario: earned 60000 and paid 9610 before start; full-year tax 26750, remaining liability 17140. Model has no YTD inputs.")

    p = plan(accounts={"cash": AccountInfo(10000, "checking"),
                       "b": AccountInfo(100000, "taxable_brokerage", 100000)},
             assumptions=AssumptionData(0, .06, 0, .02))
    record("Historical total return retains dividend tax",
           run_simulation(p, override_returns={2026: (.08, 0, 0)}).yearly_snapshots[0].net_worth,
           117600, "Specify 8% total return = 6% price + 2% qualified dividends. Growth 8000, current tax 400; override lacks yield decomposition.")
    record("Deterministic dividend control", first(p).net_worth, 117600,
           "Same explicit 6% price and 2% dividend example.", control=True)

    gain, _ = calculate_gain_on_withdrawal(40000, 80000, 100000)
    record("Realized capital loss", gain, -10000,
           "Selling half of an 80000 position with 100000 total basis realizes a 10000 loss.")

    expected_debt = 100000 * 1.01 ** 12 - 500 * (1.01 ** 12 - 1) / .01
    record("Unpaid loan interest remains owed", calculate_year(100000, .12, 500).remaining_balance,
           expected_debt, "Specify monthly capitalization: B[m+1] = B[m] * 1.01 - 500. Other loan terms still require tracking unpaid interest.")
    record("Standard mortgage control", calculate_fixed_payment(300000, .065, 360),
           1896.204070478896, "Standard 30-year fixed mortgage formula.", control=True)
    return rows


if __name__ == "__main__":
    print(json.dumps(run_probes(), indent=2))
