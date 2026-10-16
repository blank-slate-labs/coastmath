"""State retirement-income exclusions (``coastmath.engine.state_retirement_exclusion``).

Each case is hand-computed from the rule in ``data/tax_brackets_2026.json``.
Sources are in ``_sources`` in ``tax_brackets_2026.json`` ("State
retirement-income exclusions") and in each test's docstring. Unless a case
says otherwise, amounts are 2026 dollars (inflation factor 1.0), the return
is single, and federal AGI equals the covered income.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.state_retirement_exclusion import (
    RetirementIncome,
    state_retirement_exclusion,
)
from coastmath.engine.tax_engine import calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    PriorityData,
    ResidencyPeriodData,
)

_STATES = json.loads((Path(__file__).resolve().parents[1] / "coastmath" / "data" / "tax_brackets_2026.json").read_text())["state"]
MFJ = "married_filing_jointly"


def person(age, social_security=0.0, **amounts):
    return RetirementIncome(age=age, amounts=amounts, social_security=social_security)


def exclusion(state, *persons, status="single", agi=None, taxable_ss=0.0, factor=1.0):
    ss = sum(p.social_security for p in persons)
    if agi is None:
        agi = sum(sum(p.amounts.values()) for p in persons) + taxable_ss
    return state_retirement_exclusion(
        _STATES[state]["retirement_income_exclusion"], persons, status, federal_agi=agi,
        taxable_social_security=taxable_ss, social_security_income=ss, inflation_factor=factor)


def test_pennsylvania():
    """PA: IRA and employer-plan distributions are exempt once no early-withdrawal
    penalty applies (59 1/2); eligible pensions after retirement at any age;
    commercial annuities stay taxable. PA PIT Guide, Gross Compensation."""
    assert exclusion("PA", person(65, ira=50_000, **{"401k": 10_000})) == 60_000
    assert exclusion("PA", person(59, ira=50_000)) == 0           # turns 59 1/2 only next year
    assert exclusion("PA", person(50, pension=30_000)) == 30_000
    assert exclusion("PA", person(70, annuity=10_000, roth_conversion=5_000)) == 0


def test_illinois():
    """IL: IRA (including Roth conversions), qualified plans and pensions are
    subtracted at any age; nonqualified annuities are not. IDOR Pub-120 and
    IL-1040 Line 5 instructions."""
    assert exclusion("IL", person(40, ira=40_000, roth_conversion=10_000)) == 50_000
    assert exclusion("IL", person(70, annuity=10_000)) == 0


def test_new_york():
    """NY Tax Law 612(c)(3-a), IT-201-I line 29: $20,000 per person from 59 1/2;
    annuities bought with personal funds do not qualify."""
    assert exclusion("NY", person(60, ira=15_000)) == 15_000
    assert exclusion("NY", person(65, pension=30_000)) == 20_000
    assert exclusion("NY", person(59, pension=30_000)) == 0
    assert exclusion("NY", person(65, annuity=30_000)) == 0
    # Joint: each spouse uses only their own income and age.
    assert exclusion("NY", person(65, ira=30_000), person(58, ira=30_000), status=MFJ) == 20_000
    assert exclusion("NY", person(65, ira=30_000), person(61, ira=5_000), status=MFJ) == 25_000


def test_georgia():
    """GA DOR Retirees FAQ: $35,000 at 62-64, $65,000 at 65+, per person."""
    assert exclusion("GA", person(62, pension=50_000)) == 35_000
    assert exclusion("GA", person(65, ira=50_000)) == 50_000
    assert exclusion("GA", person(66, ira=80_000)) == 65_000
    assert exclusion("GA", person(61, ira=80_000)) == 0
    assert exclusion("GA", person(63, pension=40_000), person(66, ira=70_000), status=MFJ) == 100_000


def test_colorado_shares_cap_with_social_security():
    """C.R.S. 39-22-104(4)(f), DOR Income Tax Topics: $20,000 at 55-64 and
    $24,000 at 65+; taxable Social Security is subtracted (in full at 65+, or
    at 55-64 with AGI <= $75,000 single) and reduces the pension cap."""
    assert exclusion("CO", person(60, pension=30_000)) == 20_000
    assert exclusion("CO", person(70, pension=30_000)) == 24_000
    assert exclusion("CO", person(54, pension=30_000)) == 0
    # 65+: all 17,000 taxable SS; pension limited to 24,000 - 17,000 = 7,000.
    assert exclusion("CO", person(70, social_security=20_000, pension=30_000),
                     taxable_ss=17_000) == pytest.approx(24_000)
    # 60, AGI 55,500 <= 75,000: all 25,500 taxable SS; no pension room left.
    assert exclusion("CO", person(60, social_security=30_000, pension=30_000),
                     taxable_ss=25_500) == pytest.approx(25_500)
    # 60, AGI 100,000 > 75,000: SS shares the 20,000 cap.
    assert exclusion("CO", person(60, social_security=30_000, pension=30_000),
                     taxable_ss=25_500, agi=100_000) == pytest.approx(20_000)


def test_michigan_return_cap():
    """MCL 206.30 (PA 4 of 2023), RAB 2026-1 and 2026 Form 446: from 2026
    every taxpayer may deduct up to $67,610 single / $135,220 joint per
    return; IRA (and defined-contribution) distributions qualify from 59 1/2
    (RAB 2017-21); 457 deferred compensation does not."""
    assert exclusion("MI", person(66, ira=80_000)) == 67_610
    assert exclusion("MI", person(66, ira=100_000), person(64, pension=60_000), status=MFJ) == 135_220
    assert exclusion("MI", person(58, ira=20_000, pension=10_000)) == 10_000
    assert exclusion("MI", person(66, **{"457b": 20_000})) == 0
    assert exclusion("MI", person(66, ira=60_000), factor=1.1) == 60_000


def test_new_jersey_income_bands():
    """NJ Division of Taxation, Retirement Income Exclusions: 62+, pension,
    annuity and IRA withdrawals; caps $75,000 single / $100,000 joint at total
    income up to $100,000, then 37.5% / 18.75% (single) and 50% / 25% (joint)
    of the income, none above $150,000. Only the qualifying spouse's income."""
    assert exclusion("NJ", person(66, ira=60_000)) == 60_000
    assert exclusion("NJ", person(66, ira=90_000)) == 75_000
    assert exclusion("NJ", person(66, ira=60_000), agi=110_000) == pytest.approx(22_500)
    assert exclusion("NJ", person(66, ira=60_000), agi=140_000) == pytest.approx(11_250)
    assert exclusion("NJ", person(66, ira=60_000), agi=160_000) == 0
    assert exclusion("NJ", person(61, ira=60_000)) == 0
    assert exclusion("NJ", person(65, pension=50_000), person(60, pension=50_000), status=MFJ) == 50_000
    assert exclusion("NJ", person(65, pension=80_000), status=MFJ, agi=120_000) == pytest.approx(40_000)
    # NJ income excludes Social Security: 105,000 - 10,000 taxable SS = 95,000.
    assert exclusion("NJ", person(66, social_security=20_000, ira=60_000), agi=105_000,
                     taxable_ss=10_000) == 60_000


