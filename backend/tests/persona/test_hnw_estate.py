"""E2E regression test for the High Net Worth Estate persona.

Exercises the WA state estate tax path, the QCD charity engine, and the
spouse-death (first-to-die) event. The persona starts at age 60 and runs
through terminal year (age 89, given life_expectancy=90 and exclusive-end
loop semantics — see simulator.run_simulation).

Baseline comparison at the ages that the shared CHECKPOINT_AGES grid emits
for a start-age-60 plan (60, 65, 75, 85). Spot assertions target engine
behavior that is not captured by the scalar baseline fields: peak wealth,
RMD activation, QCD federal-tax reduction, and terminal estate-tax /
net-legacy.
"""

from __future__ import annotations

import copy

import pytest

from coastmath.engine.simulator import run_simulation
from tests.persona.harness import (
    assert_snapshot_near,
    build_plan_from_fixture,
    load_persona_baseline,
    load_persona_fixture,
)

PERSONA_NAME = "hnw_estate"
# Subset of the shared grid that a start-age-60 plan actually emits.
BASELINE_CHECKPOINT_AGES = [60, 65, 75, 85]
TERMINAL_AGE = 89  # life_expectancy=90 + exclusive end_year in range()


@pytest.mark.persona_regression
def test_hnw_estate_regression() -> None:
    fixture = load_persona_fixture(PERSONA_NAME)
    baseline = load_persona_baseline(PERSONA_NAME)
    assert baseline, (
        f"Missing baseline for {PERSONA_NAME}. Regenerate via "
        "`python -m scripts.regenerate_persona_baseline hnw_estate`."
    )

    plan = build_plan_from_fixture(fixture)
    result = run_simulation(plan)

    assert result.metadata.failure_year is None, (
        f"HNW Estate persona should remain viable; got failure_year="
        f"{result.metadata.failure_year}"
    )

    by_age = {snap.age: snap for snap in result.yearly_snapshots}

    # --- Baseline comparison at the ages emitted for this persona ---
    for age in BASELINE_CHECKPOINT_AGES:
        assert age in by_age, f"No snapshot emitted for age {age}"
        assert str(age) in baseline, f"Baseline missing checkpoint age {age}"
        assert_snapshot_near(
            by_age[age],
            baseline[str(age)],
            tolerance_pct=0.5,
            context=f"age {age}",
            persona=PERSONA_NAME,
        )

    # --- Spot assertions (engine invariants, not baseline-derived) ---

    # Peak wealth: total net worth should clear $7M somewhere between ages
    # 60-70 — seeded liquid assets = $7M, plus pre-retirement growth.
    peak = max(by_age[a].net_worth for a in range(60, 71) if a in by_age)
    assert peak > 7_000_000, (
        f"Expected peak wealth > $7M between ages 60-70; got ${peak:,.2f}"
    )

    # RMD activation: SECURE 2.0 start age for birth_year=1966 is 75 (see
    # rmd.get_rmd_start_age). The IRA is withdrawn in the RMD step before
    # the waterfall runs, so the draw does NOT appear in cash_flow.drawdowns
    # (that list only tracks waterfall drawdowns). Verify RMDs fired by
    # comparing the age-75 IRA balance to a no-RMD growth projection:
    # without RMDs it would be $1.5M × 1.07^15 ≈ $4.14M; with RMDs plus
    # reinvestment churn the balance should be materially different.
    assert result.metadata.rmd_start_age == 75, (
        f"birth_year=1966 → expected RMD start age 75; "
        f"got {result.metadata.rmd_start_age}"
    )
    ira_id = "00000000-0000-4000-8000-000000024003"
    ira_74 = by_age[74].accounts.get(ira_id, 0.0)
    ira_75 = by_age[75].accounts.get(ira_id, 0.0)
    # With a $4.1M+ IRA and divisor ≈ 24.6 at age 75, the RMD is ~$170k.
    # Year-over-year growth (7%) alone would add ~$290k. Net change should
    # therefore be smaller than pure 7% growth — confirms RMD fired.
    assert ira_75 < ira_74 * 1.07, (
        f"age-75 IRA balance (${ira_75:,.2f}) should trail pure 7% growth "
        f"(${ira_74 * 1.07:,.2f}) once RMDs begin; got a gap of "
        f"${ira_74 * 1.07 - ira_75:,.2f}"
    )

    # Terminal net_legacy: WA state estate tax is enabled (flat 20% over
    # $2.193M exemption). By terminal year the estate far exceeds this
    # exemption, so estate_tax > 0 and net_legacy > 0 both hold.
    assert result.metadata.net_legacy is not None, "SimMetadata.net_legacy should be populated"
    legacy = result.metadata.net_legacy.model_dump()
    assert legacy["gross_estate"] > 2_193_000, (
        f"gross_estate should exceed WA exemption ($2.193M); "
        f"got ${legacy['gross_estate']:,.2f}"
    )
    assert legacy["estate_tax"] > 0, (
        f"WA estate tax should be > $0 when estate exceeds threshold; "
        f"got ${legacy['estate_tax']:,.2f}"
    )
    assert legacy["net_legacy"] > 0, (
        f"net_legacy should be > 0; got ${legacy['net_legacy']:,.2f}"
    )

    assert TERMINAL_AGE in by_age, f"No terminal snapshot at age {TERMINAL_AGE}"


