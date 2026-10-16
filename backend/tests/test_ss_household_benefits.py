"""PIA-basis Social Security: claim factors, COLA, spousal and survivor rules."""

import pytest

from coastmath.engine.household_lifecycle import LAST_SURVIVOR
from coastmath.engine.simulator import run_simulation
from coastmath.engine.ss_household import (
    PiaRecord,
    spousal_reduction_factor,
    survivor_monthly_benefit,
    survivor_reduction_factor,
)
from coastmath.engine.survivor_social_security import survivor_fra_months
from coastmath.engine.types import (
    EstateSettingsData,
    IncomeData,
)
from tests.engine_support import source
from tests.ss_household_support import couple, pia_ss, plan


@pytest.mark.parametrize(("claim", "factor"), [(62, 0.70), (67, 1.0), (70, 1.24)])
def test_claim_age_changes_benefit_by_ssa_factor(claim, factor):
    result = run_simulation(plan(income_streams=[pia_ss("self", 2_000, claim)]))
    claim_year = 1966 + claim
    assert source(result, claim_year - 1, "self SS") == 0
    assert source(result, claim_year, "self SS") == pytest.approx(24_000 * factor)


def test_pia_ignores_saved_annual_amount_and_amount_basis_is_unchanged():
    amount = IncomeData(
        id="a", name="amount SS", annual_amount=18_000, tax_category="social_security",
        claiming_age=62, growth_rate=0, pia_monthly=2_000,
    )
    result = run_simulation(plan(income_streams=[amount]))
    assert source(result, 2028, "amount SS") == pytest.approx(18_000)


def test_claim_year_is_prorated_by_month():
    result = run_simulation(plan(birth_month=7, income_streams=[pia_ss("self", 2_000, 67)]))
    assert source(result, 2033, "self SS") == pytest.approx(24_000 * 6 / 12)
    assert source(result, 2034, "self SS") == pytest.approx(24_000)


def test_cola_grows_from_plan_start():
    result = run_simulation(plan(income_streams=[pia_ss("self", 2_000, 67, growth=0.02)]))
    assert source(result, 2033, "self SS") == pytest.approx(24_000 * 1.02 ** 7)
    assert source(result, 2035, "self SS") == pytest.approx(24_000 * 1.02 ** 9)


def test_blank_growth_follows_plan_inflation():
    p = plan(income_streams=[pia_ss("self", 2_000, 67, growth=None)])
    p.assumptions.inflation_rate = 0.025
    result = run_simulation(p)
    assert source(result, 2033, "self SS") == pytest.approx(24_000 * 1.025 ** 7)


def test_expected_percent_haircut_applies_to_own_and_spousal():
    p = couple(spouse_birth_year=1966, income_streams=[
        pia_ss("self", 3_000, 67, pct=80), pia_ss("spouse", 1_000, 67, pct=80),
    ])
    result = run_simulation(p)
    assert source(result, 2033, "self SS") == pytest.approx(36_000 * 0.8)
    assert source(result, 2033, "spouse SS") == pytest.approx(12_000 * 0.8)
    assert source(result, 2033, "spouse SS (spousal)") == pytest.approx(500 * 12 * 0.8)


def test_spousal_excess_at_full_retirement_age():
    result = run_simulation(couple(income_streams=[
        pia_ss("self", 3_000, 67), pia_ss("spouse", 1_000, 67),
    ]))
    assert source(result, 2032, "spouse SS (spousal)") == 0
    assert source(result, 2033, "spouse SS (spousal)") == pytest.approx(6_000)
    # The higher earner has no excess over half the lower PIA.
    assert source(result, 2033, "self SS (spousal)") == 0


def test_spousal_early_reduction_and_own_reduction():
    result = run_simulation(couple(income_streams=[
        pia_ss("self", 3_000, 64), pia_ss("spouse", 1_000, 64),
    ]))
    # 36 months early: own 80%, spousal 75% (25/36 of 1% per month).
    assert source(result, 2030, "spouse SS") == pytest.approx(12_000 * 0.8)
    assert source(result, 2030, "spouse SS (spousal)") == pytest.approx(6_000 * 0.75)


