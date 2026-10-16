"""POST /plans/{id}/spending-models/compare and /apply."""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.router import create_jwt
from app.models.expense import Expense
from app.models.financial_connection import FinancialSpendingFeed
from app.models.plan import Plan
from app.models.user import User
from app.routers import spending_models as route
from coastmath.engine import spending_model as engine
from coastmath.engine.household_lifecycle import UnsupportedLifecycleInput
from tests.scenario_support import post

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("transactions_on")]


async def _plan(client) -> dict:
    plan = await post(client, "/plans", {"name": "Plan", "birth_year": 1982})
    pid = plan["id"]
    await post(client, f"/plans/{pid}/incomes", {"name": "Salary", "annual_amount": 110000, "withholding_percent": 20})
    living = await post(client, f"/plans/{pid}/expenses", {"name": "Living", "annual_amount": 36000, "category": "essential"})
    fun = await post(client, f"/plans/{pid}/expenses", {"name": "Fun", "annual_amount": 12000, "discretionary_percent": 75})
    await post(client, f"/plans/{pid}/accounts", {"name": "Cash", "account_type": "checking", "balance": 25000})
    paid = await post(client, f"/plans/{pid}/expenses", {"name": "Car", "annual_amount": 5000, "recurrence_years": 5})
    return {"plan": pid, "living": living["id"], "fun": fun["id"], "car": paid["id"]}


def _amounts(essential, discretionary, **extra):
    return {"kind": "amounts", "essential_annual": essential, "discretionary_annual": discretionary, **extra}


async def _compare(client, pid, variants, status=200, **options):
    return await post(client, f"/plans/{pid}/spending-models/compare", {"variants": variants, **options}, status)


async def _expenses(client, pid):
    response = await client.get(f"/api/plans/{pid}/expenses")
    return {row["name"]: row for row in response.json()}


# ── compare ──────────────────────────────────────────────────────

async def test_compare_returns_the_plan_and_each_variant_and_counts_use(client, db_session, test_user, recorded_usage):
    ids = await _plan(client)
    body = await _compare(client, ids["plan"], [_amounts(60000, 10000, label="Lean"), _amounts(30000, 5000)])
    plan = body["plan"]
    assert plan["kind"] == "plan" and plan["label"] == "This plan"
    assert plan["essential_annual"] == pytest.approx(36000 + 3000)
    assert plan["discretionary_annual"] == pytest.approx(9000)
    assert plan["essential_ratio"] == 1.0 and plan["income_ratio"] is None
    assert [v["label"] for v in body["variants"]] == ["Lean", "Model 2"]
    lean = body["variants"][0]
    assert lean["kind"] == "amounts"
    assert lean["essential_ratio"] == pytest.approx(60000 / 39000)
    assert lean["discretionary_ratio"] == pytest.approx(10000 / 9000)
    assert set(lean["net_worth_path"][0]) == {"year", "age", "net_worth", "inflation_factor"}
    assert body["variants"][1]["final_net_worth"] > plan["final_net_worth"] > lean["final_net_worth"]
    assert body["covered_expense_ids"] == [ids["living"], ids["fun"]]
    assert body["spending_feed"] is False and body["seed"] is None and len(body["fingerprint"]) == 64
    assert recorded_usage.count("spending_model_compare") == 1


async def test_compare_scales_take_home_when_asked(client):
    ids = await _plan(client)
    planned = await _compare(client, ids["plan"], [_amounts(39000, 9000, take_home_monthly=5000)])
    assert planned["variants"][0]["income_ratio"] is None
    scaled = await _compare(client, ids["plan"], [_amounts(39000, 9000, take_home_monthly=5000)],
                            income="scale_to_take_home")
    variant = scaled["variants"][0]
    assert variant["income_ratio"] is not None and variant["income_ratio"] < 1
    assert variant["projected_take_home_monthly"] == pytest.approx(5000, abs=1)


async def test_compare_uses_the_spending_feed_expenses(client, db_session, test_user):
    ids = await _plan(client)
    db_session.add(FinancialSpendingFeed(user_id=test_user.id, plan_id=uuid.UUID(ids["plan"]), source_ids=[],
                                         essential_expense_id=uuid.UUID(ids["car"])))
    db_session.commit()
    body = await _compare(client, ids["plan"], [_amounts(9000, 0)])
    assert body["spending_feed"] is True and body["covered_expense_ids"] == [ids["car"]]
    assert body["caveats"] == ["Only the selected spending expenses change."]


