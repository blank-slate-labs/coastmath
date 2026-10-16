"""Rule of 55 (IRC 72(t)(2)(A)(v)): separation in or after the year the person turns 55."""
import pytest

from coastmath.engine.types import AccountInfo, DrawdownEntryData, SimState
from coastmath.engine.waterfall import (
    blend_source_eligible,
    execute_drawdown,
    penalty_free_by_separation,
)


@pytest.mark.parametrize(("separation_year", "year", "age", "exempt"), [
    # Turns 55 in 2030. Separation in that year qualifies; the year before does not.
    (2030, 2030, 55, True),
    (2029, 2029, 54, False),
    (2029, 2030, 55, False),
    (2030, 2032, 57, True),
    (2028, 2032, 58, False),
    # A separation date after the distribution year cannot help.
    (2031, 2030, 55, False),
])
def test_separation_year_boundary(separation_year, year, age, exempt):
    assert penalty_free_by_separation("traditional_401k", None, {"separation_year": separation_year}, age, year) is exempt


@pytest.mark.parametrize("kind", ["traditional_ira", "roth_ira", "sep_ira", "simple_ira"])
def test_ira_family_never_qualifies(kind):
    assert not penalty_free_by_separation(kind, None, {"separation_year": 2020}, 60, 2030)


def test_inherited_accounts_and_missing_metadata_do_not_qualify():
    assert not penalty_free_by_separation("traditional_401k", 2024, {"separation_year": 2020}, 60, 2030)
    assert not penalty_free_by_separation("traditional_401k", None, None, 60, 2030)
    assert not penalty_free_by_separation("traditional_401k", None, {}, 60, 2030)


@pytest.mark.parametrize("kind", ["traditional_401k", "traditional_403b"])
def test_workplace_plans_qualify(kind):
    assert penalty_free_by_separation(kind, None, {"separation_year": 2028}, 57, 2030)


def _state(kind, settings, age=56):
    state = SimState(2030, accounts={"plan": AccountInfo(200_000, kind, distribution_settings=settings)})
    state.owner_ages = {"self": age}
    return state


def test_drawdown_charges_the_penalty_without_separation_and_none_with_it():
    order = [DrawdownEntryData(1, "plan")]
    _, plain = execute_drawdown(20_000, order, _state("traditional_401k", None), age=56, birth_month=1)
    _, exempt = execute_drawdown(20_000, order, _state("traditional_401k", {"separation_year": 2029}), age=56, birth_month=1)
    assert plain > 0
    assert exempt == 0


def test_ira_with_separation_metadata_still_pays_the_penalty():
    order = [DrawdownEntryData(1, "ira")]
    state = SimState(2030, accounts={"ira": AccountInfo(200_000, "traditional_ira",
                                                         distribution_settings={"separation_year": 2029})})
    state.owner_ages = {"self": 56}
    _, penalty = execute_drawdown(20_000, order, state, age=56, birth_month=1)
    assert penalty > 0


def test_owner_specific_age_is_used_for_spouse_accounts():
    state = SimState(2030, accounts={"plan": AccountInfo(
        200_000, "traditional_401k", owner="spouse", distribution_settings={"separation_year": 2029})})
    # The primary is 66, the account holder only 54: not eligible despite the primary's age.
    state.owner_ages = {"self": 66, "spouse": 54}
    _, penalty = execute_drawdown(20_000, [DrawdownEntryData(1, "plan")], state, age=66, birth_month=1)
    assert penalty > 0


def test_tax_target_blending_treats_exempt_plan_as_penalty_free():
    exempt = _state("traditional_401k", {"separation_year": 2029})
    plain = _state("traditional_401k", None)
    assert blend_source_eligible("plan", exempt, age=56, birth_month=1, sepp_account_ids=set())
    assert not blend_source_eligible("plan", plain, age=56, birth_month=1, sepp_account_ids=set())
