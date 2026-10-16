"""Milestone trigger-year invariant suite.

Parametrized across all five personas. No baselines: these assertions verify
milestone event semantics hold end-to-end. Specifically:

* **Age-triggered milestones** fire in ``year == birth_year + age`` and their
  IDs surface in ``YearSnapshot.milestones_triggered``.
* **Partial-year salary pro-rating**: income streams with NULL
  ``end_month`` bound to an age-triggered retire milestone pay
  ``(birth_month - 1) / 12`` of their grown annual amount in the trigger year.
* **Residency-bound state_code switches**: when a milestone flips
  residency, ``state_tax`` reflects the new state in the trigger year and
  thereafter.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import YearSnapshot
from tests.persona.harness import build_plan_from_fixture, load_persona_fixture

PLAN_START_YEAR = 2026


@dataclass(frozen=True)
class PartialStream:
    """A retire-bound income stream whose trigger-year amount we assert."""

    name: str
    annual_amount: float
    growth_rate: float


@dataclass(frozen=True)
class ResidencySwitch:
    """Describes a milestone-driven state change to assert around."""

    trigger_age: int
    pre_age: int
    pre_state_has_tax: bool
    post_state_has_tax: bool


@dataclass(frozen=True)
class PersonaSpec:
    name: str
    birth_year: int
    birth_month: int
    age_milestones: tuple[tuple[str, int], ...]
    retire_age: int
    partial_streams: tuple[PartialStream, ...]
    state_switch: ResidencySwitch | None = None


PERSONAS: tuple[PersonaSpec, ...] = (
    PersonaSpec(
        name="fire_persona",
        birth_year=1994,
        birth_month=6,
        age_milestones=(
            ("00000000-0000-4000-8000-00000000f010", 35),  # Move CA to NV
            ("00000000-0000-4000-8000-00000000f011", 45),  # Retire
        ),
        retire_age=45,
        partial_streams=(PartialStream("W2 Salary", 180_000.0, 0.03),),
        state_switch=ResidencySwitch(
            trigger_age=35,
            pre_age=34,
            pre_state_has_tax=True,
            post_state_has_tax=False,
        ),
    ),
    PersonaSpec(
        name="high_earner_late_saver",
        birth_year=1976,
        birth_month=3,
        age_milestones=(
            ("00000000-0000-4000-8000-000000021010", 65),  # Retire
            ("00000000-0000-4000-8000-000000021011", 65),  # Spouse Retire
            ("00000000-0000-4000-8000-000000021012", 67),  # Social Security Start
        ),
        retire_age=65,
        partial_streams=(
            PartialStream("W2 Salary", 300_000.0, 0.03),
            PartialStream("Spouse W2 Salary", 150_000.0, 0.03),
        ),
    ),
    PersonaSpec(
        name="self_employed_sepp",
        birth_year=1988,
        birth_month=9,
        age_milestones=(
            ("00000000-0000-4000-8000-000000022010", 50),  # Retire (SEPP)
            ("00000000-0000-4000-8000-000000022011", 67),  # Social Security Begins
        ),
        retire_age=50,
        partial_streams=(PartialStream("Self-Employment Income", 220_000.0, 0.03),),
    ),
    PersonaSpec(
        name="inherited_ira",
        birth_year=1971,
        birth_month=1,
        age_milestones=(
            ("00000000-0000-4000-8000-000000023010", 65),  # Retire
        ),
        retire_age=65,
        partial_streams=(PartialStream("W2 Salary", 140_000.0, 0.03),),
    ),
    PersonaSpec(
        name="hnw_estate",
        birth_year=1966,
        birth_month=5,
        age_milestones=(
            ("00000000-0000-4000-8000-000000024010", 65),  # Retire
            ("00000000-0000-4000-8000-000000024011", 73),  # QCD Start
            ("00000000-0000-4000-8000-000000024012", 88),  # First to Die
        ),
        retire_age=65,
        partial_streams=(PartialStream("W2 Salary", 250_000.0, 0.03),),
    ),
)


@cache
def _simulate(persona_name: str) -> dict[int, YearSnapshot]:
    fixture = load_persona_fixture(persona_name)
    plan = build_plan_from_fixture(fixture)
    result = run_simulation(plan)
    return {snap.age: snap for snap in result.yearly_snapshots}


def _persona_id(spec: PersonaSpec) -> str:
    return spec.name


# ---------------------------------------------------------------------------
# 1. Age-triggered milestones fire in birth_year + age
# ---------------------------------------------------------------------------


@pytest.mark.persona_regression
@pytest.mark.parametrize("spec", PERSONAS, ids=_persona_id)
def test_age_milestones_fire_in_expected_year(spec: PersonaSpec) -> None:
    by_age = _simulate(spec.name)
    earliest_age = min(by_age)

    for milestone_id, age in spec.age_milestones:
        if age < earliest_age:
            # Persona's sim window starts later (e.g. High-Earner starts at 50);
            # a milestone whose age predates the window can't be asserted.
            continue

        assert age in by_age, (
            f"{spec.name}: expected a snapshot at age {age} "
            f"(year {spec.birth_year + age}); sim covers ages "
            f"{earliest_age}..{max(by_age)}"
        )
        snap = by_age[age]
        expected_year = spec.birth_year + age
        assert snap.year == expected_year, (
            f"{spec.name}: snapshot at age {age} should be year "
            f"{expected_year}; got {snap.year} (age offset drift?)"
        )
        assert milestone_id in snap.milestones_triggered, (
            f"{spec.name}: milestone {milestone_id} should fire in year "
            f"{expected_year} (age {age}); got milestones_triggered="
            f"{snap.milestones_triggered}"
        )


# ---------------------------------------------------------------------------
# 2. Partial-year salary: retire-year income = (birth_month-1)/12 × grown
# ---------------------------------------------------------------------------


@pytest.mark.persona_regression
@pytest.mark.parametrize("spec", PERSONAS, ids=_persona_id)
def test_retire_year_partial_salary(spec: PersonaSpec) -> None:
    by_age = _simulate(spec.name)
    if spec.retire_age not in by_age:
        pytest.skip(
            f"{spec.name}: retire age {spec.retire_age} outside simulation window"
        )

    snap = by_age[spec.retire_age]
    assert snap.cash_flow is not None, (
        f"{spec.name}: retire-year snapshot missing cash_flow breakdown"
    )

    trigger_year = spec.birth_year + spec.retire_age
    years_elapsed = trigger_year - PLAN_START_YEAR
    partial_fraction = max(0, spec.birth_month - 1) / 12.0

    stream_names = {s.name for s in spec.partial_streams}
    actual_salary = sum(
        src.amount
        for src in snap.cash_flow.income_sources
        if src.name in stream_names
    )

    expected_salary = sum(
        s.annual_amount * (1.0 + s.growth_rate) ** years_elapsed * partial_fraction
        for s in spec.partial_streams
    )

    if partial_fraction == 0.0:
        # birth_month=1 → (1-1)/12 = 0 → no salary credited in the trigger year.
        assert actual_salary == pytest.approx(0.0, abs=1.0), (
            f"{spec.name}: birth_month=1 forces 0/12 retire-year fraction; "
            f"expected $0.00 of retire-bound salary in year {trigger_year}, "
            f"got ${actual_salary:,.2f}"
        )
        return

    # ±1% tolerance: the formula is fully deterministic (no stochastic inputs,
    # no tax branching) — larger drift indicates a real regression.
    tolerance = max(expected_salary * 0.01, 1.0)
    assert abs(actual_salary - expected_salary) <= tolerance, (
        f"{spec.name}: retire-year (age {spec.retire_age}, year {trigger_year}) "
        f"partial salary expected ≈ ${expected_salary:,.2f} "
        f"[{partial_fraction:.4f} × Σ(annual × (1+g)^{years_elapsed})]; "
        f"got ${actual_salary:,.2f} — possible regression of the "
        f"pro-rated-salary semantics"
    )


# ---------------------------------------------------------------------------
# 3. Residency-bound state_code switches
# ---------------------------------------------------------------------------


_STATE_SWITCH_PERSONAS: tuple[PersonaSpec, ...] = tuple(
    s for s in PERSONAS if s.state_switch is not None
)


@pytest.mark.persona_regression
@pytest.mark.parametrize("spec", _STATE_SWITCH_PERSONAS, ids=_persona_id)
def test_residency_switch_state_tax(spec: PersonaSpec) -> None:
    by_age = _simulate(spec.name)
    sw = spec.state_switch
    assert sw is not None  # narrowed by the parametrization above
    assert sw.pre_age in by_age, f"{spec.name}: no snapshot at pre_age {sw.pre_age}"
    assert sw.trigger_age in by_age, f"{spec.name}: no snapshot at trigger_age"
    assert (sw.trigger_age + 1) in by_age, f"{spec.name}: no snapshot at post_age"

    pre_tax = by_age[sw.pre_age].state_tax
    trigger_tax = by_age[sw.trigger_age].state_tax
    post_tax = by_age[sw.trigger_age + 1].state_tax

    # Sanity anchor on the year before the move: confirm the old state's tax
    # regime is being applied at all.
    if sw.pre_state_has_tax:
        assert pre_tax > 1_000, (
            f"{spec.name}: pre-switch age {sw.pre_age} should pay meaningful "
            f"state income tax; got ${pre_tax:,.2f}"
        )
    else:
        assert abs(pre_tax) < 100.0, (
            f"{spec.name}: pre-switch age {sw.pre_age} should have ~0 state "
            f"tax; got ${pre_tax:,.2f}"
        )

    # The year AFTER the trigger is the strict assertion: residency is fully
    # resolved to the new state, so state_tax reflects the new regime.
    if sw.post_state_has_tax:
        assert post_tax > 1_000, (
            f"{spec.name}: age {sw.trigger_age + 1} (post-switch) should pay "
            f"meaningful state tax in new state; got ${post_tax:,.2f}"
        )
    else:
        assert abs(post_tax) < 100.0, (
            f"{spec.name}: age {sw.trigger_age + 1} (post-switch) should have "
            f"~0 state tax in new no-income-tax state; got ${post_tax:,.2f}"
        )

    # The trigger year itself is a ratchet rather than a strict bound: today
    # `resolve_state_for_year` picks one state per full year, so FIRE's age 35
    # lands fully in NV (near zero). If the engine later prorates residency
    # within a trigger year, age 35 could carry partial pre-state tax — which
    # must still be strictly less than age 34's full pre-state burden.
    if sw.pre_state_has_tax and not sw.post_state_has_tax:
        assert trigger_tax < pre_tax, (
            f"{spec.name}: trigger-year (age {sw.trigger_age}) state tax "
            f"${trigger_tax:,.2f} should be strictly less than pre-move "
            f"(age {sw.pre_age}) state tax ${pre_tax:,.2f} — direction of "
            f"the CA→NV switch is wrong"
        )
