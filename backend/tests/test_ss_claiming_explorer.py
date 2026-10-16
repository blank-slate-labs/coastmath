"""Social Security claiming-age explorer: who is adjustable, the grid, ranking and apply patches."""

import copy
import uuid
from dataclasses import replace

import pytest

from coastmath.engine import ss_claiming
from coastmath.engine.household_lifecycle import LAST_SURVIVOR
from coastmath.engine.simulator import run_simulation
from coastmath.engine.ss_claiming import (
    ALREADY_CLAIMED,
    MISSING_BIRTH_YEAR,
    MULTIPLE_BENEFITS,
    NO_BENEFIT,
    NO_CANDIDATE_AGES,
    SURVIVOR_TOP_UP,
    UNRESOLVED_CLAIM_DATE,
    ClaimingRun,
    best_run_index,
    explore_claiming_ages,
    first_month_index,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
)
from tests.engine_support import source


def plan(**changes) -> PlanData:
    values = dict(
        plan_id=str(uuid.uuid4()), birth_year=1965, birth_month=1, life_expectancy=88,
        filing_status="single", start_year=2026,
        assumptions=AssumptionData(inflation_rate=0.02, stock_growth_rate=0.05, bond_return_rate=0.03,
                                   stock_dividend_yield=0, cash_yield_rate=0),
        accounts={"cash": AccountInfo(balance=150_000, account_type="checking"),
                  "ira": AccountInfo(balance=400_000, account_type="traditional_ira")},
        expenses=[ExpenseData("living", "Living", 45_000)],
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "ira")],
    )
    values.update(changes)
    return PlanData(**values)


def couple(**changes) -> PlanData:
    values = dict(spouse_birth_year=1967, spouse_birth_month=7, spouse_life_expectancy=90,
                  filing_status="married_filing_jointly")
    values.update(changes)
    return plan(**values)


def ss(owner="self", amount=24_000.0, claim=67, **extra) -> IncomeData:
    return IncomeData(id=f"{owner}_ss", name=f"{owner} SS", annual_amount=amount, owner=owner,
                      tax_category="social_security", claiming_age=claim, growth_rate=0.02, **extra)


def pia_ss(owner, pia, claim=67) -> IncomeData:
    return ss(owner, 1.0, claim, ss_benefit_basis="pia", pia_monthly=pia)


def person(exploration, owner):
    return next(p for p in exploration.persons if p.owner == owner)


# --- Plan start and candidate ages -------------------------------------------

def test_first_month_follows_a_partial_first_year():
    assert first_month_index(plan()) == 2026 * 12
    # 92 of 365 days left: the plan starts on October 1.
    assert first_month_index(plan(first_year_fraction=92 / 365)) == 2026 * 12 + 9


@pytest.mark.parametrize(("birth_year", "birth_month", "fraction", "first_age"), [
    (1963, 7, 1.0, 63),          # 62 fell in July 2025, before the plan
    (1964, 1, 1.0, 62),          # 62 is January 2026, the first month
    (1964, 9, 92 / 365, 63),     # the plan starts October 2026; 62 was September
    (1964, 10, 92 / 365, 62),
])
def test_candidate_ages_start_at_the_plan_start(birth_year, birth_month, fraction, first_age):
    p = plan(birth_year=birth_year, birth_month=birth_month, first_year_fraction=fraction,
             income_streams=[ss(claim=68)])
    me = person(explore_claiming_ages(p), "self")
    assert me.adjustable and me.reason is None
    assert me.candidate_ages == list(range(first_age, 71))


# --- Current claim age -------------------------------------------------------

def test_current_age_from_claiming_age_and_start_month():
    exploration = explore_claiming_ages(plan(birth_month=3, income_streams=[ss(claim=67)]))
    assert person(exploration, "self").current_claim_age == 67.0
    # An explicit start month moves the claim within that year.
    exploration = explore_claiming_ages(plan(birth_month=3, income_streams=[ss(claim=67, start_month=9)]))
    assert person(exploration, "self").current_claim_age == pytest.approx(67.5)


