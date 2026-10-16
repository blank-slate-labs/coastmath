"""Explicit fixture semantics and isolated production-route regression coverage.

These tests never alter the original persona fixtures or captured baselines.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from coastmath.engine.milestones import evaluate_milestones
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import SimState
from coastmath.schemas.plan_data_request import request_to_engine_data
from tests.corrected_fixture_support import (
    FIXTURES,
    corrected_fixture,
    engine_request,
    persist_fixture,
)
from tests.persona.harness import build_plan_from_fixture

CASES = tuple(json.loads((FIXTURES / "provenance.json").read_text()))


@pytest.mark.parametrize("case", CASES)
def test_corrected_copy_preserves_original_hash_and_only_recorded_changes(case):
    manifest = json.loads((FIXTURES / "provenance.json").read_text())[case]
    original = Path(__file__).resolve().parents[2] / manifest["original_path"]
    assert hashlib.sha256(original.read_bytes()).hexdigest() == manifest["original_sha256"]
    expected = json.loads(original.read_text())
    for change in manifest["changes"]:
        collection, identifier, field = change["path"].split("/")
        record = next(record for record in expected[collection] if record["id"] == identifier)
        assert record.get(field) == change["before"]
        record[field] = change["after"]
    assert expected == corrected_fixture(case)


@pytest.mark.parametrize("explicit", [None, False, True])
def test_income_label_does_not_override_explicit_classification_or_owner(explicit):
    raw = corrected_fixture("standard_plan")
    income = raw["income_streams"][0]
    income["name"] = "Spouse Social Security administration salary"
    income.pop("owner")
    if explicit is None:
        income.pop("is_social_security")
    else:
        income["is_social_security"] = explicit
    loaded = build_plan_from_fixture(raw).income_streams[0]
    assert loaded.owner == "self"
    assert loaded.is_social_security is bool(explicit)
    # Only an explicitly requested archival replay retains the historical guess.
    assert build_plan_from_fixture(raw, legacy_replay=True).income_streams[0].is_social_security


@pytest.mark.parametrize("owner", ["self", "spouse", "joint"])
def test_loader_preserves_explicit_account_owner_and_name(owner):
    raw = corrected_fixture("standard_plan")
    raw["accounts"][0].update(owner=owner, name="Independent label")
    loaded = build_plan_from_fixture(raw).accounts[raw["accounts"][0]["id"]]
    assert (loaded.owner, loaded.name) == (owner, "Independent label")
    archived = build_plan_from_fixture(raw, legacy_replay=True).accounts[raw["accounts"][0]["id"]]
    assert (archived.owner, archived.name) == ("self", "")


def test_median_spouse_retirement_uses_explicit_calendar_boundary():
    raw = corrected_fixture("standard_plan")
    plan = build_plan_from_fixture(raw)
    retirement_id = raw["spouse"]["retirement_milestone_id"]
    state = SimState(year=2054)
    assert retirement_id not in evaluate_milestones(state, plan.milestones, 2054, plan.birth_year)
    assert retirement_id in evaluate_milestones(state, plan.milestones, 2055, plan.birth_year)
    assert retirement_id not in evaluate_milestones(state, plan.milestones, 2056, plan.birth_year)
    assert plan.income_streams[1].owner == "spouse"
    assert plan.income_streams[2].is_social_security


def test_two_workers_use_separate_social_security_wage_bases():
    raw = corrected_fixture("high_earner_late_saver")
    corrected = build_plan_from_fixture(raw)
    corrected.life_expectancy = 51
    same_worker = deepcopy(corrected)
    same_worker.income_streams[1].owner = "self"
    # Independently: two wage bases, Medicare on all wages, joint additional
    # Medicare above $250k. 2026 SSA wage base is $184,500.
    expected = (184_500 + 150_000) * 0.062 + 450_000 * 0.0145 + 200_000 * 0.009
    first = run_simulation(corrected).yearly_snapshots[0]
    other = run_simulation(same_worker).yearly_snapshots[0]
    assert first.fica_tax == pytest.approx(expected, abs=0.01)
    assert first.fica_tax - other.fica_tax == pytest.approx(9_300, abs=0.01)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.anyio
async def test_corrected_fixture_matches_persisted_and_stateless_routes(case, db_session, test_user, client):
    raw = corrected_fixture(case)
    loaded = build_plan_from_fixture(raw)
    persisted = persist_fixture(raw, db_session, test_user)
    assert [(i.owner, i.is_social_security) for i in loaded.income_streams] == [
        (i.owner, i.is_social_security) for i in persisted.income_streams
    ]
    assert loaded.accounts == persisted.accounts
    assert loaded.milestones == persisted.milestones
    assert loaded.expenses == persisted.expenses
    request = engine_request(loaded)
    stateless = request_to_engine_data(request)
    expected = run_simulation(loaded).model_dump(mode="json")
    assert run_simulation(stateless).model_dump(mode="json") == expected
    assert run_simulation(persisted).model_dump(mode="json") == expected
    a = await client.post(f"/api/plans/{loaded.plan_id}/simulate", headers={"X-Client-Date": "2026-09-08"})
    b = await client.post("/api/simulate/stateless", json=request.model_dump(mode="json"))
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() == expected