def test_spousal_beyond_36_months_uses_five_twelfths():
    assert spousal_reduction_factor(60) == pytest.approx(0.65)
    result = run_simulation(couple(income_streams=[
        pia_ss("self", 3_000, 62), pia_ss("spouse", 1_000, 62),
    ]))
    assert source(result, 2028, "spouse SS (spousal)") == pytest.approx(6_000 * 0.65)


def test_spousal_waits_for_worker_to_file():
    result = run_simulation(couple(spouse_birth_year=1966, birth_year=1963, income_streams=[
        pia_ss("self", 3_000, 70), pia_ss("spouse", 1_000, 62),
    ]))
    # Spouse files at 62 in 2028; the worker files at 70 in 2033 when the
    # spouse is 67 (FRA): the excess starts then, unreduced.
    assert source(result, 2028, "spouse SS") == pytest.approx(12_000 * 0.7)
    assert source(result, 2032, "spouse SS (spousal)") == 0
    assert source(result, 2033, "spouse SS (spousal)") == pytest.approx(6_000)


def test_spousal_reduction_uses_age_when_worker_files():
    result = run_simulation(couple(birth_year=1966, spouse_birth_year=1966, income_streams=[
        pia_ss("self", 3_000, 64), pia_ss("spouse", 1_000, 62),
    ]))
    # Spousal entitlement begins at 64 (36 months early), not at 62.
    assert source(result, 2029, "spouse SS (spousal)") == 0
    assert source(result, 2030, "spouse SS (spousal)") == pytest.approx(6_000 * 0.75)


def test_two_active_pia_streams_for_one_person_are_rejected():
    second = pia_ss("self", 500, 67)
    second.id = "other"
    with pytest.raises(ValueError, match="only one active PIA-basis"):
        run_simulation(plan(income_streams=[pia_ss("self", 2_000, 67), second]))


# --- Survivor rules -------------------------------------------------------

def record(pia, birth_year, claim_age_months, birth_month=1):
    birth = birth_year * 12 + birth_month - 1
    return PiaRecord(
        IncomeData(id="d", name="d", annual_amount=0, pia_monthly=pia), birth_year, birth,
        birth + claim_age_months,
    )


def test_survivor_reduction_reaches_71_5_percent_at_60():
    fra = survivor_fra_months(1962)
    assert survivor_reduction_factor(fra - 720, fra) == pytest.approx(0.715)
    assert survivor_reduction_factor(0, fra) == 1.0


def test_survivor_rib_limit_floor_at_survivor_fra():
    deceased = record(2_000, 1960, 62 * 12)  # 30% reduction: RIB 1,400
    death = 1960 * 12 + 75 * 12
    survivor_birth = 1962 * 12
    fra = survivor_fra_months(1962)
    benefit = survivor_monthly_benefit(deceased, survivor_birth, fra, death, survivor_birth + fra)
    assert benefit == pytest.approx(2_000 * 0.825)


def test_survivor_rib_limit_applies_after_early_survivor_reduction():
    deceased = record(2_000, 1960, 62 * 12)
    death = 1960 * 12 + 63 * 12
    survivor_birth = 1962 * 12
    fra = survivor_fra_months(1962)
    benefit = survivor_monthly_benefit(deceased, survivor_birth, fra, death, survivor_birth + 720)
    # 71.5% of PIA is below the 82.5% limit, so the limit does not bind.
    assert benefit == pytest.approx(2_000 * 0.715)


def test_survivor_died_before_claiming_before_fra_gets_pia():
    deceased = record(2_000, 1960, 70 * 12)
    death = 1960 * 12 + 65 * 12 + 11
    fra = survivor_fra_months(1962)
    benefit = survivor_monthly_benefit(deceased, 1962 * 12, fra, death, 1962 * 12 + fra)
    assert benefit == pytest.approx(2_000)