def test_current_age_from_a_date_milestone():
    ms = MilestoneData(id="claim", name="Claim", trigger_type="date", trigger_date="2032-06-01")
    p = plan(milestones=[ms], income_streams=[ss(claim=None, start_milestone_id="claim")])
    assert person(explore_claiming_ages(p), "self").current_claim_age == pytest.approx(67 + 5 / 12)


def test_spouse_stream_on_the_owners_milestone_gets_the_spouses_own_age():
    # Owner born January 1965 reaches 67 in January 2032; the spouse (July 1967) is then 64.5.
    ms = MilestoneData(id="ss", name="SS begins", trigger_type="age", trigger_value=67)
    p = couple(milestones=[ms], income_streams=[ss(claim=None, start_milestone_id="ss"),
                                                ss("spouse", 15_000, None, start_milestone_id="ss")])
    exploration = explore_claiming_ages(p)
    assert person(exploration, "self").current_claim_age == 67.0
    assert person(exploration, "spouse").current_claim_age == 64.5
    assert exploration.current.claim_ages == {"self": 67.0, "spouse": 64.5}


# --- Non-adjustable people ---------------------------------------------------

def test_no_benefit_returns_reasons_without_simulating(monkeypatch):
    monkeypatch.setattr(ss_claiming, "run_simulation", lambda *_: pytest.fail("must not simulate"))
    exploration = explore_claiming_ages(couple())
    assert [(p.owner, p.adjustable, p.reason) for p in exploration.persons] == [
        ("self", False, NO_BENEFIT), ("spouse", False, NO_BENEFIT)]
    assert exploration.runs == [] and exploration.current is None and exploration.best_index is None
    assert exploration.patches == [] and exploration.years == []
    assert exploration.pre_tax_discount_rate == 0.24


def test_single_plan_lists_only_self():
    exploration = explore_claiming_ages(plan())
    assert [p.owner for p in exploration.persons] == ["self"]


def test_already_claimed_benefits():
    # Claimed at 62 in 2027 by someone born 1960: before the plan.
    early = explore_claiming_ages(plan(birth_year=1960, income_streams=[ss(claim=62)]))
    assert person(early, "self").reason == ALREADY_CLAIMED
    # Neither a claiming age nor a start milestone: paid from plan start.
    now = explore_claiming_ages(plan(income_streams=[ss(claim=None)]))
    assert person(now, "self").reason == ALREADY_CLAIMED
    assert person(now, "self").income_id == "self_ss"


@pytest.mark.parametrize("milestone", [
    MilestoneData(id="m", name="Rich", trigger_type="net_worth", trigger_value=2_000_000),
    MilestoneData(id="m", name="Off", trigger_type="age", trigger_value=67, is_active=False),
    MilestoneData(id="m", name="Missing", trigger_type="relative", relative_to_id="nothing", offset_years=1),
])
def test_unresolved_claim_dates(milestone):
    p = plan(milestones=[milestone], income_streams=[ss(claim=None, start_milestone_id="m")])
    assert person(explore_claiming_ages(p), "self").reason == UNRESOLVED_CLAIM_DATE


def test_milestone_that_cannot_resolve_is_unresolved():
    milestones = [MilestoneData(id="rich", name="Rich", trigger_type="net_worth", trigger_value=1),
                  MilestoneData(id="m", name="Before rich", trigger_type="relative", relative_to_id="rich",
                                offset_years=-1)]
    p = plan(milestones=milestones, income_streams=[ss(claim=None, start_milestone_id="m")])
    assert person(explore_claiming_ages(p), "self").reason == UNRESOLVED_CLAIM_DATE


def test_multiple_benefits_and_missing_birth_year():
    p = plan(income_streams=[ss(), replace(ss(), id="second", name="Second SS"),
                             ss("spouse", 10_000)])
    exploration = explore_claiming_ages(p)
    assert person(exploration, "self").reason == MULTIPLE_BENEFITS
    assert person(exploration, "spouse").reason == MISSING_BIRTH_YEAR
    assert exploration.runs == []