async def test_feed_without_expenses_is_not_active(client, db_session, test_user):
    ids = await _plan(client)
    db_session.add(FinancialSpendingFeed(user_id=test_user.id, plan_id=uuid.UUID(ids["plan"]), source_ids=[]))
    db_session.commit()
    assert (await _compare(client, ids["plan"], [_amounts(1, 1)]))["spending_feed"] is False


async def test_compare_with_monte_carlo_shares_one_seed(client, monkeypatch):
    seeds = []
    monkeypatch.setattr(engine, "run_monte_carlo", lambda plan, n_trials, seed, max_workers, deadline: (
        seeds.append(seed) or type("R", (), {"success_rate": 0.9})()))
    ids = await _plan(client)
    body = await _compare(client, ids["plan"], [_amounts(1000, 1000)], monte_carlo_trials=10, seed=99)
    assert seeds == [99, 99] and body["seed"] == 99
    assert body["plan"]["monte_carlo_success_rate"] == body["variants"][0]["monte_carlo_success_rate"] == 0.9


@pytest.mark.parametrize("payload", [
    {"variants": []},
    {"variants": [_amounts(1, 1)] * 7},
    {"variants": [{"kind": "months", "months": ["2026-13"]}]},
    {"variants": [{"kind": "months", "months": []}]},
    {"variants": [{"kind": "other"}]},
    {"variants": [_amounts(-1, 1)]},
    {"variants": [_amounts(1, 1, take_home_monthly=0)]},
    {"variants": [_amounts(1, 1, extra=True)]},
    {"variants": [_amounts(1, 1)], "monte_carlo_trials": 501},
    {"variants": [_amounts(1, 1)], "future_phases": "sometimes"},
    {"variants": [_amounts(1, 1)], "income": "double"},
])
async def test_compare_validation_uses_the_error_envelope(client, payload):
    ids = await _plan(client)
    response = await client.post(f"/api/plans/{ids['plan']}/spending-models/compare", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_compare_reports_unsupported_lifecycle_input(client, monkeypatch):
    def refuse(*args, **kwargs):
        raise UnsupportedLifecycleInput("not supported")

    monkeypatch.setattr(route, "compare_spending_models", refuse)
    ids = await _plan(client)
    response = await client.post(f"/api/plans/{ids['plan']}/spending-models/compare", json={"variants": [_amounts(1, 1)]})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "estate_settings.household_lifecycle"


# ── gating and ownership ─────────────────────────────────────────

async def test_both_routes_refuse_while_transactions_are_off(client, monkeypatch):
    ids = await _plan(client)
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    for path, payload in (("compare", {"variants": [_amounts(1, 1)]}),
                          ("apply", {"variant": _amounts(1, 1), "expected_fingerprint": "0" * 64})):
        response = await client.post(f"/api/plans/{ids['plan']}/spending-models/{path}", json=payload)
        assert response.status_code == 503 and response.json()["error"]["code"] == "FEATURE_DISABLED"


async def test_unknown_and_other_users_plans_are_not_found(client, db_session):
    ids = await _plan(client)
    payloads = {"compare": {"variants": [_amounts(1, 1)]},
                "apply": {"variant": _amounts(1, 1), "expected_fingerprint": "0" * 64}}
    for path, payload in payloads.items():
        response = await client.post(f"/api/plans/{uuid.uuid4()}/spending-models/{path}", json=payload)
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"
    other = User(is_anonymous=True, display_name="Other", settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set("session", create_jwt(other.id))
    for path, payload in payloads.items():
        response = await client.post(f"/api/plans/{ids['plan']}/spending-models/{path}", json=payload)
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


# ── apply ────────────────────────────────────────────────────────

async def test_apply_then_simulate_equals_the_preview(client, db_session, test_user, recorded_usage):
    ids = await _plan(client)
    variant = _amounts(52000.37, 6000)
    preview = await _compare(client, ids["plan"], [variant])
    body = await post(client, f"/plans/{ids['plan']}/spending-models/apply",
                      {"variant": variant, "expected_fingerprint": preview["fingerprint"]}, 200)
    assert sorted(body["updated_expense_ids"]) == sorted([ids["living"], ids["fun"]])
    assert body["created_expense_ids"] == []
    assert body["fingerprint"] != preview["fingerprint"]
    expenses = await _expenses(client, ids["plan"])
    assert expenses["Car"]["annual_amount"] == 5000  # periodic: not covered
    assert expenses["Fun"]["discretionary_percent"] is not None
    simulated = (await post(client, f"/plans/{ids['plan']}/simulate", {}, 200))["yearly_snapshots"]
    path = preview["variants"][0]["net_worth_path"]
    assert [s["year"] for s in simulated] == [p["year"] for p in path]
    for snap, point in zip(simulated, path, strict=True):
        assert snap["net_worth"] == pytest.approx(point["net_worth"], rel=1e-9, abs=1e-6)
    # The saved plan now previews as the model.
    again = await _compare(client, ids["plan"], [variant])
    assert again["fingerprint"] == body["fingerprint"]
    assert again["plan"]["essential_annual"] == pytest.approx(52000.37, abs=0.5)
    assert again["plan"]["discretionary_annual"] == pytest.approx(6000, abs=0.5)
    assert recorded_usage.count("spending_model_apply") == 1


async def test_apply_adds_a_missing_bucket_expense(client):
    plan = await post(client, "/plans", {"name": "Plan", "birth_year": 1982})
    pid = plan["id"]
    await post(client, f"/plans/{pid}/expenses", {"name": "Living", "annual_amount": 30000, "category": "essential"})
    variant = _amounts(30000, 8000)
    preview = await _compare(client, pid, [variant])
    body = await post(client, f"/plans/{pid}/spending-models/apply",
                      {"variant": variant, "expected_fingerprint": preview["fingerprint"]}, 200)
    assert body["updated_expense_ids"] == [] and len(body["created_expense_ids"]) == 1
    assert body["discretionary_ratio"] is None and body["essential_ratio"] == pytest.approx(1.0)
    added = (await _expenses(client, pid))["Discretionary spending"]
    assert (added["annual_amount"], added["category"], added["inflation_linked"]) == (8000, "discretionary", True)
    assert added["start_milestone_id"] is None and added["end_milestone_id"] is None


async def test_apply_refuses_a_stale_fingerprint_and_saves_nothing(client):
    ids = await _plan(client)
    variant = _amounts(50000, 5000)
    preview = await _compare(client, ids["plan"], [variant])
    response = await client.put(f"/api/plans/{ids['plan']}/expenses/{ids['living']}", json={"annual_amount": 37000})
    assert response.status_code == 200
    response = await client.post(f"/api/plans/{ids['plan']}/spending-models/apply",
                                 json={"variant": variant, "expected_fingerprint": preview["fingerprint"]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "CONFLICT"
    assert (await _expenses(client, ids["plan"]))["Living"]["annual_amount"] == 37000


async def test_apply_refuses_a_plan_with_a_spending_feed(client, db_session, test_user):
    ids = await _plan(client)
    preview = await _compare(client, ids["plan"], [_amounts(1, 1)])
    db_session.add(FinancialSpendingFeed(user_id=test_user.id, plan_id=uuid.UUID(ids["plan"]), source_ids=[],
                                         discretionary_expense_id=uuid.UUID(ids["fun"])))
    db_session.commit()
    response = await client.post(f"/api/plans/{ids['plan']}/spending-models/apply",
                                 json={"variant": _amounts(1, 1), "expected_fingerprint": preview["fingerprint"]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "SPENDING_FEED_ACTIVE"


@pytest.mark.parametrize("fingerprint", ["abc", "G" * 64, None])
async def test_apply_requires_a_fingerprint(client, fingerprint):
    ids = await _plan(client)
    payload = {"variant": _amounts(1, 1)}
    if fingerprint is not None:
        payload["expected_fingerprint"] = fingerprint
    response = await client.post(f"/api/plans/{ids['plan']}/spending-models/apply", json=payload)
    assert response.status_code == 422


async def test_apply_respects_archived_plans(client, db_session):
    ids = await _plan(client)
    preview = await _compare(client, ids["plan"], [_amounts(1, 1)])
    db_session.get(Plan, uuid.UUID(ids["plan"])).archived_at = datetime.now(UTC)
    db_session.commit()
    # Analysis stays open on an archived plan; changes do not.
    assert (await _compare(client, ids["plan"], [_amounts(1, 1)]))["fingerprint"] == preview["fingerprint"]
    response = await client.post(f"/api/plans/{ids['plan']}/spending-models/apply",
                                 json={"variant": _amounts(1, 1), "expected_fingerprint": preview["fingerprint"]})
    assert response.status_code == 409 and response.json()["error"]["message"] == "Restore this plan before editing it."
    expense = db_session.get(Expense, uuid.UUID(ids["living"]))
    db_session.refresh(expense)
    assert float(expense.annual_amount) == 36000
