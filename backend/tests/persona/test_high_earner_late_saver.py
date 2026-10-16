"""E2E regression test for the High-Earner Late Saver persona.

Verifies the ``high_earner_late_saver`` fixture's full-lifecycle simulation
matches the committed baseline at the checkpoint ages that fall within its
lifespan (age 50 start, 92 end), plus engine-invariant spot checks that are
independent of the baseline (TX state-tax, RMD emission at the SECURE Act 2.0
start age, and end-of-plan solvency).
"""

from __future__ import annotations

import pytest

from coastmath.engine.simulator import run_simulation
from tests.persona.harness import (
    assert_snapshot_near,
    build_plan_from_fixture,
    load_persona_baseline,
    load_persona_fixture,
)

PERSONA_NAME = "high_earner_late_saver"
CHECKPOINT_AGES = [33, 35, 40, 45, 50, 55, 60, 65, 75, 85]


@pytest.mark.persona_regression
@pytest.mark.persona_fast
def test_high_earner_late_saver_regression() -> None:
    fixture = load_persona_fixture(PERSONA_NAME)
    baseline = load_persona_baseline(PERSONA_NAME)
    assert baseline, (
        f"Missing baseline for {PERSONA_NAME}. Regenerate via "
        "`python -m scripts.regenerate_persona_baseline high_earner_late_saver`."
    )

    plan = build_plan_from_fixture(fixture)
    result = run_simulation(plan)

    assert result.metadata.failure_year is None, (
        f"High-Earner Late Saver persona should remain viable through "
        f"life_expectancy; got failure_year={result.metadata.failure_year}"
    )

    by_age = {snap.age: snap for snap in result.yearly_snapshots}
    for age in CHECKPOINT_AGES:
        # Persona starts at age 50; pre-start checkpoints have no snapshot
        # and the regen script skips them in the baseline. Skip in lockstep.
        if age not in by_age:
            assert str(age) not in baseline, (
                f"Baseline captured age {age} but simulation did not emit "
                f"a snapshot — fixture / CHECKPOINT_AGES drift"
            )
            continue
        assert str(age) in baseline, f"Baseline missing checkpoint age {age}"
        assert_snapshot_near(
            by_age[age],
            baseline[str(age)],
            tolerance_pct=0.5,
            context=f"age {age}",
            persona=PERSONA_NAME,
        )

    # --- Spot assertions (engine invariants, not baseline-derived) ---

    # Texas has no state income tax — engine should emit a hard 0.
    snap64 = by_age[64]
    assert abs(snap64.state_tax) < 0.01, (
        f"age 64 TX resident should pay zero state income tax; "
        f"got ${snap64.state_tax:,.2f}"
    )

    # SECURE Act 2.0: birth_year 1976 → RMDs start at age 75. The engine
    # surfaces RMDs as a NamedAmount income source named "RMD" inside the
    # snapshot's cash_flow.income_sources (see simulator.py ~line 576).
    snap75 = by_age[75]
    assert snap75.cash_flow is not None, "age 75 snapshot missing cash_flow"
    rmd_total = sum(
        s.amount for s in snap75.cash_flow.income_sources if s.name == "RMD"
    )
    assert rmd_total > 0, (
        f"age 75 should have a traditional-401k RMD > $0 (SECURE Act 2.0 "
        f"start age for birth_year 1976); got ${rmd_total:,.2f}"
    )

    # Drawdown sustainability at age 85 — the plan should still be solvent.
    snap85 = by_age[85]
    assert snap85.net_worth > 0, (
        f"age 85 net_worth should remain positive (drawdown sustainability); "
        f"got ${snap85.net_worth:,.2f}"
    )
