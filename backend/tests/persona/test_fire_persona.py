"""E2E regression test for the FIRE persona.

Verifies the ``fire_persona`` fixture's full-lifecycle simulation matches the
committed baseline at 10 checkpoint ages, plus engine-invariant spot checks
that are independent of the baseline (state-tax jurisdiction change,
pro-rated salary semantics, and FIRE drawdown source gating).
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

PERSONA_NAME = "fire_persona"
CHECKPOINT_AGES = [33, 35, 40, 45, 50, 55, 60, 65, 75, 85]


@pytest.mark.persona_regression
@pytest.mark.persona_fast
def test_fire_persona_regression() -> None:
    fixture = load_persona_fixture(PERSONA_NAME)
    baseline = load_persona_baseline(PERSONA_NAME)
    assert baseline, (
        f"Missing baseline for {PERSONA_NAME}. Regenerate via "
        "`python -m scripts.regenerate_persona_baseline fire_persona`."
    )

    plan = build_plan_from_fixture(fixture)
    result = run_simulation(plan)

    assert result.metadata.failure_year is None, (
        f"FIRE persona should remain viable; got failure_year="
        f"{result.metadata.failure_year}"
    )

    by_age = {snap.age: snap for snap in result.yearly_snapshots}
    for age in CHECKPOINT_AGES:
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

    # Residency: CA before the age-35 move milestone, NV after.
    assert by_age[34].state_tax > 10_000, (
        f"age 34 (pre-move, CA) should have meaningful state tax; "
        f"got ${by_age[34].state_tax:,.2f}"
    )
    assert by_age[36].state_tax < 100, (
        f"age 36 (post-move, NV) should have near-zero state tax; "
        f"got ${by_age[36].state_tax:,.2f}"
    )

    # Pro-rated salary: W2 ends at the retire milestone (age 45) and the
    # fixture has birth_month=6 → 5 full months of work (Jan–May) that year.
    # Salary starts at $180k in 2026 and grows 3%/yr; age 45 is year 2039
    # (13 years of growth). Loose ±2% tolerance because the chaining with
    # growth introduces small accumulated rounding, but a regression to
    # full-year semantics would be off by ~2.4× — easily caught.
    expected_age45_salary = 180_000.0 * (1.03 ** 13) * (5 / 12)
    actual_age45 = by_age[45].gross_income
    assert abs(actual_age45 - expected_age45_salary) <= expected_age45_salary * 0.02, (
        f"age 45 gross_income expected ≈ ${expected_age45_salary:,.2f} "
        f"(5/12 × $180k × 1.03^13); got ${actual_age45:,.2f} "
        f"— possible regression of the pro-rated-salary fix"
    )

    # First full retirement year: no salary, drawdowns must cover expenses.
    snap46 = by_age[46]
    assert snap46.cash_flow is not None
    assert all(
        source.name != "W2 Salary"
        for source in snap46.cash_flow.income_sources
    ), "age 46 should have no W2 salary income"
    # gross_income may still contain taxable gains created by brokerage
    # drawdowns; those are income for tax purposes, not continued salary.
    drawdowns = snap46.cash_flow.drawdowns
    total_brokerage = sum(
        d.amount for d in drawdowns
        if d.account_id in plan.accounts
        and plan.accounts[d.account_id].account_type == "taxable_brokerage"
    )
    total_401k = sum(
        d.amount for d in drawdowns
        if d.account_id in plan.accounts
        and plan.accounts[d.account_id].account_type == "traditional_401k"
    )
    assert total_brokerage > 0, (
        f"age 46 FIRE funding should come from taxable brokerage; "
        f"got ${total_brokerage:,.2f}"
    )
    assert total_401k == 0, (
        f"age 46 (pre-59.5) must not draw from 401k — avoids early-withdrawal "
        f"penalty; got ${total_401k:,.2f}"
    )
