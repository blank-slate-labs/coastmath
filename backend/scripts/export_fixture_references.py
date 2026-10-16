"""Export complete deterministic results for the six canonical regression fixtures.

Run from backend: python -m scripts.export_fixture_references --output-dir /new/path
Uses the existing regression loader and engine, without a database or HTTP calls.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import platform
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from coastmath.engine.simulator import run_simulation
from coastmath.schemas.simulation import SimulationResult, YearSnapshot
from tests.persona.harness import build_plan_from_fixture

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
FIXTURES = {
    name: BACKEND_ROOT / "tests/persona/fixtures" / f"{name}.json"
    for name in (
        "fire_persona", "high_earner_late_saver", "self_employed_sepp",
        "inherited_ira", "hnw_estate",
    )
}
FIXTURES["standard_plan"] = BACKEND_ROOT / "tests/fixtures/standard_plan.json"

SEMANTICS = {
    "execution_path": "tests.persona.harness.build_plan_from_fixture -> coastmath.engine.simulator.run_simulation",
    "scope": "Local deterministic regression fixture execution; not a persisted-plan, HTTP, or production export.",
    "currency": "USD nominal; floating-point values are not rounded by this exporter.",
    "rates": "Resolved engine inputs use decimal rates (0.03 = 3%); raw fixtures are not API request bodies.",
    "timing": "Loader takes start_date's year, with first_year_fraction=1. Age milestones use primary birth year. Engine stops before primary birth_year + life_expectancy, even if spouse outlives primary.",
    "loader_defaults": "Explicit account/income ownership, names, expense categories and Social Security flags are preserved. Missing income ownership defaults to self and Social Security defaults to false; labels never establish these facts. Fixed inflation/market/bond curves become scalar assumptions. Inspect engine_input, not fixture labels, for executed behavior. Historical captures retain their original loader provenance.",
    "estate": "The loader leaves custom_federal_exemption_enabled=False; a fixture's federal_estate_exemption number alone does not enable an override.",
    "comparison": "Another engine's timing, tax rules, contribution semantics, unsupported features and extra assumptions must be reconciled before comparing results. No cross-engine parity is asserted.",
    "csv": "One column per YearSnapshot field; EVERY cell is a JSON value inside standard CSV quoting. Parse with csv then json.loads per cell to recover all nested details, nulls and precision. Metadata and opening snapshot are in the JSON bundle.",
}


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_hashes() -> dict[str, str]:
    """Fingerprint backend code/data and the exact existing fixture conversion path."""
    paths = set((BACKEND_ROOT / "app").rglob("*.py"))
    paths.update((BACKEND_ROOT / "coastmath").rglob("*.py"))
    paths.update(p for p in (BACKEND_ROOT / "coastmath" / "data").rglob("*") if p.is_file())
    paths.update(p for p in (BACKEND_ROOT / "data").rglob("*") if p.is_file())
    paths.update(FIXTURES.values())
    paths.update({
        BACKEND_ROOT / "tests/persona/harness.py",
        BACKEND_ROOT / "tests/test_simulation.py",
        Path(__file__).resolve(),
    })
    return {str(p.relative_to(REPO_ROOT)): sha256(p.read_bytes()) for p in sorted(paths)}


def git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), *args], text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def input_differences(raw: dict, resolved: dict) -> list[dict]:
    """Expose changed same-named fields; the full resolved input remains authoritative."""
    differences = []
    for collection in ("accounts", "income_streams", "expenses"):
        actual = resolved[collection]
        by_id = actual if isinstance(actual, dict) else {item["id"]: item for item in actual}
        for item in raw.get(collection, []):
            for key, value in item.items():
                converted = by_id[item["id"]]
                if key in converted and value != converted[key]:
                    differences.append({
                        "path": f"{collection}/{item['id']}/{key}",
                        "fixture_value": value, "engine_value": converted[key],
                    })
    return differences


def build_reference(name: str) -> dict:
    source = FIXTURES[name].read_bytes()
    raw = json.loads(source)
    plan = build_plan_from_fixture(raw)
    # Capture BEFORE simulation: engine code may mutate dataclass objects.
    resolved = asdict(plan)
    result = run_simulation(plan).model_dump(mode="json")
    return {
        "format_version": 1,
        "case": name,
        "source": {"path": str(FIXTURES[name].relative_to(REPO_ROOT)), "sha256": sha256(source)},
        "fixture": raw,
        "engine_input": resolved,
        "input_differences": input_differences(raw, resolved),
        "semantics": SEMANTICS,
        "provenance_file": "manifest.json",
        "result_schema_file": "simulation_result_schema.json",
        "result": result,
    }


def annual_csv(result: dict) -> bytes:
    out = io.StringIO(newline="")
    fields = list(YearSnapshot.model_fields)
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(fields)
    for row in result["yearly_snapshots"]:
        # Optional snapshot fields are omitted from the JSON when unset; write them as null.
        writer.writerow(json.dumps(row.get(key), sort_keys=True, allow_nan=False) for key in fields)
    return out.getvalue().encode()


def export_references(output_dir: Path, cases: list[str] | None = None) -> dict:
    """Write a new immutable bundle directory; manifest is written last on success."""
    names = list(FIXTURES) if cases is None else cases
    if not names or len(set(names)) != len(names) or any(n not in FIXTURES for n in names):
        raise ValueError("Choose one or more distinct canonical fixture names")
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing reference directory: {output_dir}")
    sources = source_hashes()
    files = {"simulation_result_schema.json": json_bytes(SimulationResult.model_json_schema())}
    summaries = []
    for name in names:
        bundle = build_reference(name)
        result = bundle["result"]
        files[f"{name}.json"] = json_bytes(bundle)
        files[f"{name}_annual.csv"] = annual_csv(result)
        # Preserve exact source bytes so the recorded source hash is independently verifiable.
        files[f"{name}_input.json"] = FIXTURES[name].read_bytes()
        snapshots = result["yearly_snapshots"]
        summaries.append({
            "case": name, "years": len(snapshots),
            "first_year": snapshots[0]["year"], "last_year": snapshots[-1]["year"],
            "opening_net_worth": result["initial_snapshot"]["net_worth"],
            "final_net_worth": snapshots[-1]["net_worth"],
            "success": result["metadata"]["success"],
            "failure_year": result["metadata"]["failure_year"],
            "loader_difference_count": len(bundle["input_differences"]),
        })
    if sources != source_hashes():
        raise RuntimeError("Backend source or fixtures changed during export; rerun with stable inputs")
    manifest = {
        "format_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "complete": True,
        "semantics": SEMANTICS,
        "runtime": {"python": platform.python_version(), **{p: version(p) for p in ("pydantic", "numpy", "pytest")}},
        "repository": {
            "head": git_value("rev-parse", "HEAD"),
            "branch": git_value("branch", "--show-current"),
            "status": git_value("status", "--porcelain", "--untracked-files=all"),
            "source_sha256": sources,
        },
        "cases": summaries,
        "artifacts": {name: {"sha256": sha256(data), "bytes": len(data)} for name, data in files.items()},
    }
    # No output directory is created until all six simulations and serialization succeed.
    output_dir.mkdir(parents=True, exist_ok=False)
    for filename, data in files.items():
        (output_dir / filename).write_bytes(data)
    (output_dir / "manifest.json").write_bytes(json_bytes(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory (must not already exist)")
    parser.add_argument("--case", action="append", choices=tuple(FIXTURES), help="Repeat to select cases; default all six")
    args = parser.parse_args()
    try:
        manifest = export_references(args.output_dir, args.case)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Export failed: {exc}\n")
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "cases": manifest["cases"]}, indent=2))


if __name__ == "__main__":
    main()
