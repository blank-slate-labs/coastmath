"""IRMAA ranges for married-filing-separately filers who lived apart.

20 CFR 418.1115(b) and 418.2115 give separate filers who lived apart from
their spouse for the entire tax year the individual MAGI ranges; only those
who lived together at any time use the married-separate ranges (418.1115(d)).
2026 amounts (CMS-8089-N/CMS-8091-N): individual tier 1 is $109,000-$137,000
with Part B +$81.20/mo and Part D +$14.50/mo; married-separate tier 1 is
$109,000-$391,000 with Part B +$446.30/mo and Part D +$83.30/mo.
"""
import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    IncomeData,
    PlanData,
)

MEDICARE = {"medicare_part_b": True, "medicare_part_d": True, "medicare_apply_irmaa": True}


def plan(filing_status, healthcare, lived_apart=None):
    return PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1959, birth_month=1, filing_status=filing_status,
        life_expectancy=95, spouse_birth_year=1959, spouse_birth_month=1, spouse_life_expectancy=95,
        start_year=2026, milestones=[], expenses=[], priorities=[],
        income_streams=[IncomeData(id="p", name="Pension", annual_amount=120_000, is_earned_income=False)],
        drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts={"cash": AccountInfo(balance=3_000_000, account_type="checking")},
        healthcare_settings={"enabled": True, "aca_enabled": False,
                             "magi_prior_year": 120_000, "magi_two_years_prior": 120_000, **healthcare},
        tax_settings=None if lived_apart is None else {"mfs_lived_apart_all_year": lived_apart},
    )


HOUSEHOLD = {"medicare_enabled": True, **MEDICARE}
PER_PERSON = {"persons": [
    {"owner": "self", "mode": "coverage", **MEDICARE},
    {"owner": "spouse", "mode": "itemized", "itemized_annual_amount": 0},
]}


@pytest.mark.parametrize("healthcare,people", [(HOUSEHOLD, 2), (PER_PERSON, 1)])
@pytest.mark.parametrize("filing_status,lived_apart,part_b_add,part_d_add", [
    # $120,000 lookback MAGI: individual tier 1 vs married-separate tier 1.
    ("married_filing_separately", True, 81.20, 14.50),
    ("married_filing_separately", False, 446.30, 83.30),
    ("married_filing_separately", None, 446.30, 83.30),
    ("single", None, 81.20, 14.50),
])
def test_irmaa_uses_individual_ranges_for_separate_filers_who_lived_apart(
        healthcare, people, filing_status, lived_apart, part_b_add, part_d_add):
    hc = run_simulation(plan(filing_status, healthcare, lived_apart)).yearly_snapshots[0].healthcare
    assert hc.medicare_persons == people
    assert hc.medicare_tier == 1
    assert hc.medicare_irmaa_part_b == pytest.approx(part_b_add * 12 * people)
    assert hc.medicare_irmaa_part_d == pytest.approx(part_d_add * 12 * people)
    assert hc.medicare_lookback_filing_status == filing_status