def test_virginia_age_deduction():
    """Va. Code 58.1-322.03(5): $12,000 per person 65+, less each dollar of
    federal AGI minus taxable Social Security above $50,000 single / $75,000
    married. Any income qualifies."""
    assert exclusion("VA", person(66), agi=55_000) == 7_000
    assert exclusion("VA", person(66), agi=70_000, taxable_ss=20_000) == 12_000
    assert exclusion("VA", person(66), person(67), status=MFJ, agi=80_000) == 14_000
    assert exclusion("VA", person(64), agi=30_000) == 0


def test_south_carolina_retirement_and_age_deductions():
    """S.C. Code 12-6-1170: $3,000 of retirement income not subject to an
    early-distribution penalty, $10,000 from 65; at 65+ a $15,000 deduction
    against any income less the person's retirement deduction."""
    assert exclusion("SC", person(62, ira=5_000)) == 3_000
    assert exclusion("SC", person(58, ira=5_000)) == 0
    assert exclusion("SC", person(58, pension=5_000)) == 3_000
    assert exclusion("SC", person(66, ira=8_000)) == 15_000   # 8,000 + 7,000
    assert exclusion("SC", person(66, ira=20_000)) == 15_000  # 10,000 + 5,000
    assert exclusion("SC", person(66, ira=20_000), person(63, pension=5_000), status=MFJ) == 18_000


