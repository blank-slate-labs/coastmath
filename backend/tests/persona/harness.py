"""Persona-driven E2E regression test harness.

Shared helpers for loading persona fixtures, loading expected baselines, building
engine ``PlanData`` from a fixture dict, and asserting simulation output against
a baseline with percentage-based tolerance.

Tests that consume these helpers mark themselves with ``@pytest.mark.persona_regression``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coastmath.engine.types import (
    CharityData,
    EstateSettingsData,
    PlanData,
    ResidencyPeriodData,
    SEPPSettingsData,
    SimState,
    YearSnapshot,
)
from tests.engine_support import fixture_to_plan_data

_PERSONA_DIR = Path(__file__).parent
_FIXTURES_DIR = _PERSONA_DIR / "fixtures"
_BASELINES_DIR = _PERSONA_DIR / "baselines"


# ---------------------------------------------------------------------------
# Fixture / baseline loaders
# ---------------------------------------------------------------------------

def load_persona_fixture(name: str) -> dict:
    """Load a persona input-plan fixture by name (without extension)."""
    path = _FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text())


def load_persona_baseline(name: str) -> dict:
    """Load an expected-output baseline by persona name.

    Returns an empty dict if the baseline file doesn't exist yet so that
    first-run regeneration flows (see ``scripts/regenerate_persona_baseline.py``)
    don't crash.
    """
    path = _BASELINES_DIR / f"{name}.baseline.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Plan builder — extends the standard helper with the newer plan fields
# ---------------------------------------------------------------------------

def build_plan_from_fixture(raw: dict, *, legacy_replay: bool = False) -> PlanData:
    """Build a ``PlanData`` dataclass from a persona fixture dict.

    Delegates the common work to ``tests.engine_support.fixture_to_plan_data``
    and then layers on the fields that helper doesn't know about:
    ``birth_month``, per-account ``cost_basis``,
    ``residency_periods`` and plan-level ``state_code``.

    Ownership and income classification are explicit data, never inferred from
    display names. ``legacy_replay=True`` restores the earlier loader's
    name-based Social Security classification and dropped ownership metadata
    solely for archival diagnostics; it does not restore older engine rules.
    """
    plan = fixture_to_plan_data(raw, guess_social_security=True)

    birth_month = raw.get("birth_month")
    if birth_month is not None:
        plan.birth_month = birth_month

    for acct_raw in raw.get("accounts", []):
        account = plan.accounts.get(acct_raw["id"])
        if account is None:
            continue
        if not legacy_replay:
            account.owner = acct_raw.get("owner") or "self"
            account.name = acct_raw.get("name", "")
        cost_basis = acct_raw.get("cost_basis")
        if cost_basis is not None:
            account.cost_basis = cost_basis
        inherited_year = acct_raw.get("inherited_year")
        if inherited_year is not None:
            account.inherited_year = inherited_year
        beneficiary_type = acct_raw.get("beneficiary_type")
        if beneficiary_type is not None:
            account.beneficiary_type = beneficiary_type

    plan.residency_periods = [
        ResidencyPeriodData(
            state_code=rp["state_code"],
            start_milestone_id=rp.get("start_milestone_id"),
            end_milestone_id=rp.get("end_milestone_id"),
            start_year=rp.get("start_year"),
            end_year=rp.get("end_year"),
            rank=rp.get("rank", 0),
        )
        for rp in raw.get("residency_periods", [])
    ]

    state_code = raw.get("state_code")
    if state_code is not None:
        plan.state_code = state_code

    raw_estate = raw.get("estate_settings")
    if raw_estate is not None:
        plan.estate_settings = EstateSettingsData(
            step_up_basis_on_death=raw_estate.get("step_up_basis_on_death", True),
            filing_status_after_death=raw_estate.get("filing_status_after_death", "single"),
            federal_estate_exemption=raw_estate.get("federal_estate_exemption", 13_990_000.0),
            state_estate_tax_enabled=raw_estate.get("state_estate_tax_enabled", False),
            state_estate_exemption=raw_estate.get("state_estate_exemption", 0.0),
            state_estate_tax_rate=raw_estate.get("state_estate_tax_rate", 0.0),
        )

    plan.charity_entities = [
        CharityData(
            id=ce["id"],
            name=ce["name"],
            entity_type=ce["entity_type"],
            annual_amount=ce["annual_amount"],
            start_milestone_id=ce.get("start_milestone_id"),
            end_milestone_id=ce.get("end_milestone_id"),
        )
        for ce in raw.get("charity_entities", [])
    ]

    income_by_id = {inc.id: inc for inc in plan.income_streams}
    for inc_raw in raw.get("income_streams", []):
        inc = income_by_id.get(inc_raw["id"])
        if inc is None:
            continue
        if not legacy_replay:
            inc.owner = inc_raw.get("owner") or "self"
            inc.is_social_security = bool(inc_raw.get("is_social_security", False))
            inc.is_earned_income = bool(inc_raw.get("is_earned_income", True))
            inc.claiming_age = inc_raw.get("claiming_age")
        if inc_raw.get("is_self_employed") is not None:
            inc.is_self_employed = bool(inc_raw["is_self_employed"])

    if not legacy_replay:
        expenses_by_id = {expense.id: expense for expense in plan.expenses}
        for exp_raw in raw.get("expenses", []):
            expenses_by_id[exp_raw["id"]].category = exp_raw.get("category", "essential")

    raw_sepp = raw.get("sepp_settings")
    if raw_sepp is not None and raw_sepp.get("enabled"):
        plan.sepp_settings = SEPPSettingsData(
            enabled=True,
            source_account_id=str(raw_sepp["source_account_id"]),
            method=raw_sepp.get("method", "fixed_amortization"),
            start_age=float(raw_sepp["start_age"]),
            interest_rate=float(raw_sepp.get("interest_rate", 0.05)),
        )

    return plan


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

# Map baseline-JSON keys → YearSnapshot attribute names.
_SNAPSHOT_FIELD_MAP = {
    "net_worth": "net_worth",
    "total_federal_tax": "federal_tax",
    "total_state_tax": "state_tax",
    "total_payroll_tax": "fica_tax",
}

# Likely source file(s) for each comparable field — emitted as hints in
# failure diagnostics so a developer can jump straight to the probable cause.
_CONTEXT_HINTS: dict[str, tuple[str, ...]] = {
    "net_worth": ("backend/coastmath/engine/simulator.py",),
    "federal_tax": ("backend/coastmath/engine/tax_engine.py",),
    "niit_tax": ("backend/coastmath/engine/tax_engine.py",),
    "amt_tax": ("backend/coastmath/engine/tax_engine.py",),
    "state_tax": ("backend/coastmath/engine/tax_engine.py",),
    "capital_gains_tax": (
        "backend/coastmath/engine/tax_engine.py",
        "backend/coastmath/engine/cost_basis.py",
    ),
    "fica_tax": ("backend/coastmath/engine/tax_engine.py",),
    "total_drawdown": ("backend/coastmath/engine/waterfall.py",),
    "total_income": ("backend/coastmath/engine/waterfall.py",),
    "total_expenses": ("backend/coastmath/engine/waterfall.py",),
    "rmd_amount": ("backend/coastmath/engine/rmd.py",),
    "early_withdrawal_penalty": (
        "backend/coastmath/engine/sepp.py",
        "backend/coastmath/engine/tax_engine.py",
    ),
}

# Absolute tolerance used when the expected value is zero — avoids division
# by zero and handles no-state-tax scenarios (NV, TX, FL, WA) cleanly.
_ZERO_ABS_TOLERANCE = 1.0


def _within_tolerance(actual: float, expected: float, rel: float) -> bool:
    if expected == 0.0:
        return abs(actual) <= _ZERO_ABS_TOLERANCE
    return abs(actual - expected) <= abs(expected) * rel


def _fmt_money(v: float) -> str:
    return f"${v:,.2f}"


def _fmt_signed_money(v: float) -> str:
    sign = "+" if v > 0 else ("-" if v < 0 else " ")
    return f"{sign}{abs(v):,.2f}"


def _pct_delta(actual: float, expected: float) -> str:
    if expected == 0.0:
        return "n/a" if actual == 0.0 else "∞"
    return f"{(actual - expected) / expected * 100.0:+.2f}%"


def _total_drawdown(snap: YearSnapshot) -> float:
    """Sum of named drawdowns from the snapshot's cash-flow breakdown."""
    if snap.cash_flow is None:
        return 0.0
    return sum(d.amount for d in snap.cash_flow.drawdowns)


