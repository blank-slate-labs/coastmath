"""Divorced-spouse and surviving-divorced-spouse Social Security benefits."""

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    IncomeData,
    MilestoneData,
)
from tests.engine_support import source
from tests.ss_divorced_support import DIVORCED, SURVIVOR, ex, pia_ss, plan


def snapshot(result, year):
    return next(s for s in result.yearly_snapshots if s.year == year)


def test_excess_over_own_pia_at_full_retirement_age():
    result = run_simulation(plan(income_streams=[pia_ss(ex_spouse=ex())]))
    assert source(result, 2026, DIVORCED) == 0
    # Claimant born 1960 reaches FRA 67 in January 2027: 50% x 3,000 - 1,000.
    assert source(result, 2027, DIVORCED) == pytest.approx(6_000)
    assert source(result, 2027, "self SS") == pytest.approx(12_000)


def test_no_record_and_no_excess_add_nothing():
    plain = run_simulation(plan(income_streams=[pia_ss()]))
    rich = run_simulation(plan(income_streams=[pia_ss(pia=2_000, ex_spouse=ex())]))
    for result in (plain, rich):
        assert source(result, 2030, DIVORCED) == 0
    assert source(rich, 2030, "self SS") == pytest.approx(24_000)


@pytest.mark.parametrize(("years", "attested", "expected"), [
    (9.9, False, 0.0), (10, False, 6_000.0), (None, True, 6_000.0),
])
def test_marriage_must_last_ten_years(years, attested, expected):
    record = ex(marriage_years=years, marriage_lasted_10_years=attested)
    result = run_simulation(plan(income_streams=[pia_ss(ex_spouse=record)]))
    assert source(result, 2028, DIVORCED) == pytest.approx(expected)


def test_claimant_must_be_62():
    # Own benefit filed at 61 via a fixed date; the divorced spouse's benefit waits for 62.
    start = MilestoneData(id="file", name="File", trigger_type="date", trigger_date="2027-01-01")
    own = pia_ss(claim=None, ex_spouse=ex(), start_milestone_id="file")
    result = run_simulation(plan(birth_year=1966, milestones=[start], income_streams=[own]))
    assert source(result, 2027, DIVORCED) == 0
    assert source(result, 2028, DIVORCED) > 0


def test_former_spouse_must_be_62():
    record = ex(birth_year=1966, claim_age=None)
    result = run_simulation(plan(income_streams=[pia_ss(ex_spouse=record)]))
    assert source(result, 2027, DIVORCED) == 0
    assert source(result, 2028, DIVORCED) == pytest.approx(6_000)


def test_independent_entitlement_needs_two_years_divorced():
    unclaimed = ex(divorce_year=2026, divorce_month=1, claim_age=None)
    result = run_simulation(plan(income_streams=[pia_ss(ex_spouse=unclaimed)]))
    assert source(result, 2027, DIVORCED) == 0
    assert source(result, 2028, DIVORCED) == pytest.approx(6_000)
    # An entitled former spouse needs no waiting period.
    claimed = ex(divorce_year=2026, divorce_month=1, claim_age=62)
    result = run_simulation(plan(income_streams=[pia_ss(ex_spouse=claimed)]))
    assert source(result, 2027, DIVORCED) == pytest.approx(6_000)


def test_remarried_claimant_is_not_eligible_until_the_marriage_ends():
    married = dict(
        filing_status="married_filing_jointly",
        spouse_birth_year=1960, spouse_birth_month=1, spouse_life_expectancy=70,
    )
    result = run_simulation(plan(**married, income_streams=[pia_ss(ex_spouse=ex())]))
    assert source(result, 2029, DIVORCED) == 0
    # The current spouse's death (legacy timing: their January 2030 birthday)
    # ends the marriage and restores eligibility.
    assert source(result, 2030, DIVORCED) == pytest.approx(6_000)


def test_filing_status_change_ends_and_starts_marriage():
    changes = [{"year": 2029, "filing_status": "married_filing_jointly"}]
    result = run_simulation(plan(filing_status_changes=changes, income_streams=[pia_ss(ex_spouse=ex())]))
    assert source(result, 2028, DIVORCED) == pytest.approx(6_000)
    assert source(result, 2029, DIVORCED) == 0


