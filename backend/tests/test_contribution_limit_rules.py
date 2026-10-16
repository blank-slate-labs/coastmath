"""Contribution limits by age, filing status, income range and employer.

A spouse with no birth year gets no catch-up; a separate filer who lived apart
all year uses the single Roth IRA range; Roth IRA income ranges index only
their starting amount; and IRC 415(c) applies per employer, so a solo 401(k)
has its own limit beside a W-2 plan.

Expected values come from the cited rules and published tables, not from
engine output.
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
    PriorityData,
)
from coastmath.engine.waterfall import _irs_contribution_room

ZERO = AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0)


def _plan(**kw) -> PlanData:
    values = dict(plan_id=str(uuid.uuid4()), birth_year=1980, birth_month=1, filing_status="single",
                  life_expectancy=50, start_year=2026, assumptions=ZERO)
    values.update(kw)
    return PlanData(**values)


# ---------------------------------------------------------------------------
# A spouse with no birth year gets no catch-up. 2026:
# $24,500 402(g) limit, $7,500 IRA limit (catch-ups need a known age 50+).
# ---------------------------------------------------------------------------


class TestSpouseCatchUpWithoutBirthYear:
    @pytest.mark.parametrize(("spouse_birth_year", "roth_401k", "roth_ira"), [
        (None, 24_500, 7_500),
        # Known and under 50: same limits. Known and 50+: $8,000 + $1,100 catch-ups.
        (1990, 24_500, 7_500),
        (1970, 32_500, 8_600),
    ])
    def test_spouse_limits(self, spouse_birth_year, roth_401k, roth_ira):
        p = _plan(birth_year=1965, spouse_birth_year=spouse_birth_year,
                  filing_status="married_filing_jointly", life_expectancy=62,
                  income_streams=[IncomeData("sp", "Spouse job", 100_000, owner="spouse")],
                  accounts={"cash": AccountInfo(0, "checking"),
                            "sk": AccountInfo(0, "roth_401k", owner="spouse"),
                            "sr": AccountInfo(0, "roth_ira", owner="spouse")},
                  priorities=[PriorityData(1, "sk", priority_type="pre_tax_contribution", source_income_id="sp"),
                              PriorityData(2, "sr"), PriorityData(3, "cash")],
                  drawdown_order=[DrawdownEntryData(1, "cash")])
        s = run_simulation(p).yearly_snapshots[0]
        assert s.accounts["sk"] == pytest.approx(roth_401k)
        assert s.accounts["sr"] == pytest.approx(roth_ira)


# ---------------------------------------------------------------------------
# IRC 408A(c)(3)(D) applies 219(g)(4), so a separate
# filer who lived apart all year uses the single Roth IRA range
# ($153,000-$168,000 for 2026), not the separate $0-$10,000 range.
# ---------------------------------------------------------------------------


class TestSeparateFilerLivedApartRothIra:
    @pytest.mark.parametrize(("lived_apart", "expected"), [(True, 7_500.0), (False, 0.0)])
    def test_roth_ira_range(self, lived_apart, expected):
        p = _plan(birth_year=1986, spouse_birth_year=1986, filing_status="married_filing_separately",
                  life_expectancy=41, tax_settings={"mfs_lived_apart_all_year": lived_apart},
                  income_streams=[IncomeData("job", "Salary", 60_000)],
                  accounts={"cash": AccountInfo(0, "checking"), "r": AccountInfo(0, "roth_ira")},
                  priorities=[PriorityData(1, "r"), PriorityData(2, "cash")],
                  drawdown_order=[DrawdownEntryData(1, "cash")])
        s = run_simulation(p).yearly_snapshots[0]
        assert s.accounts["r"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Roth IRA income ranges index only their starting amount
# IRC 408A(c)(3); Publication 590-A Worksheet 2-2.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filing_status, magi, expected", [
    # Single: start 153,000 x 1.1 = 168,300; the 15,000 width is fixed.
    # 8,250 x (1 - 11,700 / 15,000) = 1,815 -> next $10 = 1,820.
    ("single", 180_000, 1_820),
    ("single", 183_300, 0),
    # Separate return: 0-10,000 is never indexed. 8,250 x 0.1 = 825 -> 830.
    ("married_filing_separately", 9_000, 830),
    ("married_filing_separately", 10_000, 0),
])
def test_roth_ira_phaseout_indexes_only_the_start(filing_status, magi, expected):
    room = _irs_contribution_room("roth_ira", 40, 0.0, 1.1, filing_status, magi)
    assert room == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Section 415(c) applies per employer (Treas. Reg.
# 1.415(f)-1). A W-2 401(k) and a solo 401(k) funded from unrelated
# self-employment each have a $72,000 limit; 402(g) stays per person.
# ---------------------------------------------------------------------------


class TestPerEmployer415c:
    @pytest.mark.parametrize("w2_employer_rate", [0.10, 0.0])
    def test_solo_plan_has_its_own_limit(self, w2_employer_rate):
        p = _plan(birth_year=1986, life_expectancy=41,
                  income_streams=[IncomeData("w2", "Day job", 200_000),
                                  IncomeData("se", "Side business", 200_000, is_self_employed=True)],
                  accounts={"cash": AccountInfo(0, "checking"), "ka": AccountInfo(0, "traditional_401k"),
                            "kb": AccountInfo(0, "traditional_401k")},
                  priorities=[PriorityData(1, "ka", priority_type="income_percent", source_income_id="w2",
                                           employee_rate=0.20, employer_match_rate=w2_employer_rate),
                              PriorityData(2, "kb", priority_type="income_percent", source_income_id="se",
                                           employee_rate=0.0, employer_match_rate=0.25)],
                  drawdown_order=[DrawdownEntryData(1, "cash")])
        s = run_simulation(p).yearly_snapshots[0]
        # W-2 plan: $24,500 deferral (402(g)) + 10% x 200,000 employer.
        assert s.accounts["ka"] == pytest.approx(24_500 + w2_employer_rate * 200_000)
        # Pub. 560: 20% x (200,000 - 2,678.15 half SE tax; W-2 pay is above
        # the $184,500 wage base, so only the 2.9% Medicare part applies).
        assert s.accounts["kb"] == pytest.approx(0.2 * (200_000 - 2_678.15), abs=0.01)
