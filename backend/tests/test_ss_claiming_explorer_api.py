"""POST /api/plans/{plan_id}/social-security/claiming."""

import uuid

import pytest

from app.auth.router import create_jwt
from app.models.user import User
from app.routers import ss_claiming as route
from coastmath.engine.household_lifecycle import UnsupportedLifecycleInput

pytestmark = pytest.mark.anyio


async def _couple(client) -> tuple[str, dict, dict]:
    plan = await client.post("/api/plans", json={
        "name": "Claiming", "birth_year": 1966, "birth_month": 1, "plan_type": "FIXED_DATE",
        "start_date": "2026-01-01", "life_expectancy": 90, "filing_status": "married_filing_jointly",
        "spouse": {"name": "Partner", "birth_year": 1968, "birth_month": 7, "life_expectancy": 90},
    })
    assert plan.status_code == 201, plan.text
    pid = plan.json()["id"]
    assert (await client.post("/api/accounts", json={"name": "Cash", "account_type": "checking",
                                                     "balance": 600_000})).status_code == 201
    assert (await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living",
                                                                  "annual_amount": 40_000})).status_code == 201
    milestone = (await client.post(f"/api/plans/{pid}/milestones", json={
        "name": "Social Security begins", "trigger_type": "age", "trigger_value": 67})).json()
    own = (await client.post(f"/api/plans/{pid}/incomes", json={
        "name": "Social Security", "annual_amount": 30_000, "tax_category": "social_security",
        "start_milestone_id": milestone["id"]})).json()
    partner = (await client.post(f"/api/plans/{pid}/incomes", json={
        "name": "Partner Social Security", "annual_amount": 1, "tax_category": "social_security", "owner": "spouse",
        "claiming_age": 67, "ss_benefit_basis": "pia", "pia_monthly": 1_200})).json()
    return pid, own, partner


async def test_route_compares_claiming_ages_and_the_patch_saves(client, db_session, test_user, recorded_usage):
    pid, own, partner = await _couple(client)
    r = await client.post(f"/api/plans/{pid}/social-security/claiming")
    assert r.status_code == 200, r.text
    body = r.json()
    persons = {p["owner"]: p for p in body["persons"]}
    # The owner's stream runs on a milestone at 67; the PIA-basis partner claims at 67.
    assert persons["self"] | {"candidate_ages": None} == {
        "owner": "self", "adjustable": True, "reason": None, "income_id": own["id"], "birth_year": 1966,
        "birth_month": 1, "full_retirement_age": 67.0, "current_claim_age": 67.0, "candidate_ages": None,
        "benefit_basis": "amount", "earnings_test_withholds": False}
    assert persons["self"]["candidate_ages"] == list(range(62, 71))
    assert persons["spouse"]["benefit_basis"] == "pia" and persons["spouse"]["current_claim_age"] == 67.0
    assert len(body["runs"]) == 81 and len(body["patches"]) == 18
    assert body["pre_tax_discount_rate"] == 0.24
    assert len(body["years"]) == len(body["current"]["social_security_by_year"])
    best = body["runs"][body["best_index"]]
    assert body["best_end_net_worth_after_tax_change"] == pytest.approx(best["end_net_worth_after_tax_change"])
    # Amount basis carries a rescaled amount; PIA basis does not.
    own_70 = next(p for p in body["patches"] if p["owner"] == "self" and p["claiming_age"] == 70)
    partner_64 = next(p for p in body["patches"] if p["owner"] == "spouse" and p["claiming_age"] == 64)
    assert own_70["changes"] == {"claiming_age": 70, "start_milestone_id": None, "start_month": None,
                                 "annual_amount": pytest.approx(30_000 * 1.24)}
    assert partner_64["changes"] == {"claiming_age": 64, "start_milestone_id": None, "start_month": None}
    expected = next(run for run in body["runs"] if run["claim_ages"] == {"self": 70, "spouse": 64})

    # Adopt both through the income update route: the plan now matches that run.
    for patch in (own_70, partner_64):
        saved = await client.put(f"/api/plans/{pid}/incomes/{patch['income_id']}", json=patch["changes"])
        assert saved.status_code == 200, saved.text
    after = (await client.post(f"/api/plans/{pid}/social-security/claiming")).json()
    assert after["current"]["claim_ages"] == {"self": 70, "spouse": 64}
    assert after["current"]["end_net_worth"] == pytest.approx(expected["end_net_worth"], abs=0.01)

    assert recorded_usage.count("ss_claiming_explorer") == 2


async def test_plan_without_social_security_returns_reasons(client):
    plan = (await client.post("/api/plans", json={"name": "None", "birth_year": 1980, "plan_type": "NOW",
                                                  "life_expectancy": 90})).json()
    r = await client.post(f"/api/plans/{plan['id']}/social-security/claiming", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(p["owner"], p["adjustable"], p["reason"]) for p in body["persons"]] == [("self", False, "no_benefit")]
    assert body["runs"] == [] and body["current"] is None and body["best_index"] is None and body["patches"] == []


async def test_unknown_and_foreign_plans_are_not_found(client, db_session):
    r = await client.post(f"/api/plans/{uuid.uuid4()}/social-security/claiming")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    pid, _, _ = await _couple(client)
    other = User(is_anonymous=True, display_name="Other household", settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set("session", create_jwt(other.id))
    r = await client.post(f"/api/plans/{pid}/social-security/claiming")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


async def test_request_body_is_strict(client):
    pid, _, _ = await _couple(client)
    r = await client.post(f"/api/plans/{pid}/social-security/claiming", json={"ages": [62]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(("error", "status", "code", "field"), [
    (UnsupportedLifecycleInput("Unsupported lifecycle"), 422, "VALIDATION_ERROR", "estate_settings.household_lifecycle"),
    (ValueError("Bad input"), 422, "VALIDATION_ERROR", "plan"),
    (RuntimeError("boom"), 500, "SIMULATION_FAILED", None),
])
async def test_engine_errors_use_the_error_envelope(client, monkeypatch, error, status, code, field):
    pid, _, _ = await _couple(client)

    def fail(_plan):
        raise error

    monkeypatch.setattr(route, "explore_claiming_ages", fail)
    r = await client.post(f"/api/plans/{pid}/social-security/claiming")
    assert r.status_code == status
    envelope = r.json()["error"]
    assert envelope["code"] == code
    assert [d["field"] for d in envelope["details"]] == ([field] if field else [])
