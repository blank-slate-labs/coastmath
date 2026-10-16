"""Pennsylvania taxes employee retirement contributions.

PA DOR Personal Income Tax Guide, Gross Compensation: "Employee contributions
to any retirement plan are always taxable as compensation", including IRC 401
deferrals; PA-40 has no IRA deduction. Section 125 health and HSA amounts stay
excluded as they are federally. PA's 3.07% flat rate has no standard
deduction, so every expected value is 3.07% of the compensation PA taxes.
"""

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
from tests.engine_support import contributed

PA_RATE = 0.0307
WAGE = 100_000.0


def _first_year(*, payroll_type=None, payroll_rate=0.0, ira=0.0):
    accounts = {"chk": AccountInfo(balance=50_000, account_type="checking", name="Chk")}
    priorities = []
    if payroll_type:
        accounts["payroll"] = AccountInfo(balance=0, account_type=payroll_type, name="Payroll")
        priorities.append(PriorityData(priority_rank=1, priority_type="income_percent",
                                       target_account_id="payroll", source_income_id="w",
                                       employee_rate=payroll_rate))
    if ira:
        accounts["ira"] = AccountInfo(balance=0, account_type="traditional_ira", name="IRA")
        priorities.append(PriorityData(priority_rank=2, target_account_id="ira",
                                       allocation_mode="amount", allocation_value=ira,
                                       max_annual_amount=ira))
    plan = PlanData(
        plan_id="00000000-0000-0000-0000-000000000026", birth_year=1986, birth_month=3,
        filing_status="single", life_expectancy=41, start_year=2026, state_code="PA",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts=accounts,
        income_streams=[IncomeData(id="w", name="Wage", annual_amount=WAGE, growth_rate=0.0)],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000, inflation_linked=False)],
        priorities=priorities, drawdown_order=[DrawdownEntryData(1, "chk")],
    )
    return run_simulation(plan).yearly_snapshots[0]


@pytest.mark.parametrize(("payroll_type", "rate", "ira", "account", "amount"), [
    (None, 0.0, 0.0, None, 0.0),
    ("traditional_401k", 0.10, 0.0, "payroll", 10_000.0),
    # 24.5% of $100,000 is exactly the 2026 402(g) limit of $24,500.
    ("traditional_401k", 0.245, 0.0, "payroll", 24_500.0),
    (None, 0.0, 7_500.0, "ira", 7_500.0),
])
def test_pa_base_includes_retirement_contributions(payroll_type, rate, ira, account, amount):
    snapshot = _first_year(payroll_type=payroll_type, payroll_rate=rate, ira=ira)
    if account:
        assert contributed(snapshot, account) == pytest.approx(amount)
    # 3.07% x $100,000 = $3,070.00 regardless of the contribution.
    assert snapshot.state_tax == pytest.approx(3_070.00, abs=0.01)


def test_pa_keeps_hsa_payroll_contributions_excluded():
    snapshot = _first_year(payroll_type="hsa", payroll_rate=0.04)
    assert contributed(snapshot, "payroll") == pytest.approx(4_000.0)
    # 3.07% x ($100,000 - $4,000) = $2,947.20.
    assert snapshot.state_tax == pytest.approx(2_947.20, abs=0.01)