def test_early_claim_uses_spousal_reduction():
    result = run_simulation(plan(birth_year=1964, income_streams=[pia_ss(claim=62, ex_spouse=ex())]))
    # 60 months early: 1 - 36 x 25/36% - 24 x 5/12% = 65%.
    assert source(result, 2027, DIVORCED) == pytest.approx(500 * 12 * 0.65)
    assert source(result, 2027, "self SS") == pytest.approx(12_000 * 0.70)


def test_surviving_divorced_spouse_from_60_and_remarriage_after_60():
    # Claimant born 1966 turns 60 in January 2026; the former spouse died in
    # 2025 before claiming or reaching FRA, so the deemed PIA is 3,000.
    record = ex(birth_year=1964, claim_age=None, death_year=2025, survivor_claim_age=60,
                current_marriage_year=2026)
    married = dict(
        birth_year=1966, filing_status="married_filing_jointly",
        spouse_birth_year=1966, spouse_birth_month=1, spouse_life_expectancy=90,
    )
    result = run_simulation(plan(**married, income_streams=[pia_ss(ex_spouse=record)]))
    # Survivor FRA 67 (804 months): 84 months early = the full 28.5% reduction.
    survivor = 3_000 * 0.715 * 12
    assert source(result, 2026, SURVIVOR) == pytest.approx(survivor)
    assert source(result, 2026, DIVORCED) == 0
    # From the own claim at 67 only the excess over the own benefit is paid.
    assert source(result, 2033, SURVIVOR) == pytest.approx(survivor - 12_000)
    # A remarriage before 60 bars survivor benefits while it lasts.
    early = ex(birth_year=1964, claim_age=None, death_year=2025, survivor_claim_age=60,
               current_marriage_year=2020)
    result = run_simulation(plan(**married, income_streams=[pia_ss(ex_spouse=early)]))
    assert source(result, 2026, SURVIVOR) == 0
    assert source(result, 2040, SURVIVOR) == 0


def test_divorced_benefit_converts_to_survivor_after_death():
    record = ex(claim_age=62, death_year=2030)
    result = run_simulation(plan(income_streams=[pia_ss(ex_spouse=record)]))
    assert source(result, 2030, DIVORCED) == pytest.approx(6_000)
    assert source(result, 2031, DIVORCED) == 0
    # Claimed at 62 (70%): the widow limit is max(70%, 82.5%) of PIA.
    assert source(result, 2031, SURVIVOR) == pytest.approx(3_000 * 0.825 * 12 - 12_000)


def test_highest_single_auxiliary_benefit_is_paid():
    # Married to the plan partner (spousal excess 50% x 2,400 - 1,000 = 200),
    # then single from 2028 while the partner's spousal stream continues.
    couple = dict(
        filing_status="married_filing_jointly",
        spouse_birth_year=1960, spouse_birth_month=1, spouse_life_expectancy=90,
        filing_status_changes=[{"year": 2028, "filing_status": "single"}],
    )
    result = run_simulation(plan(**couple, income_streams=[
        pia_ss(ex_spouse=ex()), pia_ss(owner="spouse", pia=2_400),
    ]))
    assert source(result, 2027, "self SS (spousal)") == pytest.approx(2_400)
    assert source(result, 2027, DIVORCED) == 0
    assert source(result, 2028, "self SS (spousal)") + source(result, 2028, DIVORCED) == pytest.approx(6_000)


def test_earnings_test_withholds_from_divorced_benefit_too():
    job = IncomeData(id="job", name="Job", annual_amount=100_000, tax_category="employment", growth_rate=0.0)
    p = plan(birth_year=1964, income_streams=[pia_ss(claim=62, ex_spouse=ex()), job])
    result = run_simulation(p)
    row = snapshot(result, 2026)
    full_own, full_divorced = 12_000 * 0.70, 500 * 12 * 0.65
    assert row.ss_earnings_test_withheld > 0
    own_paid = source(result, 2026, "self SS")
    divorced_paid = source(result, 2026, DIVORCED)
    assert divorced_paid < full_divorced
    assert own_paid / full_own == pytest.approx(divorced_paid / full_divorced)
    assert own_paid + divorced_paid == pytest.approx(
        full_own + full_divorced - row.ss_earnings_test_withheld)


def _job(**extra):
    return IncomeData(id="job", name="Job", annual_amount=100_000, tax_category="employment", growth_rate=0.0, **extra)