def test_inactive_streams_are_ignored():
    p = plan(income_streams=[ss(), replace(ss(), id="old", name="Old SS", is_active=False)])
    assert person(explore_claiming_ages(p), "self").adjustable


def test_claim_after_70_with_every_candidate_before_the_plan():
    ms = MilestoneData(id="late", name="Late", trigger_type="date", trigger_date="2031-01-01")
    p = plan(birth_year=1950, life_expectancy=95, milestones=[ms],
             income_streams=[ss(claim=None, start_milestone_id="late")])
    me = person(explore_claiming_ages(p), "self")
    assert me.reason == NO_CANDIDATE_AGES and me.candidate_ages == []


# --- Grid --------------------------------------------------------------------

def test_one_person_sweeps_with_the_other_as_planned():
    p = couple(income_streams=[ss(), ss("spouse", 15_000, claim=None)])  # spouse already paid
    exploration = explore_claiming_ages(p)
    assert person(exploration, "spouse").reason == ALREADY_CLAIMED
    assert [r.claim_ages for r in exploration.runs] == [{"self": float(a)} for a in range(62, 71)]
    assert set(exploration.runs[0].first_year_benefits) == {"self"}
    assert len(exploration.patches) == 9


def test_two_people_cross_product_in_self_major_order():
    p = couple(income_streams=[ss(), ss("spouse", 15_000)])
    exploration = explore_claiming_ages(p)
    assert len(exploration.runs) == 81
    assert exploration.runs[0].claim_ages == {"self": 62.0, "spouse": 62.0}
    assert exploration.runs[1].claim_ages == {"self": 62.0, "spouse": 63.0}
    assert exploration.runs[9].claim_ages == {"self": 63.0, "spouse": 62.0}
    assert len(exploration.patches) == 18
    years = exploration.years
    assert years == [s.year for s in run_simulation(copy.deepcopy(p)).yearly_snapshots]
    assert all(len(r.social_security_by_year) == len(years) for r in exploration.runs)


def test_current_run_matches_a_plain_simulation_bitwise():
    p = couple(income_streams=[ss(), ss("spouse", 15_000)])
    expected = run_simulation(copy.deepcopy(p))
    current = explore_claiming_ages(p).current
    assert current.end_net_worth == expected.yearly_snapshots[-1].net_worth
    assert current.lifetime_taxes == sum(s.taxes for s in expected.yearly_snapshots)
    assert current.success is expected.metadata.success
    assert current.lifetime_social_security == pytest.approx(sum(
        source(expected, s.year, "self SS") + source(expected, s.year, "spouse SS") for s in expected.yearly_snapshots))
    # The candidate equal to the plan reproduces it.
    exploration = explore_claiming_ages(p)
    same = next(r for r in exploration.runs if r.claim_ages == {"self": 67.0, "spouse": 67.0})
    assert same.end_net_worth == current.end_net_worth
    assert same.end_net_worth_after_tax_change == 0 and same.lifetime_social_security_change == 0


def test_the_callers_plan_is_not_mutated():
    p = couple(income_streams=[ss(), ss("spouse", 15_000)])
    before = copy.deepcopy(p)
    explore_claiming_ages(p)
    assert p == before


# --- Amount basis rescale ----------------------------------------------------

@pytest.mark.parametrize(("age", "amount"), [(70, 24_000 * 1.24), (62, 24_000 * 0.70), (67, 24_000)])
def test_amount_basis_rescales_by_claiming_factor(age, amount):
    exploration = explore_claiming_ages(plan(income_streams=[ss(claim=67)]))  # born 1965: FRA 67
    patch = next(x for x in exploration.patches if x.claiming_age == age)
    assert patch.income_id == "self_ss" and patch.owner == "self"
    assert patch.changes == {"claiming_age": age, "start_milestone_id": None, "start_month": None,
                             "annual_amount": pytest.approx(amount)}
    run = next(r for r in exploration.runs if r.claim_ages == {"self": float(age)})
    assert run.first_year_benefits["self"] == pytest.approx(amount)