def assert_snapshot_near(
    actual: YearSnapshot,
    expected: dict,
    tolerance_pct: float = 0.5,
    context: str = "",
    persona: str | None = None,
) -> None:
    """Compare scalar fields on a ``YearSnapshot`` against an expected dict.

    Checked fields (if present in ``expected``): ``net_worth``,
    ``total_federal_tax``, ``total_state_tax``, ``total_payroll_tax``,
    ``total_drawdown``. Missing keys are skipped so callers can assert on a
    subset per-checkpoint.

    Tolerance is relative (``tolerance_pct`` percent of the expected value).
    When ``expected`` is exactly zero, falls back to an absolute $1 tolerance
    so no-state-tax jurisdictions don't spuriously fail.

    On mismatch, emits a rich diagnostic table with a row for every compared
    field (failing rows marked ``← FAIL``), followed by ``Suggested next
    steps:`` pointing to likely source files for the failing fields.
    """
    rel = tolerance_pct / 100.0
    rows: list[tuple[str, float, float, bool]] = []

    for expected_key, attr_name in _SNAPSHOT_FIELD_MAP.items():
        if expected_key not in expected:
            continue
        expected_v = float(expected[expected_key])
        actual_v = float(getattr(actual, attr_name))
        failed = not _within_tolerance(actual_v, expected_v, rel)
        rows.append((attr_name, expected_v, actual_v, failed))

    if "total_drawdown" in expected:
        expected_dd = float(expected["total_drawdown"])
        actual_dd = _total_drawdown(actual)
        failed = not _within_tolerance(actual_dd, expected_dd, rel)
        rows.append(("total_drawdown", expected_dd, actual_dd, failed))

    if not any(failed for _, _, _, failed in rows):
        return

    if context and persona:
        header = f"Assertion failed at {context} (persona: {persona})"
    elif context:
        header = f"Assertion failed at {context}"
    elif persona:
        header = f"Assertion failed (persona: {persona})"
    else:
        header = "Assertion failed"

    name_w = max(len("field"), *(len(name) for name, _, _, _ in rows))
    lines = [
        header,
        f"  year={actual.year} age={actual.age} tolerance={tolerance_pct:g}%",
        f"  {'':<{name_w}}  {'EXPECTED':>16}  {'ACTUAL':>16}  {'Δ':>14}  {'Δ%':>8}",
    ]
    for name, exp, act, failed in rows:
        marker = "  ← FAIL" if failed else ""
        lines.append(
            f"  {name:<{name_w}}  {_fmt_money(exp):>16}  {_fmt_money(act):>16}  "
            f"{_fmt_signed_money(act - exp):>14}  {_pct_delta(act, exp):>8}{marker}"
        )

    failing_fields = [name for name, _, _, failed in rows if failed]
    hint_lines: list[str] = []
    for name in failing_fields:
        sources = _CONTEXT_HINTS.get(name)
        if not sources:
            continue
        if len(sources) == 1:
            hint_lines.append(f"  - {name} mismatch — check `git log -p {sources[0]}`")
        else:
            joined = " ".join(sources)
            hint_lines.append(f"  - {name} mismatch — check `git log -p {joined}`")

    persona_arg = persona if persona else "<persona_name>"
    hint_lines.append(
        f"  - If the change is intentional: "
        f"`python -m scripts.regenerate_persona_baseline {persona_arg} --diff` "
        f"and review, then `--all`"
    )

    lines.append("")
    lines.append("Suggested next steps:")
    lines.extend(hint_lines)

    pytest.fail("\n".join(lines), pytrace=False)