def test_divorced_reduction_is_adjusted_at_fra_for_withheld_months():
    # Claimed at 62 (60 months early) and fully withheld while working: at
    # FRA (January 2031) the reduction is recomputed without those months.
    always = run_simulation(plan(birth_year=1964, income_streams=[pia_ss(claim=62, ex_spouse=ex()), _job()]))
    assert source(always, 2031, DIVORCED) == pytest.approx(500 * 12)
    assert source(always, 2031, "self SS") == pytest.approx(12_000)
    # Two years fully withheld (2026-2027): 36 months remain, 75% of the excess.
    stop = MilestoneData(id="stop", name="Stop work", trigger_type="date", trigger_date="2028-01-01")
    two_years = run_simulation(plan(
        birth_year=1964, milestones=[stop],
        income_streams=[pia_ss(claim=62, ex_spouse=ex()), _job(end_milestone_id="stop")],
    ))
    assert snapshot(two_years, 2028).ss_earnings_test_withheld == 0
    assert source(two_years, 2030, DIVORCED) == pytest.approx(500 * 12 * 0.65)
    assert source(two_years, 2031, DIVORCED) == pytest.approx(500 * 12 * 0.75)
    # No withholding keeps the original reduction after FRA.
    none = run_simulation(plan(birth_year=1964, income_streams=[pia_ss(claim=62, ex_spouse=ex())]))
    assert source(none, 2031, DIVORCED) == pytest.approx(500 * 12 * 0.65)


def test_spousal_reduction_is_adjusted_for_months_the_worker_earnings_withhold():
    # The partner works until FRA while claiming at 62, so their earnings
    # withhold the spousal benefit paid on their record every month.
    couple = dict(
        birth_year=1964, filing_status="married_filing_jointly",
        spouse_birth_year=1964, spouse_birth_month=1, spouse_life_expectancy=90,
    )
    partner_job = IncomeData(id="job", name="Job", owner="spouse", annual_amount=100_000,
                             tax_category="employment", growth_rate=0.0)
    working = run_simulation(plan(**couple, income_streams=[
        pia_ss(claim=62), pia_ss(owner="spouse", pia=2_400, claim=62), partner_job,
    ]))
    retired = run_simulation(plan(**couple, income_streams=[
        pia_ss(claim=62), pia_ss(owner="spouse", pia=2_400, claim=62),
    ]))
    spousal = "self SS (spousal)"
    assert source(retired, 2031, spousal) == pytest.approx(200 * 12 * 0.65)
    assert source(working, 2030, spousal) == 0
    assert source(working, 2031, spousal) == pytest.approx(200 * 12)


def test_larger_benefit_comparison_uses_spousal_benefit_after_withholding():
    # Single from 2026 while the plan partner's spousal stream continues, as
    # in test_highest_single_auxiliary_benefit_is_paid. The partner (born
    # 1962, FRA January 2029) claims at 62 and works through 2028, so their
    # earnings withhold the spousal benefit paid on their record in full.
    couple = dict(
        filing_status="married_filing_jointly",
        spouse_birth_year=1962, spouse_birth_month=1, spouse_life_expectancy=90,
        filing_status_changes=[{"year": 2026, "filing_status": "single"}],
    )
    stop = MilestoneData(id="stop", name="Stop work", trigger_type="date", trigger_date="2029-01-01")
    partner_job = IncomeData(id="job", name="Job", owner="spouse", annual_amount=200_000,
                             tax_category="employment", growth_rate=0.0, end_milestone_id="stop")
    streams = [pia_ss(ex_spouse=ex()), pia_ss(owner="spouse", pia=2_400, claim=62)]
    idle = run_simulation(plan(**couple, milestones=[stop], income_streams=streams))
    working = run_simulation(plan(**couple, milestones=[stop], income_streams=[*streams, partner_job]))
    spousal = "self SS (spousal)"
    # Without withholding: spousal 2,400 plus the divorced excess 3,600.
    assert source(idle, 2027, spousal) == pytest.approx(2_400)
    assert source(idle, 2027, DIVORCED) == pytest.approx(3_600)
    # Spousal withheld: the larger divorced-spouse benefit is paid in full.
    assert source(working, 2027, spousal) == 0
    assert source(working, 2027, DIVORCED) == pytest.approx(6_000)
    # Payments still reconcile to the gross benefits less the withheld total.
    names = ("spouse SS", spousal, DIVORCED)
    gross = sum(source(idle, 2027, name) for name in names)
    paid = sum(source(working, 2027, name) for name in names)
    assert paid == pytest.approx(gross - snapshot(working, 2027).ss_earnings_test_withheld)
    # After the partner stops working nothing changes.
    assert source(working, 2029, DIVORCED) == pytest.approx(3_600)