def test_rescale_from_a_fractional_current_age_is_rounded_to_cents():
    exploration = explore_claiming_ages(plan(income_streams=[ss(amount=20_000, claim=67, start_month=7)]))
    patch = next(x for x in exploration.patches if x.claiming_age == 70)
    # 67.5 earns 6 months of credits (1.04); 70 earns 36 (1.24).
    assert patch.changes["annual_amount"] == round(20_000 * 1.24 / 1.04, 2)


# --- PIA basis household -----------------------------------------------------

def test_pia_basis_spousal_excess_follows_both_ages():
    p = couple(spouse_birth_year=1965, spouse_birth_month=1,
               income_streams=[pia_ss("self", 3_000), pia_ss("spouse", 600)])
    exploration = explore_claiming_ages(p)
    patch = next(x for x in exploration.patches if x.owner == "spouse")
    assert "annual_amount" not in patch.changes
    run = {tuple(r.claim_ages.values()): r for r in exploration.runs}
    # Own benefit follows the claim factor; the engine sizes it.
    assert run[(70.0, 62.0)].first_year_benefits == pytest.approx({"self": 3_000 * 12 * 1.24, "spouse": 600 * 12 * 0.70})
    # Spousal excess starts when the worker files: a later worker claim delays it.
    scenario = ss_claiming.with_claims(p, {a.person.owner: (a, age) for a, age in (
        (_adjustable(p, "self"), 70), (_adjustable(p, "spouse"), 62))})
    result = run_simulation(scenario)
    assert source(result, 2034, "spouse SS (spousal)") == 0
    assert source(result, 2035, "spouse SS (spousal)") > 0
    expected = [sum(i.amount for i in s.cash_flow.income_sources if i.name in {"self SS", "spouse SS", "spouse SS (spousal)"})
                for s in result.yearly_snapshots]
    assert run[(70.0, 62.0)].social_security_by_year == pytest.approx(expected)
    assert run[(62.0, 62.0)].social_security_by_year[2028 - 2026] > 0
    # Before the worker files, the spouse receives only their own benefit, grown by COLA from plan start.
    assert run[(70.0, 62.0)].social_security_by_year[2028 - 2026] == pytest.approx(600 * 12 * 0.70 * 1.02 ** 2)


def _adjustable(p, owner):
    exploration_person, adjustable = ss_claiming._person(p, owner, first_month_index(p))
    return adjustable


def test_pia_basis_survivor_benefit_follows_the_deceaseds_claim():
    p = couple(
        birth_year=1964, life_expectancy=74, spouse_birth_year=1966, spouse_birth_month=1, spouse_life_expectancy=92,
        estate_settings=EstateSettingsData(
            household_lifecycle=LAST_SURVIVOR,
            survivor_social_security_policy="claimed_benefit_at_survivor_fra",
            survivor_social_security_eligibility_confirmed=True,
            survivor_social_security_eligibility_source="Synthetic eligibility fixture",
        ),
        income_streams=[pia_ss("self", 2_500), pia_ss("spouse", 800)],
    )
    exploration = explore_claiming_ages(p)
    run = {tuple(r.claim_ages.values()): r for r in exploration.runs}
    after_death = 2039 - 2026  # self dies in 2038
    early, late = run[(62.0, 67.0)], run[(70.0, 67.0)]
    # Delayed credits raise the widow's benefit; an early claim caps it at 82.5% of PIA.
    assert late.social_security_by_year[after_death] > early.social_security_by_year[after_death]
    result = run_simulation(ss_claiming.with_claims(p, {"self": (_adjustable(p, "self"), 70),
                                                         "spouse": (_adjustable(p, "spouse"), 67)}))
    top_up = source(result, 2039, SURVIVOR_TOP_UP)
    assert top_up > 0
    assert late.social_security_by_year[after_death] == pytest.approx(top_up + source(result, 2039, "spouse SS"))


# --- Ranking -----------------------------------------------------------------

def _run(after_tax, success=True):
    return ClaimingRun(claim_ages={}, first_year_benefits={}, social_security_by_year=[], lifetime_social_security=0,
                       lifetime_taxes=0, end_net_worth=after_tax, end_net_worth_after_tax=after_tax,
                       success=success, failure_year=None if success else 2050)