def test_kentucky_delaware_oklahoma_caps():
    """KRS 141.019 / DOR Schedule P: $31,110 per person, Roth conversions included.
    Delaware DOR FAQ: $12,500 at 60+, $2,000 of pension under 60.
    68 O.S. 2358: $10,000 per person."""
    assert exclusion("KY", person(45, ira=40_000)) == 31_110
    assert exclusion("KY", person(45, roth_conversion=10_000)) == 10_000
    assert exclusion("DE", person(62, ira=20_000)) == 12_500
    assert exclusion("DE", person(55, pension=5_000)) == 2_000
    assert exclusion("DE", person(55, ira=5_000)) == 0
    assert exclusion("OK", person(50, pension=15_000)) == 10_000
    assert exclusion("OK", person(50, pension=15_000), person(50, ira=4_000), status=MFJ) == 14_000


def test_maryland_reduced_by_social_security():
    """MD pension exclusion (Tax-General 10-209; Comptroller worksheet 13A):
    65+, $41,200 less the person's Social Security; employer plans qualify, IRAs
    do not."""
    assert exclusion("MD", person(66, social_security=20_000, pension=50_000)) == pytest.approx(21_200)
    assert exclusion("MD", person(66, **{"401k": 10_000})) == 10_000
    assert exclusion("MD", person(66, ira=10_000)) == 0
    assert exclusion("MD", person(64, pension=10_000)) == 0


def test_maine_reduced_by_social_security_and_phased_out():
    """36 M.R.S. 5122(2)(M-2), (M-3): the maximum SSA benefit at full retirement
    age ($4,152 x 12 = $49,824 for 2026) less the person's Social Security;
    no 72(t) distributions; phased out by (federal AGI - $125,000) / $100,000."""
    assert exclusion("ME", person(66, social_security=20_000, ira=30_000)) == pytest.approx(29_824)
    assert exclusion("ME", person(66, ira=30_000), agi=175_000) == pytest.approx(15_000)
    assert exclusion("ME", person(58, ira=30_000, pension=5_000)) == 5_000


def test_alabama_arkansas_mississippi_iowa():
    """Ala. Schedule RS: defined-benefit pensions exempt; $6,000 of other
    retirement income at 65+. Ark. DFA Subject 206: $6,000 per taxpayer, IRAs
    from 59 1/2. MS DOR FAQ: retirement income exempt unless an early
    distribution. Iowa DOR: all retirement income from 55, Roth conversions
    included, nonqualified annuities excluded."""
    assert exclusion("AL", person(50, pension=50_000)) == 50_000
    assert exclusion("AL", person(66, ira=10_000)) == 6_000
    assert exclusion("AL", person(64, ira=10_000)) == 0
    assert exclusion("AR", person(50, pension=10_000)) == 6_000
    assert exclusion("AR", person(58, ira=5_000)) == 0
    assert exclusion("AR", person(60, ira=5_000, pension=5_000)) == 6_000
    assert exclusion("MS", person(58, pension=40_000, ira=10_000)) == 40_000
    assert exclusion("MS", person(60, ira=100_000)) == 100_000
    assert exclusion("IA", person(55, ira=50_000, roth_conversion=20_000)) == 70_000
    assert exclusion("IA", person(55, annuity=10_000)) == 0
    assert exclusion("IA", person(54, ira=50_000)) == 0


def test_louisiana_wisconsin_rhode_island_missouri():
    """La. R.S. 47:44.1: $12,000 at 65+, CPI-indexed from 2026. Wis. 2025 Act
    15: $24,000 per person 67+. RI Pub 2025-01: $50,000 at full retirement
    age, no IRAs, nothing above the AGI limit ($107,000 single for 2025).
    RSMo 143.124: $6,000 private pension less each dollar of Missouri AGI
    above $25,000 single."""
    assert exclusion("LA", person(65, ira=15_000)) == 12_000
    assert exclusion("LA", person(65, ira=15_000), factor=1.1) == pytest.approx(13_200)
    assert exclusion("LA", person(64, ira=15_000)) == 0
    assert exclusion("WI", person(67, ira=30_000)) == 24_000
    assert exclusion("WI", person(66, ira=30_000)) == 0
    assert exclusion("WI", person(67, ira=30_000), person(68, pension=30_000), status=MFJ) == 48_000
    assert exclusion("RI", person(67, pension=60_000)) == 50_000
    assert exclusion("RI", person(67, ira=60_000)) == 0
    assert exclusion("RI", person(67, pension=60_000), agi=110_000) == 0
    assert exclusion("RI", person(66, pension=60_000)) == 0
    assert exclusion("MO", person(66, pension=10_000), agi=20_000) == 6_000
    assert exclusion("MO", person(66, pension=10_000), agi=28_000) == 3_000
    assert exclusion("MO", person(66, pension=10_000), agi=40_000) == 0


