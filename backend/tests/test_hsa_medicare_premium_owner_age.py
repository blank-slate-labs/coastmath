"""Medicare premiums are qualified HSA expenses only for an owner 65+.

IRC 223(d)(2)(C)(iv) (https://www.law.cornell.edu/uscode/text/26/223) lets an
HSA pay insurance premiums only for "an account beneficiary who has attained"
65. IRS Publication 969 (2025), "Insurance premiums"
(https://www.irs.gov/publications/p969): "if you, the account beneficiary,
aren't 65 or older, Medicare premiums for coverage of your spouse ... aren't
generally qualified medical expenses." The beneficiary's age decides.

Household: 2026, TX, MFJ, no growth or inflation. Self born January 1963
(63), spouse born January 1960 (66, on Medicare: Part B 12 x $202.90 =
$2,434.80, Part D off). $50,000 qualified pension, $80,000 expenses.
Deductions 32,200 standard + 1,650 (spouse 65+) + 6,000 senior = 39,850, so
federal tax on HSA taxable income T is 2,480 + 12% x (50,000 + T - 39,850 -
24,800) = 722 + 0.12 T while taxable income stays in the 12% bracket.
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
)

PART_B = 12 * 202.90


def _plan(accounts, order):
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000050",
        birth_year=1963, birth_month=1, spouse_birth_year=1960, spouse_birth_month=1,
        spouse_life_expectancy=95, filing_status="married_filing_jointly", life_expectancy=95,
        start_year=2026, state_code="TX",
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0,
                                   bond_return_rate=0.0, stock_dividend_yield=0.0),
        accounts={"chk": AccountInfo(0, "checking", name="chk"), **accounts},
        drawdown_order=[DrawdownEntryData(1, "chk")]
        + [DrawdownEntryData(rank, aid) for rank, aid in enumerate(order, start=2)],
        income_streams=[IncomeData(id="p", name="Pension", annual_amount=50000, is_earned_income=False,
                                   tax_category="qualified_pension", growth_rate=0.0)],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=80000)],
        healthcare_settings={"enabled": True, "medicare_enabled": True, "medicare_part_d": False},
        tax_settings={"cash_flow_frequency": "annual"},
    )


def _first_year(plan):
    return run_simulation(plan).yearly_snapshots[0]


def test_under_65_owner_cannot_reimburse_spouse_medicare_premiums():
    # Need 80,000 + 2,434.80 - 50,000 = 32,434.80. Nothing qualifies, so the
    # whole withdrawal W is income plus the 20% additional tax:
    # W - 0.20 W - (722 + 0.12 W) = 32,434.80 -> W = 33,156.80 / 0.68 = 48,760.
    s = _first_year(_plan({"hsa": AccountInfo(200000, "hsa", name="hsa", owner="self")}, ["hsa"]))
    assert s.healthcare.medicare_part_b == pytest.approx(PART_B)
    assert sum(d.amount for d in s.cash_flow.drawdowns) == pytest.approx(48760.00, abs=0.01)
    assert s.gross_income == pytest.approx(98760.00, abs=0.01)
    assert s.federal_tax == pytest.approx(722 + 0.12 * 48760, abs=0.01)  # 6,573.20
    assert s.taxes == pytest.approx(6573.20 + 0.20 * 48760, abs=0.01)  # 16,325.20


def test_65_plus_owner_still_reimburses_the_premiums():
    # Control: the 66-year-old owns the HSA, so the $2,434.80 stays untaxed
    # and there is no additional tax. T = 30,000 + 0.12 T + 722 -> T =
    # 30,722 / 0.88 = 34,911.36; federal 722 + 0.12 T = 4,911.36.
    s = _first_year(_plan({"hsa": AccountInfo(200000, "hsa", name="hsa", owner="spouse")}, ["hsa"]))
    taxable = 30722 / 0.88
    assert sum(d.amount for d in s.cash_flow.drawdowns) == pytest.approx(PART_B + taxable, abs=0.01)
    assert s.federal_tax == pytest.approx(722 + 0.12 * taxable, abs=0.01)
    assert s.taxes == pytest.approx(s.federal_tax, abs=0.01)


def test_premiums_stay_available_to_the_older_owners_hsa():
    # The 63-year-old's $10,000 HSA is drawn first and all of it is taxable
    # (penalty 2,000, net 8,000). The 66-year-old's HSA then reimburses the
    # premiums untaxed and draws T2 more, taxable without penalty:
    # 8,000 + 2,434.80 + T2 = 32,434.80 + 722 + 0.12 (10,000 + T2)
    # -> 0.88 T2 = 23,922 -> T2 = 27,184.09.
    s = _first_year(_plan({
        "young": AccountInfo(10000, "hsa", name="young", owner="self"),
        "old": AccountInfo(200000, "hsa", name="old", owner="spouse"),
    }, ["young", "old"]))
    t2 = 23922 / 0.88
    drawn = {d.name: d.amount for d in s.cash_flow.drawdowns}
    assert drawn["young"] == pytest.approx(10000, abs=0.01)
    assert drawn["old"] == pytest.approx(PART_B + t2, abs=0.01)
    assert s.federal_tax == pytest.approx(722 + 0.12 * (10000 + t2), abs=0.01)
    assert s.taxes == pytest.approx(s.federal_tax + 2000, abs=0.01)
