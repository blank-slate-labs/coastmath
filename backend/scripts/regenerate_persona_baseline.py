"""Regenerate persona-regression baseline files from their fixtures.

Usage::

    python -m scripts.regenerate_persona_baseline <persona_name> [--diff]
    python -m scripts.regenerate_persona_baseline --all [--diff]

Baselines live at ``tests/persona/baselines/<name>.baseline.json`` and are
committed as the expected-output contract for ``@pytest.mark.persona_regression``
tests. The baseline captures a fixed set of checkpoint ages; fields match
``tests.persona.harness.assert_snapshot_near`` (see ``_SNAPSHOT_FIELD_MAP``).

``--diff`` previews the per-checkpoint / per-field delta against the existing
baseline with colorized percent deltas and does NOT write the file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from coastmath.engine.simulator import run_simulation
from coastmath.schemas.simulation import SimulationResult, YearSnapshot
from tests.persona.harness import build_plan_from_fixture

CHECKPOINT_AGES: list[int] = [33, 35, 40, 45, 50, 55, 60, 65, 75, 85]

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES_DIR = _BACKEND_ROOT / "tests" / "persona" / "fixtures"
_BASELINES_DIR = _BACKEND_ROOT / "tests" / "persona" / "baselines"

# Fields on Pydantic YearSnapshot → baseline JSON keys. Kept in sync with
# tests/persona/harness.py::_SNAPSHOT_FIELD_MAP so regenerated baselines match
# what assert_snapshot_near compares against.
_SCALAR_FIELD_MAP: dict[str, str] = {
    "federal_tax": "total_federal_tax",
    "state_tax": "total_state_tax",
    "fica_tax": "total_payroll_tax",
}

# ANSI colors for --diff percent-delta rendering.
_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_GREEN = "\x1b[32m"
_RESET = "\x1b[0m"


def _total_drawdown(snap: YearSnapshot) -> float:
    if snap.cash_flow is None:
        return 0.0
    return sum(d.amount for d in snap.cash_flow.drawdowns)


def _round_balances(balances: dict[str, float]) -> dict[str, float]:
    return {aid: round(float(bal), 2) for aid, bal in sorted(balances.items())}


def _snapshot_to_checkpoint(snap: YearSnapshot) -> dict:
    entry: dict = {
        "year": snap.year,
        "net_worth": round(float(snap.net_worth), 2),
    }
    for attr, key in _SCALAR_FIELD_MAP.items():
        entry[key] = round(float(getattr(snap, attr)), 2)
    entry["total_drawdown"] = round(_total_drawdown(snap), 2)
    entry["account_balances"] = _round_balances(snap.accounts)
    return entry


def generate_baseline(name: str) -> dict[str, dict]:
    """Run the simulation for a persona fixture and return its baseline dict."""
    fixture_path = _FIXTURES_DIR / f"{name}.json"
    if not fixture_path.exists():
        raise FileNotFoundError(f"No fixture at {fixture_path}")

    raw = json.loads(fixture_path.read_text())
    plan = build_plan_from_fixture(raw)
    result: SimulationResult = run_simulation(plan)

    by_age: dict[int, YearSnapshot] = {s.age: s for s in result.yearly_snapshots}
    max_age = max(by_age) if by_age else -1

    baseline: dict[str, dict] = {}
    for age in CHECKPOINT_AGES:
        snap = by_age.get(age)
        if snap is None:
            print(
                f"  ! persona '{name}': skipping age {age} "
                f"(beyond final snapshot age {max_age})",
                file=sys.stderr,
            )
            continue
        baseline[str(age)] = _snapshot_to_checkpoint(snap)
    return baseline


def load_existing_baseline(name: str) -> dict[str, dict]:
    path = _BASELINES_DIR / f"{name}.baseline.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def write_baseline(name: str, baseline: dict[str, dict]) -> Path:
    _BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    path = _BASELINES_DIR / f"{name}.baseline.json"
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    return path


def _colorize_pct(pct: float) -> str:
    abs_pct = abs(pct)
    if abs_pct > 5.0:
        color = _RED
    elif abs_pct >= 1.0:
        color = _YELLOW
    else:
        color = _GREEN
    return f"{color}{pct:+.2f}%{_RESET}"


def _format_delta(old: float | None, new: float | None) -> str:
    if old is None:
        return f"(new) {new!r}"
    if new is None:
        return f"(removed) was {old!r}"
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        if old == 0:
            pct_str = "n/a" if new == 0 else f"{_RED}∞{_RESET}"
        else:
            pct = (new - old) / old * 100.0
            pct_str = _colorize_pct(pct)
        return f"{old:,.2f} → {new:,.2f}  ({pct_str})"
    return f"{old!r} → {new!r}"


def _diff_scalars(old_entry: dict, new_entry: dict) -> list[str]:
    lines: list[str] = []
    keys = ["year", "net_worth", *_SCALAR_FIELD_MAP.values(), "total_drawdown"]
    for key in keys:
        old_v = old_entry.get(key) if old_entry else None
        new_v = new_entry.get(key) if new_entry else None
        if old_v == new_v:
            continue
        lines.append(f"    {key:<22} {_format_delta(old_v, new_v)}")
    return lines


def _diff_account_balances(old_entry: dict, new_entry: dict) -> list[str]:
    old_bal = (old_entry or {}).get("account_balances", {}) or {}
    new_bal = (new_entry or {}).get("account_balances", {}) or {}
    all_keys = sorted(set(old_bal) | set(new_bal))
    lines: list[str] = []
    for key in all_keys:
        old_v = old_bal.get(key)
        new_v = new_bal.get(key)
        if old_v == new_v:
            continue
        lines.append(f"    account[{key}] {_format_delta(old_v, new_v)}")
    return lines


def print_diff(name: str, old: dict[str, dict], new: dict[str, dict]) -> None:
    print(f"\n=== Persona: {name} ===")
    ages = sorted(set(old) | set(new), key=int)
    any_changes = False
    for age in ages:
        old_entry = old.get(age, {})
        new_entry = new.get(age, {})
        if old_entry == new_entry:
            continue
        any_changes = True
        year = new_entry.get("year") or old_entry.get("year") or "?"
        print(f"  age {age} (year {year}):")
        if not old_entry:
            print("    (new checkpoint)")
        elif not new_entry:
            print("    (removed checkpoint)")
        for line in _diff_scalars(old_entry, new_entry):
            print(line)
        for line in _diff_account_balances(old_entry, new_entry):
            print(line)
    if not any_changes:
        print("  (no changes)")


def _fixture_names() -> list[str]:
    if not _FIXTURES_DIR.exists():
        return []
    return sorted(p.stem for p in _FIXTURES_DIR.glob("*.json"))


def _regenerate_one(name: str, diff_only: bool) -> None:
    new_baseline = generate_baseline(name)
    if diff_only:
        old_baseline = load_existing_baseline(name)
        print_diff(name, old_baseline, new_baseline)
        return
    path = write_baseline(name, new_baseline)
    print(
        f"Wrote {len(new_baseline)} checkpoints for persona {name} "
        f"({path.relative_to(_BACKEND_ROOT)}). "
        "Use `git diff` to review changes, "
        "`pytest tests/persona/ -m persona_regression` to verify."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regenerate_persona_baseline",
        description=(
            "Regenerate persona-regression baselines from their fixtures. "
            "Baselines are committed and consumed by @persona_regression tests."
        ),
    )
    parser.add_argument(
        "persona_name",
        nargs="?",
        help="Persona fixture stem (e.g. 'fire_persona'). Omit when using --all.",
    )
    parser.add_argument(
        "--all",
        dest="all_fixtures",
        action="store_true",
        help="Regenerate baselines for every fixture in tests/persona/fixtures/.",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Preview per-checkpoint deltas with colorized percent changes; skip write.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.all_fixtures and args.persona_name is not None:
        parser.error("persona_name is not allowed with --all")
    if not args.all_fixtures and args.persona_name is None:
        parser.error("persona_name is required (or pass --all)")

    if args.all_fixtures:
        names = _fixture_names()
        if not names:
            print(f"No fixtures found in {_FIXTURES_DIR}", file=sys.stderr)
            return 1
    else:
        names = [args.persona_name]

    for name in names:
        _regenerate_one(name, diff_only=args.diff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