def test_rhode_island_pension_joint_limit_matches_the_social_security_limit():
    """R.I. Gen. Laws 44-30-12(c)(9)(vi) ties the pension modification's income
    limits to the Social Security modification's; ADV 2025-22 publishes the
    joint limit for both. Spouses at full retirement age keep the exclusion
    at or below the joint limit and lose all of it above; the single limit
    does not apply to a joint return."""
    ri = _STATES["RI"]
    limits = ri["retirement_income_exclusion"]["components"][0]["income_limit"]["threshold"]
    joint = limits[MFJ]
    assert joint == ri["social_security_subtraction"]["start"][MFJ]
    couple = (person(67, pension=60_000), person(68, pension=30_000))
    assert exclusion("RI", *couple, status=MFJ, agi=joint - 1) == 80_000
    assert exclusion("RI", *couple, status=MFJ, agi=joint) == 80_000
    assert exclusion("RI", *couple, status=MFJ, agi=joint + 1) == 0
    single = limits["single"]
    assert single < joint
    assert exclusion("RI", *couple, status=MFJ, agi=single + 1) == 80_000
    assert exclusion("RI", person(67, pension=60_000), agi=single + 1) == 0


def test_connecticut_schedule():
    """Conn. Gen. Stat. 12-701(a)(20)(B)(xxi)-(xxix): 100% of pension, annuity
    and (from 2026) IRA income below $75,000 single / $100,000 joint federal
    AGI, then the statutory percentages down to 0 at $100,000 / $150,000."""
    assert exclusion("CT", person(40, ira=30_000), agi=60_000) == 30_000
    assert exclusion("CT", person(40, ira=30_000), agi=78_000) == pytest.approx(21_000)
    assert exclusion("CT", person(40, ira=30_000), agi=100_000) == 0
    # Joint 120,000 is in the "$120,000 but not over $124,999" band: 25%.
    assert exclusion("CT", person(66, pension=40_000), status=MFJ, agi=120_000) == pytest.approx(10_000)
    assert exclusion("CT", person(66, pension=40_000), status=MFJ, agi=119_999) == pytest.approx(16_000)


def test_states_without_a_rule_and_custom_brackets():
    assert "retirement_income_exclusion" not in _STATES["CA"]
    income = [person(70, ira=50_000)]
    ca = calculate(gross_income=50_000, deductions=0, filing_status="single", state_code="CA",
                   holder_age=70, retirement_income=income)
    assert ca.state_retirement_exclusion == 0
    custom = calculate(gross_income=50_000, deductions=0, filing_status="single", state_code="PA",
                       holder_age=70, retirement_income=income,
                       settings={"state_brackets": [[1e9, 0.05]]})
    assert custom.state_retirement_exclusion == 0
    assert custom.state == pytest.approx(2_500)


def test_tax_engine_subtracts_exclusion_from_state_agi():
    """PA 3.07% flat: 50,000 IRA + 20,000 wages; the IRA is excluded, so PA
    tax is 3.07% x 20,000 = 614. NY: a $20,000 exclusion lowers NY tax."""
    pa = calculate(gross_income=70_000, deductions=0, filing_status="single", state_code="PA",
                   holder_age=66, retirement_income=[person(66, ira=50_000)])
    assert pa.state_retirement_exclusion == 50_000
    assert pa.state == pytest.approx(614.0)
    base = dict(gross_income=50_000, deductions=0, filing_status="single", state_code="NY", holder_age=66)
    with_exclusion = calculate(**base, retirement_income=[person(66, pension=50_000)])
    without = calculate(**base)
    assert with_exclusion.state_retirement_exclusion == 20_000
    assert with_exclusion.state < without.state
    # The subtraction never exceeds state AGI (SC age deduction on small income).
    sc = calculate(gross_income=4_000, deductions=0, filing_status="single", state_code="SC",
                   holder_age=70, retirement_income=[person(70, ira=4_000)])
    assert sc.state_retirement_exclusion == pytest.approx(4_000)


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


