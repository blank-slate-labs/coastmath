"""Cross-cut tax-invariant suite across all personas.

Engine-level invariants on the ``YearSnapshot`` tax fields, fanned out across
all five personas (FIRE, High-Earner Late Saver, Self-Employed SEPP, Inherited
IRA, HNW Estate) via ``@pytest.mark.parametrize`` over the cartesian product of
persona × checkpoint age so each case is isolated and individual failures
don't short-circuit sibling invariants.

These are *not* baseline comparisons — every assertion follows from the engine
contract alone (decomposition, rate bounds, FICA on earned income, no state
tax in full-year NV/TX/FL/WA cases, resident-period CA tax). A violation
indicates a real engine bug, not a numeric drift.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import YearSnapshot
from tests.persona.harness import (
    build_plan_from_fixture,
    load_persona_fixture,
)

CHECKPOINT_AGES = [33, 35, 40, 45, 50, 55, 60, 65, 75, 85]

# No-state-income-tax jurisdictions (rounding tolerance applies).
_NO_STATE_TAX_STATES = {"NV", "TX", "FL", "WA", "SD", "AK", "WY", "TN", "NH"}


@dataclass(frozen=True)
class ResidencySegment:
    """Inclusive-start, exclusive-end age range with a state code.

    ``start_age=None`` means ``-inf`` (applies from plan start); ``end_age=None``
    means ``+inf`` (applies through end of plan).
    """
    start_age: int | None
    end_age: int | None
    state_code: str

    def contains(self, age: int) -> bool:
        if self.start_age is not None and age < self.start_age:
            return False
        return self.end_age is None or age < self.end_age


@dataclass(frozen=True)
class PersonaSpec:
    name: str
    retire_age: int
    residency: tuple[ResidencySegment, ...]

    def state_at(self, age: int) -> str:
        for seg in self.residency:
            if seg.contains(age):
                return seg.state_code
        raise AssertionError(
            f"persona {self.name!r} has no residency segment covering age {age}"
        )


PERSONAS: list[PersonaSpec] = [
    PersonaSpec(
        name="fire_persona",
        retire_age=45,
        residency=(
            ResidencySegment(start_age=None, end_age=35, state_code="CA"),
            ResidencySegment(start_age=35, end_age=None, state_code="NV"),
        ),
    ),
    PersonaSpec(
        name="high_earner_late_saver",
        retire_age=65,
        residency=(ResidencySegment(None, None, "TX"),),
    ),
    PersonaSpec(
        name="self_employed_sepp",
        retire_age=50,
        residency=(ResidencySegment(None, None, "FL"),),
    ),
    PersonaSpec(
        name="inherited_ira",
        retire_age=65,
        residency=(ResidencySegment(None, None, "CA"),),
    ),
    PersonaSpec(
        name="hnw_estate",
        retire_age=65,
        residency=(ResidencySegment(None, None, "WA"),),
    ),
]


# Cache simulation results so the 50-case fan-out doesn't re-run the engine
# 10× per persona (once per checkpoint age).
_RESULT_CACHE: dict[str, list[YearSnapshot]] = {}


def _snapshots_for(persona: PersonaSpec) -> dict[int, YearSnapshot]:
    if persona.name not in _RESULT_CACHE:
        fixture = load_persona_fixture(persona.name)
        plan = build_plan_from_fixture(fixture)
        result = run_simulation(plan)
        _RESULT_CACHE[persona.name] = list(result.yearly_snapshots)
    return {snap.age: snap for snap in _RESULT_CACHE[persona.name]}


def _fmt(v: float) -> str:
    return f"${v:,.2f}"


# Absolute floating-point tolerance for "is zero" comparisons on dollar
# amounts — a few cents of rounding drift shouldn't flag.
_ZERO_TOL = 1.0


@pytest.mark.persona_regression
@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.name)
@pytest.mark.parametrize("age", CHECKPOINT_AGES)
def test_tax_invariants(persona: PersonaSpec, age: int) -> None:
    by_age = _snapshots_for(persona)
    snap = by_age.get(age)
    if snap is None:
        pytest.skip(f"{persona.name}: no snapshot at age {age}")

    ctx = f"{persona.name} @ age {age}"

    # ------------------------------------------------------------------
    # (1) Decomposition identity: the exposed tax components sum to the
    # recorded total tax, including the resident local income tax. AMT is
    # folded into federal_tax via max(regular_tax, amt_tax) inside the tax
    # engine, so amt_tax is exposed for observability but NOT included in
    # this sum (would double-count). NIIT and the early-withdrawal penalty
    # are separate additions to total tax and must be included here.
    # ------------------------------------------------------------------
    component_sum = (
        snap.federal_tax
        + snap.state_tax
        + snap.local_tax
        + snap.capital_gains_tax
        + snap.fica_tax
        + snap.niit_tax
        + snap.early_withdrawal_penalty
    )
    decomp_gap = abs(snap.taxes - component_sum)
    decomp_tol = max(_ZERO_TOL, abs(snap.taxes) * 0.001)
    assert decomp_gap <= decomp_tol, (
        f"{ctx}: tax decomposition leak of {_fmt(decomp_gap)} — "
        f"taxes={_fmt(snap.taxes)} vs "
        f"federal+state+local+cg+fica+niit+ewp={_fmt(component_sum)}"
    )

    # ------------------------------------------------------------------
    # (2) Effective tax rate sanity bound. The engine's effective_rate
    # uses a broader denominator than raw W2 gross_income (it includes
    # SS, Roth conversions, taxable RMD, and capital gains) so it's the
    # right field for a "is this rate plausible?" check.
    # ------------------------------------------------------------------
    assert 0.0 <= snap.effective_rate <= 0.65, (
        f"{ctx}: effective_rate={snap.effective_rate:.4f} outside "
        f"plausible [0, 0.65] bound — possible denominator bug or "
        f"runaway tax computation"
    )

    # ------------------------------------------------------------------
    # (3) Pre-retirement payroll tax. All five personas carry earned
    # income (W2 or self-employment) every pre-retirement year by
    # fixture construction, so FICA must be positive. The retirement
    # year itself is skipped — partial-year W2 still produces FICA, but
    # skipping makes the invariant robust to transitional edge cases.
    # ------------------------------------------------------------------
    if age < persona.retire_age:
        assert snap.fica_tax > 0, (
            f"{ctx}: pre-retirement (retire_age={persona.retire_age}) "
            f"should have payroll tax > 0 on earned income; got "
            f"fica_tax={_fmt(snap.fica_tax)}"
        )

    # ------------------------------------------------------------------
    # (4) Post-retirement payroll tax. Once earned income ends, FICA
    # ends too. Social Security and RMDs are not wage-like and do not
    # generate FICA.
    # ------------------------------------------------------------------
    if age > persona.retire_age:
        assert snap.fica_tax < _ZERO_TOL, (
            f"{ctx}: post-retirement (retire_age={persona.retire_age}) "
            f"should have zero payroll tax; got "
            f"fica_tax={_fmt(snap.fica_tax)}"
        )

    # ------------------------------------------------------------------
    # (5) CA residency: gross income above the standard deduction must
    # produce state tax. CA's brackets begin low, but the CA standard
    # deduction shields small RMDs/income from state tax.
    # ------------------------------------------------------------------
    state = persona.state_at(age)
    if state == "CA" and snap.gross_income > snap.deduction_amount:
        assert snap.state_tax > 0, (
            f"{ctx}: CA resident with gross_income="
            f"{_fmt(snap.gross_income)} above deduction="
            f"{_fmt(snap.deduction_amount)} must owe state tax; got "
            f"state_tax={_fmt(snap.state_tax)}"
        )

    # ------------------------------------------------------------------
    # (6) A no-tax destination does not erase earlier resident-period wages.
    # The FIRE fixture moves on its June birthday and works the whole move
    # year. FTB part-year rules retain the preceding CA wages. Other cases
    # below spend the full calendar year in a no-state-income-tax jurisdiction.
    # https://www.ftb.ca.gov/file/personal/residency-status/part-year-and-nonresident.html
    # ------------------------------------------------------------------
    if state in _NO_STATE_TAX_STATES:
        birth_month = load_persona_fixture(persona.name).get("birth_month", 1) or 1
        moved_from_ca_during_year = persona.state_at(age - 1) == "CA" and birth_month > 1
        if moved_from_ca_during_year:
            assert age < persona.retire_age, "This fixture invariant requires wages before the move"
            assert snap.state_tax > 0, (
                f"{ctx}: wages received while resident in CA remain taxable after "
                f"the move to {state}; got state_tax={_fmt(snap.state_tax)}"
            )
        else:
            assert abs(snap.state_tax) < _ZERO_TOL, (
                f"{ctx}: full-calendar {state} case has no state income tax; got "
                f"state_tax={_fmt(snap.state_tax)}"
            )