def test_ranking_prefers_successful_runs_and_keeps_the_first_tie():
    assert best_run_index([_run(5), _run(9, success=False), _run(7), _run(7)]) == 2
    assert best_run_index([_run(3), _run(3)]) == 0


def test_ranking_falls_back_to_all_runs_when_none_succeed():
    assert best_run_index([_run(1, False), _run(4, False), _run(2, False)]) == 1
    assert best_run_index([]) is None


def test_best_run_and_deltas_are_reported():
    exploration = explore_claiming_ages(plan(income_streams=[ss()]))
    best = exploration.runs[exploration.best_index]
    assert exploration.best_index == best_run_index(exploration.runs)
    assert exploration.best_end_net_worth_after_tax_change == best.end_net_worth_after_tax_change
    assert best.end_net_worth_after_tax_change == pytest.approx(
        best.end_net_worth_after_tax - exploration.current.end_net_worth_after_tax)
    assert exploration.best_lifetime_social_security_change == pytest.approx(
        best.lifetime_social_security - exploration.current.lifetime_social_security)


# --- Earnings test -----------------------------------------------------------

def salary(owner, amount=98_000.0, **extra) -> IncomeData:
    return IncomeData(id=f"{owner}_work", name=f"{owner} work", annual_amount=amount, owner=owner,
                      tax_category="employment", growth_rate=0, **extra)


def test_a_partners_unending_salary_is_flagged_as_withholding():
    # The partner (FRA 67) works to the end of the plan, so claiming before 67 is withheld.
    p = couple(income_streams=[ss(), ss("spouse", 15_000), salary("spouse")])
    exploration = explore_claiming_ages(p)
    assert person(exploration, "spouse").earnings_test_withholds is True
    assert person(exploration, "self").earnings_test_withholds is False


def test_no_earnings_or_earnings_ending_before_62_are_not_flagged():
    ends = MilestoneData(id="stop", name="Stop work", trigger_type="date", trigger_date="2028-01-01")
    for streams in ([ss(), ss("spouse", 15_000)],
                    [ss(), ss("spouse", 15_000), salary("spouse", end_milestone_id="stop")]):
        exploration = explore_claiming_ages(couple(milestones=[ends], income_streams=streams))
        assert not any(p.earnings_test_withholds for p in exploration.persons)


def test_withholding_is_attributed_to_the_earner_and_matches_the_household_total():
    # Partner claims at 62 while working: only the partner's earnings withhold.
    p = couple(income_streams=[ss(), ss("spouse", 15_000, claim=62), salary("spouse")])
    result = run_simulation(p)
    withheld = [s for s in result.yearly_snapshots if s.ss_earnings_test_withheld > 0]
    assert withheld
    for snap in withheld:
        assert snap._ss_earnings_test_withheld_by_earner == {"spouse": pytest.approx(snap.ss_earnings_test_withheld)}
    # Engine-only: never serialized.
    assert "_ss_earnings_test_withheld_by_earner" not in withheld[0].model_dump()


# --- Apply patch round trip --------------------------------------------------

def test_apply_patch_reproduces_the_candidate():
    ms = MilestoneData(id="ss", name="SS begins", trigger_type="age", trigger_value=66)
    p = couple(milestones=[ms], income_streams=[ss(claim=None, start_milestone_id="ss", start_month=4),
                                                ss("spouse", 15_000, claim=None, start_milestone_id="ss")])
    exploration = explore_claiming_ages(p)
    for self_age, spouse_age in ((62, 70), (69, 64)):
        applied = copy.deepcopy(p)
        for patch in exploration.patches:
            if (patch.owner, patch.claiming_age) in (("self", self_age), ("spouse", spouse_age)):
                applied.income_streams = [replace(i, **patch.changes) if i.id == patch.income_id else i
                                          for i in applied.income_streams]
        run = next(r for r in exploration.runs
                   if r.claim_ages == {"self": float(self_age), "spouse": float(spouse_age)})
        assert run_simulation(applied).yearly_snapshots[-1].net_worth == run.end_net_worth