def _plan(state_code, birth_year, **overrides) -> PlanData:
    defaults = dict(
        plan_id=str(uuid.uuid4()), birth_year=birth_year, birth_month=1, filing_status="single",
        life_expectancy=2030 - birth_year, start_year=2026, milestones=[], income_streams=[],
        expenses=[], priorities=[], drawdown_order=[],
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts={"cash": AccountInfo(balance=0.0, account_type="checking")},
        state_code=state_code, residency_periods=[],
    )
    defaults.update(overrides)
    return PlanData(**defaults)


def _ira_retiree(state_code, **overrides) -> PlanData:
    """A 66-year-old spending $40,000 a year from a traditional IRA."""
    return _plan(
        state_code, 1960,
        accounts={"cash": AccountInfo(balance=0.0, account_type="checking"),
                  "ira": AccountInfo(balance=1_000_000.0, account_type="traditional_ira", cost_basis=0.0)},
        expenses=[ExpenseData(id="living", name="Living", annual_amount=40_000.0, growth_rate=0.0)],
        drawdown_order=[DrawdownEntryData(1, "ira")],
        **overrides,
    )


def test_simulator_pennsylvania_ira_distributions_have_no_state_tax():
    first = run_simulation(_ira_retiree("PA")).yearly_snapshots[0]
    assert first.state_retirement_exclusion > 40_000
    assert first.state_tax == pytest.approx(0.0)


def test_simulator_new_york_pension_at_60_excludes_20000():
    plan = _plan("NY", 1966, income_streams=[IncomeData(
        id="pension", name="Pension", annual_amount=50_000.0, growth_rate=0.0,
        tax_category="qualified_pension")])
    first = run_simulation(plan).yearly_snapshots[0]
    assert first.state_retirement_exclusion == pytest.approx(20_000)
    expected = calculate(gross_income=50_000, deductions=0, filing_status="single", state_code="NY",
                         holder_age=60, retirement_income=[person(60, pension=50_000)])
    assert first.state_tax == pytest.approx(expected.state)


def test_simulator_move_from_new_york_to_pennsylvania_applies_each_state_rule():
    """NY through 2027, PA from 2028: $20,000 then the full IRA draw."""
    plan = _ira_retiree("NY", residency_periods=[
        ResidencyPeriodData(state_code="NY", end_year=2027, rank=0),
        ResidencyPeriodData(state_code="PA", start_year=2028, rank=1),
    ])
    snaps = {s.year: s for s in run_simulation(plan).yearly_snapshots}
    for year in (2026, 2027):
        assert snaps[year].state_retirement_exclusion == pytest.approx(20_000)
        assert snaps[year].state_tax > 0
    for year in (2028, 2029):
        assert snaps[year].state_retirement_exclusion > 40_000
        assert snaps[year].state_tax == pytest.approx(0.0)


def test_simulator_splits_joint_pension_between_spouses():
    """NY, both 66, a $60,000 joint pension: $30,000 each, $20,000 excluded each."""
    plan = _plan("NY", 1960, filing_status=MFJ, spouse_birth_year=1960, spouse_birth_month=1,
                 spouse_life_expectancy=70,
                 income_streams=[IncomeData(id="pension", name="Pension", annual_amount=60_000.0,
                                            growth_rate=0.0, tax_category="qualified_pension", owner="joint")])
    assert run_simulation(plan).yearly_snapshots[0].state_retirement_exclusion == pytest.approx(40_000)


def test_simulator_roth_conversion_counts_only_where_covered():
    """A $30,000 conversion at 50: Illinois subtracts it (IL-1040 line 5);
    New York does not (no conversion guidance; excluded conservatively)."""
    def plan(state):
        return _plan(state, 1976, accounts={
            "cash": AccountInfo(balance=100_000.0, account_type="checking"),
            "ira": AccountInfo(balance=200_000.0, account_type="traditional_ira", cost_basis=0.0),
            "roth": AccountInfo(balance=0.0, account_type="roth_ira")},
            priorities=[PriorityData(1, "roth", priority_type="roth_conversion", source_account_id="ira",
                                     max_annual_amount=30_000.0)])
    il = run_simulation(plan("IL")).yearly_snapshots[0]
    assert il.state_retirement_exclusion == pytest.approx(30_000)
    assert run_simulation(plan("NY")).yearly_snapshots[0].state_retirement_exclusion == 0