def assert_account_balances_near(
    actual_state: SimState,
    year: int,
    expected_balances: dict[str, float],
    tolerance_pct: float = 0.5,
) -> None:
    """Compare per-account balances on a ``SimState`` against expected values.

    Uses the same relative/zero-absolute tolerance rules as
    :func:`assert_snapshot_near`. Missing accounts on the state are treated as
    balance ``0.0`` so the diagnostic surfaces the absent account explicitly
    rather than raising a KeyError.
    """
    rel = tolerance_pct / 100.0
    mismatches: list[tuple[str, float, float]] = []

    for account_id, expected_v in expected_balances.items():
        account = actual_state.accounts.get(account_id)
        actual_v = account.balance if account is not None else 0.0
        if not _within_tolerance(actual_v, float(expected_v), rel):
            mismatches.append((account_id, float(expected_v), actual_v))

    if not mismatches:
        return

    lines = [
        f"Persona regression mismatch — account balances at year {year}",
        f"  tolerance={tolerance_pct:g}%",
        f"  {'account_id':<40} {'expected':>16} {'actual':>16} {'delta':>16}    pct",
    ]
    for account_id, exp, act in mismatches:
        lines.append(
            f"  {account_id:<40} {_fmt_money(exp):>16} {_fmt_money(act):>16} "
            f"{_fmt_money(act - exp):>16}   {_pct_delta(act, exp)}"
        )
    pytest.fail("\n".join(lines))
