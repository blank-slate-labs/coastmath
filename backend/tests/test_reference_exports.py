"""Lossless fixture export checks, independent of checkpoint baseline tolerances."""

import csv
import hashlib
import json
from dataclasses import asdict

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.schemas.simulation import SimulationResult, YearSnapshot
from scripts.export_fixture_references import FIXTURES, export_references
from tests.persona.harness import build_plan_from_fixture

EXPECTED = {
    "fire_persona": (2026, 2083, 470_000, 180_000, 55_000),
    "high_earner_late_saver": (2026, 2067, 290_000, 450_000, 140_000),
    "self_employed_sepp": (2026, 2075, 680_000, 220_000, 70_000),
    "inherited_ira": (2026, 2058, 910_000, 140_000, 80_000),
    "hnw_estate": (2026, 2055, 7_000_000, 250_000, 250_000),
    "standard_plan": (2025, 2079, 260_000, 160_000, 66_000),
}


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    directory = tmp_path_factory.mktemp("references") / "output"
    original = {path: path.read_bytes() for path in FIXTURES.values()}
    manifest = export_references(directory)
    assert {path: path.read_bytes() for path in FIXTURES.values()} == original
    return directory, manifest


@pytest.mark.parametrize("name", EXPECTED)
def test_full_results_roundtrip_and_accounting(exported, name):
    directory, _ = exported
    bundle = json.loads((directory / f"{name}.json").read_text())
    raw = json.loads(FIXTURES[name].read_bytes())
    plan = build_plan_from_fixture(raw)
    assert bundle["fixture"] == raw
    assert bundle["engine_input"] == asdict(plan)
    direct = run_simulation(plan).model_dump(mode="json")
    assert bundle["result"] == direct  # Includes nested details and all unrounded values.
    assert SimulationResult.model_validate(direct).model_dump(mode="json") == direct
    with (directory / f"{name}_annual.csv").open(newline="") as stream:
        rows = [{key: json.loads(value) for key, value in row.items()} for row in csv.DictReader(stream)]
    assert rows == direct["yearly_snapshots"]
    assert all(set(row) == set(YearSnapshot.model_fields) for row in rows)
    first, last, opening, income, expenses = EXPECTED[name]
    assert [row["year"] for row in rows] == list(range(first, last + 1))
    assert direct["metadata"]["start_date"] == f"{first}-01-01"
    assert direct["metadata"]["first_year_fraction"] == 1
    assert direct["metadata"]["end_year"] == last
    assert direct["initial_snapshot"]["net_worth"] == opening
    assert sum(direct["initial_snapshot"]["accounts"].values()) == opening
    assert rows[0]["gross_income"] == income
    assert rows[0]["expenses"] == expenses
    for row in rows:
        assert row["net_worth"] == pytest.approx(
            sum(row["accounts"].values()) + row["real_assets_value"]
            - row["liabilities_balance"] - row["tax_balance"] - row["unfunded_expenses"],
            abs=1e-6,
        )
    # Byte-for-byte input provenance survives export, including formatting.
    source = (directory / f"{name}_input.json").read_bytes()
    assert source == FIXTURES[name].read_bytes()
    assert hashlib.sha256(source).hexdigest() == bundle["source"]["sha256"]


def test_manifest_complete_and_hashes_independently_match(exported):
    directory, manifest = exported
    assert manifest["complete"] is True
    assert {item["case"] for item in manifest["cases"]} == set(EXPECTED)
    assert len(manifest["artifacts"]) == 19
    for name, artifact in manifest["artifacts"].items():
        data = (directory / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
        assert len(data) == artifact["bytes"]
    assert json.loads((directory / "simulation_result_schema.json").read_text()) == SimulationResult.model_json_schema()
    assert "backend/coastmath/engine/simulator.py" in manifest["repository"]["source_sha256"]
    assert "backend/coastmath/data/tax_brackets_2026.json" in manifest["repository"]["source_sha256"]


def test_explicit_metadata_is_preserved_and_remaining_fixture_limits_exposed(exported):
    directory, _ = exported
    median = json.loads((directory / "standard_plan.json").read_text())
    assert any(a["owner"] == "spouse" for a in median["engine_input"]["accounts"].values())
    assert any(e["category"] == "discretionary" for e in median["engine_input"]["expenses"])
    assert not any(d["path"].endswith("/owner") and d["fixture_value"] == "spouse"
                   for d in median["input_differences"])
    assert not next(i for i in median["engine_input"]["income_streams"]
                    if "Social Security" in i["name"])["is_social_security"]
    assert next(m for m in median["result"]["metadata"]["milestone_outcomes"] if m["name"] == "Spouse Retirement")["year"] == 2053
    hnw = json.loads((directory / "hnw_estate.json").read_text())
    assert hnw["engine_input"]["estate_settings"]["custom_federal_exemption_enabled"] is False


def test_existing_directory_cannot_be_overwritten(exported):
    directory, _ = exported
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        export_references(directory)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


@pytest.mark.parametrize("cases", [[], ["unknown"], ["fire_persona", "fire_persona"]])
def test_invalid_case_selection_creates_no_artifacts(tmp_path, cases):
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="distinct canonical"):
        export_references(output, cases)
    assert not output.exists()
