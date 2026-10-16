"""E2E regression test for the Self-Employed SEPP persona.

Verifies the ``self_employed_sepp`` fixture's full-lifecycle simulation matches
the committed baseline at scheduled checkpoint ages, plus engine-invariant spot
checks (SE tax path exercised, SEPP 72(t) income emitted, no early-withdrawal
penalty leakage during ages 50-60 when SEPP is active).

The persona's lifespan (age 38 → 88) means ages 33 and 35 fall outside the
simulation window; the regen script skips those checkpoints and we only assert
baseline values for ages 40 through 85.

Note: the engine has no dedicated account_type for SEP-IRA — "SEP-IRA
contribution" in the task spec is absorbed into the brokerage priority after
the traditional IRA's $7k IRS cap is hit by the first priority.
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

PERSONA_NAME = "self_employed_sepp"
CHECKPOINT_AGES = [33, 35, 40, 45, 50, 55, 60, 65, 75, 85]
# Ages 33 and 35 are before the persona's start age (38) — the regen script
# skips them and the baseline file omits those keys.
SKIPPED_AGES = {33, 35}


def _penalty_residual(snap) -> float:
    """Upper bound on early-withdrawal penalty leaked into total taxes.

    ``snap.taxes`` includes ``actual_tax + early_withdrawal_penalty``; the four
    broken-out components sum to ``actual_tax`` minus NIIT. For this FL persona
    (no state tax, small post-retirement investment income), NIIT is at most
    a few hundred dollars, so a residual above ~$2k implies the 10% penalty
    leaked through — a $7k+ signal vs the $2k bound.
    """
    return snap.taxes - (
        snap.federal_tax + snap.state_tax + snap.capital_gains_tax + snap.fica_tax
    )


@pytest.mark.persona_regression
def test_self_employed_sepp_persona_regression() -> None:
    fixture = load_persona_fixture(PERSONA_NAME)
    baseline = load_persona_baseline(PERSONA_NAME)
    assert baseline, (
        f"Missing baseline for {PERSONA_NAME}. Regenerate via "
        "`python -m scripts.regenerate_persona_baseline self_employed_sepp`."
    )

    plan = build_plan_from_fixture(fixture)
    result = run_simulation(plan)

    assert result.metadata.failure_year is None, (
        f"Self-Employed SEPP persona should remain viable; got failure_year="
        f"{result.metadata.failure_year}"
    )

    by_age = {snap.age: snap for snap in result.yearly_snapshots}
    for age in CHECKPOINT_AGES:
        if age in SKIPPED_AGES:
            continue
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

    # Self-employment tax path: at age 40 (2028), SE income ≈ $220k × 1.03^2
    # ≈ $233k. SE FICA is double the employee share (SS ~12.4% up to wage
    # base + Medicare ~2.9% + additional Medicare 0.9% over $200k), so
    # fica_tax should be well above $20k. A W-2 regression would drop this
    # to roughly half.
    snap40 = by_age[40]
    assert snap40.fica_tax > 20_000, (
        f"age 40 fica_tax should reflect SE doubled FICA on ~$233k income; "
        f"got ${snap40.fica_tax:,.2f} — possible regression of the "
        f"is_self_employed SE-tax path in tax_engine.py"
    )

    # Corroboration: last working year (age 49) still exercises the SE path.
    snap49 = by_age[49]
    assert snap49.fica_tax > 0, (
        f"age 49 (last pre-retirement year) should still have SE FICA > 0; "
        f"got ${snap49.fica_tax:,.2f} — SE income silently stopped"
    )

    # SEPP 72(t) mandatory distribution — must show up as an income source
    # and NOT be charged the 10% early-withdrawal penalty during ages 50-59.
    # (SEPP distributions go through ``state.withdraw_from`` directly; the
    # waterfall SEPP exemption protects any *additional* IRA drawdown pulled
    # via execute_drawdown when brokerage runs low.)
    for age in range(50, 60):
        snap = by_age[age]
        sepp_income = sum(
            s.amount
            for s in snap.cash_flow.income_sources
            if s.name == "SEPP 72(t)"
        )
        assert sepp_income > 0, (
            f"age {age}: SEPP 72(t) should produce mandatory distribution income; "
            f"got $0 — SEPP not firing"
        )
        residual = _penalty_residual(snap)
        assert residual < 2_000.0, (
            f"age {age}: early-withdrawal penalty leaked into taxes — "
            f"residual (taxes − [federal+state+cg+fica]) = ${residual:,.2f}. "
            f"A 10% penalty on any IRA draw would be ~$7k+; SEPP exemption "
            f"must be preserved (see waterfall.py sepp_account_ids)."
        )

    # Age 60 — past the IRS 59.5 threshold. No penalty would apply even
    # without SEPP, but confirm the IRA is still being accessed (either
    # via lingering SEPP or open drawdown) and no residual leakage exists.
    snap60 = by_age[60]
    residual60 = _penalty_residual(snap60)
    assert residual60 < 2_000.0, (
        f"age 60: residual = ${residual60:,.2f} — should be ~0 past 59.5"
    )
