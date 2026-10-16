"""Healthcare premiums and HSA eligibility follow coverage months and ages.

ACA premiums are charged only for the coverage window's months and price only
the covered adults under 65; the IRMAA top tier starts at its boundary; and
with no HSA coverage entered, HSA contributions stop from the month the owner
enrolls in Medicare.

Expected values come from the cited rules and published tables, not from
engine output. Plans use zero growth and inflation unless a case needs
otherwise.
"""

import uuid

import pytest

from coastmath.engine.healthcare import _irmaa_tier
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


def _plan(**kw) -> PlanData:
    values = dict(plan_id=str(uuid.uuid4()), birth_year=1980, birth_month=1, filing_status="single",
                  life_expectancy=50, start_year=2026, assumptions=ZERO)
    values.update(kw)
    return PlanData(**values)


# ---------------------------------------------------------------------------
# ACA premiums follow the coverage window's months
# Marketplace premiums are owed only for months of coverage (26 CFR
# 1.36B-3(c)); the window uses the same month rule as milestone-bounded
# expenses: from the start milestone's month to the month before the end.
# ---------------------------------------------------------------------------


def _aca_plan(start: MilestoneData, end: MilestoneData | None = None, *, start_year: int = 2030) -> PlanData:
    """Single, born January 1980, $12,000/yr premium, no age curve, no advance credit."""
    milestones = [start] + ([end] if end is not None else [])
    return PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1980, birth_month=1, filing_status="single",
        life_expectancy=56, start_year=start_year, assumptions=ZERO, milestones=milestones,
        income_streams=[IncomeData("pay", "Salary", 120_000, end_milestone_id=start.id, tax_category="employment")],
        expenses=[ExpenseData("live", "Living", 40_000, inflation_linked=False)],
        accounts={"cash": AccountInfo(2_000_000, "savings")},
        drawdown_order=[DrawdownEntryData(1, "cash")],
        healthcare_settings={
            "enabled": True, "aca_enabled": True, "aca_start_milestone_id": start.id,
            "aca_end_milestone_id": end.id if end is not None else None,
            "aca_benchmark_premium_annual": 12_000, "aca_plan_premium_annual": 12_000,
            "aca_advance_credit_fraction": 0.0, "aca_apply_age_curve": False, "medicare_enabled": False,
        },
    )


def _gross_premium(result, year):
    healthcare = year_snapshot(result, year).healthcare
    return healthcare.aca_gross_premium if healthcare is not None else 0.0


class TestAcaCoverageMonths:
    RETIRE = MilestoneData("retire", "Retire", "date", trigger_date="2030-07-01")
    NEW_JOB = MilestoneData("job", "New job", "date", trigger_date="2033-07-01")

    def test_window_starting_in_july_charges_six_months(self):
        result = run_simulation(_aca_plan(self.RETIRE, self.NEW_JOB))
        assert _gross_premium(result, 2030) == pytest.approx(6_000)
        assert _gross_premium(result, 2031) == pytest.approx(12_000)
        assert _gross_premium(result, 2032) == pytest.approx(12_000)

    def test_window_ending_in_july_charges_january_to_june(self):
        result = run_simulation(_aca_plan(self.RETIRE, self.NEW_JOB))
        assert _gross_premium(result, 2033) == pytest.approx(6_000)
        assert _gross_premium(result, 2034) == pytest.approx(0)

    def test_age_milestone_starts_in_the_birthday_month(self):
        # Age 50 is reached in January 2030; born April instead -> April.
        plan = _aca_plan(MilestoneData("retire", "Retire", "age", trigger_value=50))
        plan.birth_month = 4
        assert _gross_premium(run_simulation(plan), 2030) == pytest.approx(9_000)

    def test_window_started_before_the_plan_is_a_full_year(self):
        plan = _aca_plan(MilestoneData("retire", "Retire", "date", trigger_date="2029-07-01"))
        assert _gross_premium(run_simulation(plan), 2030) == pytest.approx(12_000)

    def test_unknown_start_milestone_never_starts_coverage(self):
        plan = _aca_plan(self.RETIRE)
        plan.healthcare_settings = {**plan.healthcare_settings, "aca_start_milestone_id": "deleted"}
        assert _gross_premium(run_simulation(plan), 2031) == pytest.approx(0)


# ---------------------------------------------------------------------------
# Entered ACA premiums price the covered adults under 65
# at plan start; a partner already on Medicare does not dilute them.
# MAGI $150,000 joint is above 400% FPL, so there is no credit.
# ---------------------------------------------------------------------------


