"""E2E regression test for the Inherited IRA persona.

Covers the SECURE-Act 10-year rule for a non-EDB beneficiary: a $500k
inherited traditional IRA inherited at the start of 2026 must be fully
distributed by end of 2036 (age 65), including the deadline year's growth.
Source: https://www.irs.gov/publications/p590b (10-year rule).
Independent arithmetic is also tested in tests/test_inherited_deadline.py.

Spot assertions verify the engine invariants independently of the
baseline: federal tax > 0 during the 10-year window (W2 active),
inherited IRA balance alive through the window, substantially drained
at the deadline, and retirement drawdowns > 0 after the W2 stops.
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

PERSONA_NAME = "inherited_ira"
INHERITED_IRA_ACCOUNT_ID = "00000000-0000-4000-8000-000000023004"
# Sim starts at age 55 (birth_year=1971, start_year=2026) and ends at
# age 87 (life_expectancy=88). Checkpoints skip the pre-sim ages used by
# the shared baseline regenerator script.
CHECKPOINT_AGES = [55, 60, 65, 75, 85]


@pytest.mark.persona_regression
def test_inherited_ira_persona_regression() -> None:
    fixture = load_persona_fixture(PERSONA_NAME)
    baseline = load_persona_baseline(PERSONA_NAME)
    assert baseline, (
        f"Missing baseline for {PERSONA_NAME}. Regenerate via "
        "`python -m scripts.regenerate_persona_baseline inherited_ira`."
    )

    plan = build_plan_from_fixture(fixture)
    result = run_simulation(plan)

    # NOTE: this persona's core stress is the 10-year SECURE-Act rule and
    # the high-tax CA drag through the 10-year window — not plan
    # longevity. With the task-specified $80k expenses inflating to
    # ~$200k by the late 80s on ~$910k liquid at retirement, the plan
    # can legitimately run out before life expectancy, and that failure
    # is not what we're testing here. Skip the `failure_year` sanity
    # check used by luxuriously-funded personas like FIRE.

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

    # Ages 55–64 span the 10-year non-EDB window. W2 salary is active
    # through age 64 (retire milestone at 65), so federal tax must be
    # positive every year. The inherited IRA must stay alive because
    # non-EDB has no annual RMD in years 1–9 — only the year-10 force-out.
    for age in range(55, 65):
        snap = by_age[age]
        assert snap.federal_tax > 0, (
            f"age {age}: W2 salary active, federal_tax must be > 0; "
            f"got ${snap.federal_tax:,.2f}"
        )
        ira_balance = snap.accounts.get(INHERITED_IRA_ACCOUNT_ID, 0.0)
        assert ira_balance > 0, (
            f"age {age}: inherited IRA must be alive pre-deadline; "
            f"got ${ira_balance:,.2f}"
        )

    # First full retirement year (age 66): W2 has ended, expenses must be
    # covered by drawdowns from remaining accounts.
    snap66 = by_age[66]
    assert snap66.cash_flow is not None
    total_drawdown_66 = sum(d.amount for d in snap66.cash_flow.drawdowns)
    assert total_drawdown_66 > 0, (
        f"age 66 (post-retirement): drawdowns must cover expenses; "
        f"got ${total_drawdown_66:,.2f}"
    )

    # Age 65 is year 2036 — exactly 10 years after inheritance in 2026.
    # The deadline includes current-year growth, not just the prior December balance.
    snap65 = by_age[65]
    ira_balance_65 = snap65.accounts.get(INHERITED_IRA_ACCOUNT_ID, 0.0)
    assert ira_balance_65 == pytest.approx(0.0, abs=1.0), (
        f"age 65: 10-year SECURE-Act deadline must force full "
        f"distribution; got ${ira_balance_65:,.2f}"
    )
