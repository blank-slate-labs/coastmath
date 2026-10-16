"""Cross-cut drawdown & account-balance invariants.

Engine-level invariants that must hold for every persona regardless of
baseline scalars:

1. Account balances are never negative in any year.
2. Net-worth decomposition:
   ``sum(accounts) == net_worth + liabilities_balance - real_assets_value``.
3. Pure-drawdown YoY identity: in retirement years where the only cash
   inflow is waterfall drawdowns (no W2, no SS, no RMD, no SEPP), the
   drawdown total equals the decrease in total liquid balances plus the
   year's investment growth — within 1% of prior-year liquid total.
4. Early-withdrawal penalty count == 0 for every persona (FIRE retires
   from taxable brokerage, HighEarner/InheritedIRA/HNW retire at 65 past
   the 59.5 threshold, SEPP uses a 72(t) exemption).
5. RMD compliance: once ``age >= metadata.rmd_start_age`` and the plan
   holds a traditional account, the snapshot's cash-flow stream must
   include a positive ``"RMD"`` income source.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import YearSnapshot
from tests.persona.harness import build_plan_from_fixture, load_persona_fixture

# ---------------------------------------------------------------------------
# Persona parametrization
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PersonaSpec:
    name: str
    retire_age: int
    # Age window where we search for pure-drawdown years (inclusive).
    pure_drawdown_window: tuple[int, int] | None


PERSONAS: list[PersonaSpec] = [
    # FIRE: retire at 45 from brokerage; pre-RMD window closes at 74.
    PersonaSpec("fire_persona", retire_age=45, pure_drawdown_window=(46, 74)),
    # HighEarner: retire at 65, SS at 67 → single pure-drawdown year (66).
    PersonaSpec("high_earner_late_saver", retire_age=65, pure_drawdown_window=(66, 66)),
    # SEPP: retire at 50 but SEPP runs through ~age 59. SS at 67.
    # Pure-drawdown window is post-SEPP, pre-SS (roughly 62-66).
    PersonaSpec("self_employed_sepp", retire_age=50, pure_drawdown_window=(62, 66)),
    # InheritedIRA: retire at 65; age-65 is the 10-year force-out year.
    # Use 66-74 as pure-drawdown window (pre-owner-RMD at 75).
    PersonaSpec("inherited_ira", retire_age=65, pure_drawdown_window=(66, 74)),
    # HNW: retire at 65, QCD begins at 73, RMD at 75.
    PersonaSpec("hnw_estate", retire_age=65, pure_drawdown_window=(66, 72)),
]

PARAM_IDS = [p.name for p in PERSONAS]


_TRADITIONAL_TYPES = frozenset({"traditional_ira", "traditional_401k"})


@dataclass
class PersonaRun:
    snapshots: list[YearSnapshot]
    metadata: object
    traditional_account_ids: set[str]


@pytest.fixture(scope="module")
def persona_runs() -> dict[str, PersonaRun]:
    """Run every persona once and cache snapshots + metadata + account-type map."""
    out: dict[str, PersonaRun] = {}
    for spec in PERSONAS:
        raw = load_persona_fixture(spec.name)
        plan = build_plan_from_fixture(raw)
        result = run_simulation(plan)
        trad_ids = {
            acct["id"]
            for acct in raw.get("accounts", [])
            if acct.get("account_type") in _TRADITIONAL_TYPES
        }
        out[spec.name] = PersonaRun(
            snapshots=list(result.yearly_snapshots),
            metadata=result.metadata,
            traditional_account_ids=trad_ids,
        )
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INCOME_DISQUALIFIERS = frozenset({"RMD", "SEPP 72(t)", "Social Security"})


def _is_pure_drawdown_year(snap: YearSnapshot) -> bool:
    """True if this year is funded only by waterfall drawdowns.

    A year qualifies when:
    - A cash-flow breakdown was emitted.
    - No earned income (``fica_tax == 0``).
    - No RMD / SEPP / SS income sources.
    - At least one dollar of waterfall drawdown fired.
    """
    if snap.cash_flow is None:
        return False
    if snap.fica_tax > 1.0:
        return False
    # Disqualifying income sources are sometimes emitted with amount == 0
    # (the engine keeps the "RMD" label after the balance is force-distributed
    # in a prior year). Only bail when one of these streams is actually
    # contributing cash.
    if any(
        s.name in _INCOME_DISQUALIFIERS and s.amount > 1.0
        for s in snap.cash_flow.income_sources
    ):
        return False
    drawdown_total = sum(d.amount for d in snap.cash_flow.drawdowns)
    return drawdown_total > 0


def _total_drawdown(snap: YearSnapshot) -> float:
    if snap.cash_flow is None:
        return 0.0
    return sum(d.amount for d in snap.cash_flow.drawdowns)


def _penalty_residual(snap: YearSnapshot) -> float:
    """Upper bound on early-withdrawal penalty leaking into ``snap.taxes``.

    ``snap.taxes`` ≈ federal + state + capital_gains + fica + NIIT +
    early_withdrawal_penalty. NIIT on modest post-retirement investment
    income is at most a few hundred dollars, so a residual above the
    ``PENALTY_RESIDUAL_THRESHOLD`` implies the 10% penalty fired.
    Matches the heuristic in ``test_self_employed_sepp.py``.
    """
    return snap.taxes - (
        snap.federal_tax + snap.state_tax + snap.capital_gains_tax + snap.fica_tax
    )


PENALTY_RESIDUAL_THRESHOLD = 2_000.0


def _rmd_income(snap: YearSnapshot) -> float:
    if snap.cash_flow is None:
        return 0.0
    return sum(s.amount for s in snap.cash_flow.income_sources if s.name == "RMD")


# ---------------------------------------------------------------------------
# Invariant 1 — no negative account balances in any year
# ---------------------------------------------------------------------------

@pytest.mark.persona_regression
@pytest.mark.parametrize("spec", PERSONAS, ids=PARAM_IDS)
def test_account_balances_never_negative(
    spec: PersonaSpec,
    persona_runs: dict[str, PersonaRun],
) -> None:
    negative_hits: list[tuple[int, str, float]] = []
    for snap in persona_runs[spec.name].snapshots:
        for account_id, balance in snap.accounts.items():
            if balance < -0.01:
                negative_hits.append((snap.age, account_id, balance))
    assert not negative_hits, (
        f"{spec.name}: account balance went negative — "
        f"{negative_hits[:5]}{'…' if len(negative_hits) > 5 else ''}"
    )


# ---------------------------------------------------------------------------
# Invariant 2 — net-worth decomposition identity
# ---------------------------------------------------------------------------

@pytest.mark.persona_regression
@pytest.mark.parametrize("spec", PERSONAS, ids=PARAM_IDS)
def test_net_worth_decomposition(
    spec: PersonaSpec,
    persona_runs: dict[str, PersonaRun],
) -> None:
    mismatches: list[tuple[int, float, float]] = []
    for snap in persona_runs[spec.name].snapshots:
        liquid = sum(snap.accounts.values())
        expected = (snap.net_worth + snap.liabilities_balance + snap.tax_balance
                    + snap.unfunded_expenses - snap.real_assets_value)
        if abs(liquid - expected) > 1.0:
            mismatches.append((snap.age, liquid, expected))
    assert not mismatches, (
        f"{spec.name}: net-worth decomposition failed "
        f"(sum(accounts) != net_worth + loans + tax + unpaid bills - real_assets) — "
        f"first 3 mismatches: {mismatches[:3]}"
    )


# ---------------------------------------------------------------------------
# Invariant 3 — pure-drawdown YoY identity
# ---------------------------------------------------------------------------

@pytest.mark.persona_regression
@pytest.mark.parametrize("spec", PERSONAS, ids=PARAM_IDS)
def test_pure_drawdown_matches_liquid_decrease(
    spec: PersonaSpec,
    persona_runs: dict[str, PersonaRun],
) -> None:
    if spec.pure_drawdown_window is None:
        pytest.skip(f"{spec.name}: no pure-drawdown window defined")

    snaps = persona_runs[spec.name].snapshots
    by_age = {s.age: s for s in snaps}

    lo, hi = spec.pure_drawdown_window
    qualifying_ages = [
        age for age in range(lo, hi + 1)
        if age in by_age and _is_pure_drawdown_year(by_age[age])
    ]
    if not qualifying_ages:
        pytest.skip(
            f"{spec.name}: no pure-drawdown years in window [{lo},{hi}] "
            f"(income sources disqualified every candidate)"
        )

    mismatches: list[tuple[int, float, float, float, float]] = []
    for age in qualifying_ages:
        prev = by_age.get(age - 1)
        if prev is None:
            continue
        cur = by_age[age]
        prev_liquid = sum(prev.accounts.values())
        cur_liquid = sum(cur.accounts.values())
        decrease = prev_liquid - cur_liquid
        drawdown = _total_drawdown(cur)
        growth = cur.investment_growth
        expected = decrease + growth
        # Floor the tolerance at $100 so it doesn't collapse to near-zero
        # if a persona draws liquid balances very low in late retirement.
        tol = max(0.01 * abs(prev_liquid), 100.0)
        if abs(drawdown - expected) > tol:
            mismatches.append((age, drawdown, decrease, growth, expected))

    assert not mismatches, (
        f"{spec.name}: pure-drawdown YoY identity failed "
        f"(drawdown vs decrease+growth within 1%). "
        f"First mismatch age={mismatches[0][0]}: "
        f"drawdown=${mismatches[0][1]:,.2f}, "
        f"decrease=${mismatches[0][2]:,.2f}, "
        f"growth=${mismatches[0][3]:,.2f}, "
        f"expected=${mismatches[0][4]:,.2f}"
    )


# ---------------------------------------------------------------------------
# Invariant 4 — zero early-withdrawal penalty for every persona
# ---------------------------------------------------------------------------

@pytest.mark.persona_regression
@pytest.mark.parametrize("spec", PERSONAS, ids=PARAM_IDS)
def test_zero_early_withdrawal_penalty(
    spec: PersonaSpec,
    persona_runs: dict[str, PersonaRun],
) -> None:
    # The 10% early-withdrawal penalty only applies to traditional-account
    # withdrawals before age 59.5. Post-59.5, the ``taxes - components``
    # residual is dominated by NIIT on investment income (which legitimately
    # scales up in late retirement as RMDs force taxable distributions), so
    # restrict the invariant to ages < 60.
    penalty_years = [
        (snap.age, _penalty_residual(snap))
        for snap in persona_runs[spec.name].snapshots
        if snap.age < 60 and _penalty_residual(snap) > PENALTY_RESIDUAL_THRESHOLD
    ]
    assert not penalty_years, (
        f"{spec.name}: early-withdrawal penalty residual exceeded "
        f"${PENALTY_RESIDUAL_THRESHOLD:,.0f} threshold in "
        f"{len(penalty_years)} pre-59.5 year(s). First 3: {penalty_years[:3]}. "
        f"This persona should never incur the 10% penalty — design bug "
        f"in drawdown source selection or SEPP exemption."
    )


# ---------------------------------------------------------------------------
# Invariant 5 — RMD compliance once past SECURE 2.0 start age
# ---------------------------------------------------------------------------

@pytest.mark.persona_regression
@pytest.mark.parametrize("spec", PERSONAS, ids=PARAM_IDS)
def test_rmd_compliance_post_start_age(
    spec: PersonaSpec,
    persona_runs: dict[str, PersonaRun],
) -> None:
    run = persona_runs[spec.name]
    trad_ids = run.traditional_account_ids
    if not trad_ids:
        pytest.skip(f"{spec.name}: no traditional account → no owner RMD expected")

    # TODO: if SimMetadata ever drops rmd_start_age, this fallback keeps the
    # invariant live. Every persona in this suite is birth_year >= 1960, so
    # SECURE 2.0 pegs the start age at 75 across the board.
    rmd_start_age = getattr(run.metadata, "rmd_start_age", None) or 75

    rmd_years = [s for s in run.snapshots if s.age >= rmd_start_age]
    if not rmd_years:
        pytest.skip(
            f"{spec.name}: lifespan ends before RMD start age "
            f"({rmd_start_age}) — nothing to check"
        )

    # Only require an RMD when at least one traditional account still holds
    # funds at year-end. If every traditional account is drained (e.g. the
    # inherited IRA was force-distributed under the 10-year rule and the
    # traditional 401k was spent down by the waterfall), no owner RMD is
    # computable and the snapshot correctly reports zero.
    missing = [
        s.age for s in rmd_years
        if _rmd_income(s) <= 0.0
        and any(s.accounts.get(aid, 0.0) > 1.0 for aid in trad_ids)
    ]
    assert not missing, (
        f"{spec.name}: no RMD income recorded at ages {missing[:5]} "
        f"(rmd_start_age={rmd_start_age}) despite a live traditional "
        f"balance. Either the RMD step did not fire or the income-source "
        f"emission dropped the 'RMD' label."
    )