def _aca_household(primary_birth_year, spouse_birth_year, cover_spouse=True):
    p = _plan(birth_year=primary_birth_year, filing_status="married_filing_jointly",
              life_expectancy=90, spouse_birth_year=spouse_birth_year, spouse_birth_month=1,
              spouse_life_expectancy=90,
              income_streams=[IncomeData("pen", "Pension", 150_000, is_earned_income=False, growth_rate=0.0)],
              accounts={"cash": AccountInfo(500_000, "checking")},
              drawdown_order=[DrawdownEntryData(1, "cash")],
              healthcare_settings={"enabled": True, "aca_enabled": True,
                                   "aca_benchmark_premium_annual": 12_000, "aca_plan_premium_annual": 12_000,
                                   "aca_cover_spouse": cover_spouse, "medicare_enabled": True,
                                   "medicare_apply_irmaa": False, "medical_inflation_rate": 0.0})
    return run_simulation(p).yearly_snapshots[0].healthcare


class TestAcaBaselineExcludesMedicare:
    @pytest.mark.parametrize(("primary", "spouse", "cover_spouse"), [
        (1966, 1960, True),   # spouse 66 on Medicare, partner coverage left on
        (1966, 1960, False),  # control
        (1960, 1966, True),   # primary 66 on Medicare, spouse 60 covered
    ])
    def test_full_premium_for_the_one_covered_adult(self, primary, spouse, cover_spouse):
        hc = _aca_household(primary, spouse, cover_spouse)
        assert hc.aca_covered_adults == 1
        assert hc.aca_gross_premium == pytest.approx(12_000)
        assert hc.aca_net_premium == pytest.approx(12_000)


# ---------------------------------------------------------------------------
# The IRMAA top tier starts at the boundary
# 20 CFR 418.1115: the top range is "greater than or equal to" $500,000
# single, $750,000 joint and $391,000 married filing separately.
# ---------------------------------------------------------------------------


class TestIrmaaTopTierBoundary:
    @pytest.mark.parametrize(("magi", "status", "tier", "part_b_add"), [
        (500_000, "single", 5, 487.00),
        (499_999.99, "single", 4, 446.30),
        (750_000, "married_filing_jointly", 5, 487.00),
        (749_999.99, "married_filing_jointly", 4, 446.30),
        (391_000, "married_filing_separately", 2, 487.00),
        (390_999.99, "married_filing_separately", 1, 446.30),
        # The lower tiers keep their "less than or equal to" upper bound.
        (109_000, "single", 0, 0.00),
        (205_000, "single", 3, 324.60),
        (109_000, "married_filing_separately", 0, 0.00),
    ])
    def test_tier_at_boundary(self, magi, status, tier, part_b_add):
        got_tier, got_b, _ = _irmaa_tier(magi, status, 2026, 1.0)
        assert (got_tier, got_b) == (tier, pytest.approx(part_b_add))


# ---------------------------------------------------------------------------
# With no HSA coverage entered, HSA contributions stop
# from the month the engine enrolls the owner in Medicare (IRC 223(b)(7)).
# 2026 self-only limit $4,400 + $1,000 catch-up at 55+.
# ---------------------------------------------------------------------------


def _hsa_by_year(birth_month, **kw):
    p = _plan(birth_year=1962, birth_month=birth_month, life_expectancy=72,
              income_streams=[IncomeData("pay", "Salary", 150_000, tax_category="employment")],
              expenses=[ExpenseData("live", "Living", 60_000, inflation_linked=False)],
              accounts={"chk": AccountInfo(0, "checking"), "hsa": AccountInfo(10_000, "hsa")},
              priorities=[PriorityData(1, "hsa", allocation_mode="remaining")],
              drawdown_order=[DrawdownEntryData(1, "chk")], **kw)
    return {s.year: sum(c.amount for c in s.cash_flow.contributions if c.account_id == "hsa")
            for s in run_simulation(p).yearly_snapshots[:3]}


class TestHsaStopsAtMedicare:
    def test_january_birthday(self):
        hsa = _hsa_by_year(1, healthcare_settings={"enabled": True, "medicare_enabled": True})
        assert hsa == {2026: pytest.approx(5_400), 2027: 0.0, 2028: 0.0}

    def test_july_birthday_prorates_enrollment_year(self):
        hsa = _hsa_by_year(7, healthcare_settings={"enabled": True, "medicare_enabled": True})
        assert hsa[2027] == pytest.approx(5_400 * 6 / 12)
        assert hsa[2028] == 0.0

    def test_unchanged_without_modeled_medicare(self):
        hsa = _hsa_by_year(1, healthcare_settings={"enabled": True, "medicare_enabled": False})
        assert hsa[2027] == pytest.approx(5_400)
        assert _hsa_by_year(1)[2027] == pytest.approx(5_400)

    def test_entered_coverage_wins(self):
        hsa = _hsa_by_year(1, healthcare_settings={"enabled": True, "medicare_enabled": True},
                           tax_settings={"hsa_coverage": [{"owner": "self", "start_year": 2026,
                                                           "end_year": 2030, "coverage": "self_only"}]})
        assert hsa[2027] == pytest.approx(5_400)