@pytest.mark.persona_regression
def test_hnw_estate_qcd_reduces_federal_tax() -> None:
    """Running the same fixture without QCD charity should yield strictly
    higher federal tax during the RMD years (age 75+), since QCDs suppress
    taxable IRA distributions. A measurable positive delta is the engine's
    contract — an unchanged federal_tax would mean the QCD wiring is broken.
    """
    fixture_with_qcd = load_persona_fixture(PERSONA_NAME)
    fixture_without_qcd = copy.deepcopy(fixture_with_qcd)
    fixture_without_qcd["charity_entities"] = []

    plan_with = build_plan_from_fixture(fixture_with_qcd)
    plan_without = build_plan_from_fixture(fixture_without_qcd)

    result_with = run_simulation(plan_with)
    result_without = run_simulation(plan_without)

    with_by_age = {s.age: s for s in result_with.yearly_snapshots}
    without_by_age = {s.age: s for s in result_without.yearly_snapshots}

    fed_with = sum(
        with_by_age[a].federal_tax for a in range(75, 86) if a in with_by_age
    )
    fed_without = sum(
        without_by_age[a].federal_tax for a in range(75, 86) if a in without_by_age
    )

    assert fed_without > fed_with, (
        f"Expected QCD to reduce federal tax over ages 75-85; "
        f"got with_qcd=${fed_with:,.2f} vs without_qcd=${fed_without:,.2f}"
    )


@pytest.mark.persona_regression
def test_hnw_estate_first_to_die_engine_behavior() -> None:
    """First-to-die in this engine is driven by ``spouse.life_expectancy``,
    not a milestone. Partner death fires in year >= spouse_birth_year +
    spouse_life_expectancy = 1966 + 88 = 2054 (holder age 88). Verify the
    sim progresses through and past the spouse-death year without failure,
    and the terminal net_worth remains positive.

    The engine has no 'partial estate settlement' path — estate tax only
    fires at the terminal year, so this test makes no assertion about an
    age 89 estate settlement in the tax snapshot.
    """
    fixture = load_persona_fixture(PERSONA_NAME)
    plan = build_plan_from_fixture(fixture)
    result = run_simulation(plan)

    by_age = {s.age: s for s in result.yearly_snapshots}

    assert 88 in by_age, "Snapshot at age 88 (spouse-death year) missing"
    assert 89 in by_age, "Snapshot at age 89 (post-first-death) missing"
    assert result.metadata.failure_year is None

    assert by_age[89].net_worth > 0, (
        f"age 89 net_worth should remain positive; got ${by_age[89].net_worth:,.2f}"
    )