def test_survivor_died_after_fra_before_claiming_keeps_delayed_credits():
    deceased = record(2_000, 1960, 70 * 12)
    # Death in month 69y0m: credits through the prior month (23 months past FRA 67).
    death = 1960 * 12 + 69 * 12
    fra = survivor_fra_months(1962)
    benefit = survivor_monthly_benefit(deceased, 1962 * 12, fra, death, 1962 * 12 + fra)
    assert benefit == pytest.approx(2_000 * (1 + 23 * 0.08 / 12))


def test_survivor_after_delayed_claim_gets_full_increased_benefit():
    deceased = record(2_000, 1960, 70 * 12)
    death = 1960 * 12 + 75 * 12
    fra = survivor_fra_months(1962)
    benefit = survivor_monthly_benefit(deceased, 1962 * 12, fra, death, 1962 * 12 + fra)
    assert benefit == pytest.approx(2_000 * 1.24)


def survivor_plan(self_claim, spouse_claim, self_pia=2_000, spouse_pia=800, **changes):
    p = couple(
        birth_year=1950, birth_month=1, life_expectancy=76,
        spouse_birth_year=1952, spouse_birth_month=7, spouse_life_expectancy=80,
        estate_settings=EstateSettingsData(
            household_lifecycle=LAST_SURVIVOR,
            survivor_social_security_policy="claimed_benefit_at_survivor_fra",
            survivor_social_security_eligibility_confirmed=True,
            survivor_social_security_eligibility_source="Synthetic eligibility fixture",
        ),
        income_streams=[pia_ss("self", self_pia, self_claim), pia_ss("spouse", spouse_pia, spouse_claim)],
    )
    for key, value in changes.items():
        setattr(p, key, value)
    return p


def test_pia_survivor_top_up_uses_rib_limit_and_replaces_spousal():
    result = run_simulation(survivor_plan(62, 67))
    # Self (FRA 66) claimed at 62: RIB 75% of 2,000 = 1,500; limit 82.5% = 1,650.
    # Spouse (FRA 66) claimed at 67: own 800 x 1.08 = 864.
    assert source(result, 2026, "self SS") == pytest.approx(18_000)
    assert source(result, 2026, "spouse SS") == pytest.approx(864 * 12)
    assert source(result, 2026, "spouse SS (spousal)") == pytest.approx(200 * 12)
    assert source(result, 2027, "spouse SS (spousal)") == 0
    assert source(result, 2027, "spouse SS") == pytest.approx(864 * 12)
    assert source(result, 2027, "Social Security survivor top-up") == pytest.approx((1_650 - 864) * 12)
    assert any("both spouses' PIAs" in w for w in result.metadata.warnings)


def test_pia_survivor_own_benefit_larger_means_no_top_up():
    result = run_simulation(survivor_plan(62, 67, self_pia=1_000, spouse_pia=1_500))
    assert source(result, 2027, "Social Security survivor top-up") == 0


def test_pia_survivor_starts_at_survivor_claim_when_later():
    p = survivor_plan(66, 70, spouse_birth_year=1960, spouse_birth_month=1, spouse_life_expectancy=90)
    result = run_simulation(p)
    # Spouse (born 1960, claims 70 in 2030) only receives survivor benefits from 2030.
    assert source(result, 2029, "Social Security survivor top-up") == 0
    own = 800 * 1.24
    assert source(result, 2030, "Social Security survivor top-up") == pytest.approx((2_000 - own) * 12)


def test_mixed_basis_survivor_is_rejected():
    p = survivor_plan(62, 67)
    p.income_streams[1].ss_benefit_basis = "amount"
    p.income_streams[1].annual_amount = 9_000
    with pytest.raises(ValueError, match="both spouses' benefits to use PIA basis"):
        run_simulation(p)


def test_pia_survivor_without_policy_has_no_top_up():
    p = survivor_plan(62, 67)
    p.estate_settings.survivor_social_security_policy = "off"
    result = run_simulation(p)
    assert source(result, 2027, "Social Security survivor top-up") == 0
    assert source(result, 2027, "spouse SS (spousal)") == 0
