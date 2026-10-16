"""New Jersey taxes traditional IRA contributions.

NJ Division of Taxation GIT-2 (IRA Withdrawals): "The New Jersey Gross Income
Tax Act does not contain any provisions similar to the Internal Revenue Code
that allow an individual to deduct contributions to an IRA. Contributions to
an IRA are subject to New Jersey Income Tax in the year they are made." NJ
still excludes 401(k) elective deferrals (N.J.S.A. 54A:6-21).

NJ single schedule (no standard deduction; the engine omits the $1,000
exemption): 1.4% to $20,000, 1.75% to $35,000, 3.5% to $40,000, 5.525% to
$75,000, 6.37% to $500,000.
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

WAGE = 100_000.0
# 20,000 x 1.4% + 15,000 x 1.75% + 5,000 x 3.5% + 35,000 x 5.525% = 2,651.25
# below $75,000; 6.37% above it.
NJ_TAX_AT_75K = 280.00 + 262.50 + 175.00 + 1_933.75


def _first_year(*, payroll_401k_rate=0.0, ira=0.0, state_code="NJ"):
    accounts = {"chk": AccountInfo(balance=50_000, account_type="checking", name="Chk")}
    priorities = []
    if payroll_401k_rate:
        accounts["k"] = AccountInfo(balance=0, account_type="traditional_401k", name="401k")
        priorities.append(PriorityData(priority_rank=1, priority_type="income_percent",
                                       target_account_id="k", source_income_id="w",
                                       employee_rate=payroll_401k_rate))
    if ira:
        accounts["ira"] = AccountInfo(balance=0, account_type="traditional_ira", name="IRA")
        priorities.append(PriorityData(priority_rank=2, target_account_id="ira",
                                       allocation_mode="amount", allocation_value=ira,
                                       max_annual_amount=ira))
    plan = PlanData(
        plan_id="00000000-0000-0000-0000-000000000041", birth_year=1986, birth_month=3,
        filing_status="single", life_expectancy=41, start_year=2026, state_code=state_code,
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts=accounts,
        income_streams=[IncomeData(id="w", name="Wage", annual_amount=WAGE, growth_rate=0.0)],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000, inflation_linked=False)],
        priorities=priorities, drawdown_order=[DrawdownEntryData(1, "chk")],
    )
    return run_simulation(plan).yearly_snapshots[0]


@pytest.mark.parametrize("ira", [0.0, 7_500.0])
def test_nj_base_includes_traditional_ira_contribution(ira):
    snapshot = _first_year(ira=ira)
    if ira:
        assert contributed(snapshot, "ira") == pytest.approx(ira)
    # $2,651.25 + 25,000 x 6.37% = $4,243.75 whether or not the IRA is funded.
    assert snapshot.state_tax == pytest.approx(NJ_TAX_AT_75K + 1_592.50, abs=0.01)


def test_nj_ira_contribution_still_reduces_federal_tax():
    without, with_ira = _first_year(), _first_year(ira=7_500.0)
    # IRC 219 deduction at the 22% marginal rate: 7,500 x 22% = 1,650.
    assert without.federal_tax - with_ira.federal_tax == pytest.approx(1_650.0, abs=0.01)


@pytest.mark.parametrize("ira", [0.0, 7_500.0])
def test_nj_keeps_401k_deferrals_excluded(ira):
    snapshot = _first_year(payroll_401k_rate=0.10, ira=ira)
    assert contributed(snapshot, "k") == pytest.approx(10_000.0)
    # Base $90,000: $2,651.25 + 15,000 x 6.37% = $3,606.75; the IRA adds back.
    assert snapshot.state_tax == pytest.approx(NJ_TAX_AT_75K + 955.50, abs=0.01)


# M.G.L. c.62 s.2(d)(1)(F) disallows the IRC 219 IRA deduction for
# Massachusetts; 401(k) deferrals stay excluded (s.2(a) follows federal gross
# income). MA is a flat 5%; the engine omits the $4,400 personal exemption.
@pytest.mark.parametrize("ira", [0.0, 7_500.0])
def test_ma_base_includes_traditional_ira_contribution(ira):
    snapshot = _first_year(ira=ira, state_code="MA")
    if ira:
        assert contributed(snapshot, "ira") == pytest.approx(ira)
    # 100,000 x 5% = 5,000 whether or not the IRA is funded.
    assert snapshot.state_tax == pytest.approx(5_000.0, abs=0.01)


@pytest.mark.parametrize("ira", [0.0, 7_500.0])
def test_ma_keeps_401k_deferrals_excluded(ira):
    snapshot = _first_year(payroll_401k_rate=0.10, ira=ira, state_code="MA")
    assert contributed(snapshot, "k") == pytest.approx(10_000.0)
    # Base $90,000 x 5% = $4,500; the IRA adds back.
    assert snapshot.state_tax == pytest.approx(4_500.0, abs=0.01)
