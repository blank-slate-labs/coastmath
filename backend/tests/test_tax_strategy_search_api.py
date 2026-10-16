"""POST /api/plans/{plan_id}/tax-strategies/search."""

import uuid
from threading import BoundedSemaphore

import pytest

from app import engine_capacity
from app.auth.router import create_jwt
from app.models.user import User
from app.seed import seed_demo_plan
from coastmath.engine import tax_strategy_search

pytestmark = pytest.mark.anyio


async def _setup(client) -> dict:
    plan = (await client.post("/api/plans", json={"name": "Search", "birth_year": 1966, "plan_type": "NOW",
                                                  "life_expectancy": 90, "filing_status": "single"})).json()
    pid = plan["id"]

    async def account(name, kind, balance, **extra):
        r = await client.post("/api/accounts", json={"name": name, "account_type": kind, "balance": balance, **extra})
        assert r.status_code == 201, r.text
        return r.json()

    ira = await account("IRA", "traditional_ira", 1_500_000)
    roth = await account("Roth", "roth_ira", 50_000)
    cash = await account("Cash", "checking", 100_000)
    brk = await account("Brokerage", "taxable_brokerage", 600_000, cost_basis=200_000)
    assert (await client.post(f"/api/plans/{pid}/expenses", json={"name": "Living", "annual_amount": 90_000})).status_code == 201
    order = [ira, cash, brk, roth]
    r = await client.put(f"/api/plans/{pid}/drawdown-order",
                         json={"items": [{"rank": i + 1, "source_account_id": a["id"]} for i, a in enumerate(order)]})
    assert r.status_code in (200, 201), r.text
    ms = {}
    for name, age in (("m65", 65), ("m70", 70)):
        r = await client.post(f"/api/plans/{pid}/milestones", json={"name": name, "trigger_type": "age",
                                                                    "trigger_value": age, "sort_order": age})
        assert r.status_code == 201, r.text
        ms[name] = r.json()["id"]
    return {"pid": pid, "ira": ira["id"], "roth": roth["id"], "cash": cash["id"], "brk": brk["id"], "ms": ms}


def _body(ctx, **overrides) -> dict:
    body = {"objective": "lifetime_taxes", "bracket_rates": [0.12, 0.22],
            "conversion": {"source_account_id": ctx["ira"], "target_account_id": ctx["roth"]}}
    body.update(overrides)
    return body


async def _search(client, ctx, **overrides):
    return await client.post(f"/api/plans/{ctx['pid']}/tax-strategies/search", json=_body(ctx, **overrides))


async def test_search_returns_a_ranked_bounded_comparison_and_counts_one_use(client, db_session, test_user, recorded_usage):
    ctx = await _setup(client)
    r = await _search(client, ctx, harvest={"source_account_id": ctx["brk"]}, blend_withdrawals=True,
                      drawdown_presets=["pretax_first"],
                      windows=[{"start_milestone_id": ctx["ms"]["m65"], "end_milestone_id": ctx["ms"]["m70"]}],
                      max_simulations=40)
    assert r.status_code == 200, r.text
    out = r.json()
    counts = out["counts"]
    assert counts["max_simulations"] == 40 and counts["simulated"] <= 40
    assert counts["simulated"] == len(out["candidates"])
    assert counts["simulated"] == counts["stage1_simulated"] + counts["stage2_simulated"] + 1
    assert out["baseline_key"] == "baseline" and out["objective_direction"] == "lower"
    assert [c["rank"] for c in out["candidates"]] == list(range(1, len(out["candidates"]) + 1))
    assert sum(c["is_best"] for c in out["candidates"]) == 1
    assert out["best_key"] == out["candidates"][0]["key"]
    assert out["windows"][0]["label"] == "From m65 to m70"
    assert any("not a global optimum" in c for c in out["caveats"])
    baseline = next(c for c in out["candidates"] if c["is_baseline"])
    assert baseline["changes"] == [] and baseline["delta_vs_baseline"] == 0
    assert all(c["delta_vs_baseline"] == pytest.approx(c["objective_value"] - baseline["objective_value"])
               for c in out["candidates"])
    best = out["candidates"][0]
    assert best["objective_value"] == min(c["objective_value"] for c in out["candidates"] if c["success"])
    assert out["pre_tax_discount_rate"] == 0.24 and isinstance(out["priorities_revision"], int)
    # Every objective's measure is reported for every candidate.
    for field in ("lifetime_taxes", "net_legacy", "final_net_worth", "total_aca_subsidies", "total_irmaa_surcharge",
                  "total_rmd_distributions", "lifetime_effective_tax_rate"):
        assert all(isinstance(c[field], float | int) for c in out["candidates"]), field
    # The search never writes: allocation rules and revision stay as they were.
    after = (await client.get(f"/api/plans/{ctx['pid']}/priorities")).json()
    assert after["items"] == [] and after["revision"] == out["priorities_revision"]
    assert recorded_usage.count("tax_optimizer") == 1


async def test_search_budget_is_enforced_and_reported(client):
    ctx = await _setup(client)
    r = await _search(client, ctx, harvest={"source_account_id": ctx["brk"]}, blend_withdrawals=True,
                      bracket_rates=[0.10, 0.12, 0.22, 0.24],
                      drawdown_presets=["taxable_first", "pretax_first", "roth_before_pretax"], max_simulations=7)
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert counts["simulated"] == 7 and counts["budget_exhausted"] and counts["skipped_by_budget"] > 0
    assert len(r.json()["candidates"]) == 7
    assert any("not simulated" in c for c in r.json()["caveats"])


async def test_applying_a_candidate_reproduces_its_reported_outcome(client):
    ctx = await _setup(client)
    pid = ctx["pid"]
    r = await _search(client, ctx, objective="net_legacy", harvest={"source_account_id": ctx["brk"]},
                      drawdown_presets=["roth_before_pretax"], blend_withdrawals=True,
                      windows=[{"start_milestone_id": ctx["ms"]["m65"]}])
    out = r.json()
    best = next(c for c in out["candidates"] if c["is_best"])
    candidate = best if not best["is_baseline"] else next(c for c in out["candidates"] if c["changes"] and c["success"])
    proposal = candidate["proposal"]
    # Review panel contents: each change is described, and the proposal matches the list of changes.
    assert candidate["changes"] and all(ch["summary"] for ch in candidate["changes"])
    adds = [ch for ch in candidate["changes"] if ch["target"] == "priority"]
    assert len(adds) == len(proposal["priorities_to_add"])

    current = (await client.get(f"/api/plans/{pid}/priorities")).json()
    assert current["revision"] == out["priorities_revision"]
    items = [{k: v for k, v in item.items() if k not in ("id", "plan_id")} for item in current["items"]]
    items += proposal["priorities_to_add"]
    r = await client.put(f"/api/plans/{pid}/priorities", json={"expected_revision": out["priorities_revision"], "items": items})
    assert r.status_code == 200, r.text
    if proposal["tax_settings"]:
        plan = (await client.get(f"/api/plans/{pid}")).json()
        merged = {**(plan.get("tax_settings") or {}), **proposal["tax_settings"]}
        r = await client.put(f"/api/plans/{pid}", json={"tax_settings": merged})
        assert r.status_code == 200, r.text
    if proposal["drawdown_order"]:
        r = await client.put(f"/api/plans/{pid}/drawdown-order", json={"items": proposal["drawdown_order"]})
        assert r.status_code in (200, 201), r.text

    sim = (await client.post(f"/api/plans/{pid}/simulate")).json()
    legacy = sim["metadata"]["net_legacy"]
    assert legacy["net_legacy"] == pytest.approx(candidate["net_legacy"], rel=1e-6)
    assert sum(s["taxes"] for s in sim["yearly_snapshots"]) == pytest.approx(candidate["lifetime_taxes"], rel=1e-6)
    assert candidate["objective_value"] == pytest.approx(legacy["net_legacy"] - 0.24 * legacy["pretax_balance"], rel=1e-6)

    # The allocation revision moved: applying the same stale proposal again is refused (409), not merged.
    stale = await client.put(f"/api/plans/{pid}/priorities",
                             json={"expected_revision": out["priorities_revision"], "items": items})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT"
    assert (await client.get(f"/api/plans/{pid}/priorities")).json()["revision"] == out["priorities_revision"] + 1


async def test_search_requires_a_session_and_hides_other_households(client, db_session):
    ctx = await _setup(client)
    owner_cookie = client.cookies.get("session")
    other = User(is_anonymous=True, display_name="Other household", settings={})
    db_session.add(other)
    db_session.commit()
    client.cookies.set("session", create_jwt(other.id))
    r = await _search(client, ctx)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    foreign = seed_demo_plan(other.id, db_session)
    db_session.commit()
    # The owner's accounts are not reachable through a plan of the same other household.
    r = await client.post(f"/api/plans/{foreign.id}/tax-strategies/search", json=_body(ctx))
    assert r.status_code == 422
    client.cookies.clear()
    r = await _search(client, ctx)
    assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_REQUIRED"
    client.cookies.set("session", owner_cookie)
    assert (await _search(client, ctx, max_simulations=6)).status_code == 200


@pytest.mark.parametrize("override, field", [
    ({"objective": "vibes"}, "objective"),
    ({"bracket_rates": [0.13, 0.22]}, "bracket_rates[0]"),
    ({"bracket_rates": [0.99]}, "bracket_rates[0]"),
])
async def test_search_rejects_unknown_objectives_and_non_bracket_rates(client, override, field):
    ctx = await _setup(client)
    r = await _search(client, ctx, **override)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert r.json()["error"]["details"][0]["field"] == field


async def test_search_rejects_unusable_accounts_and_milestones(client):
    ctx = await _setup(client)
    roth_source = {"conversion": {"source_account_id": ctx["roth"], "target_account_id": ctx["ira"]}}
    r = await _search(client, ctx, **roth_source)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"].startswith("conversion.")
    r = await _search(client, ctx, conversion={"source_account_id": str(uuid.uuid4()), "target_account_id": ctx["roth"]})
    assert r.status_code == 422
    r = await _search(client, ctx, conversion=None, harvest={"source_account_id": ctx["ira"]})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "harvest.source_account_id"
    nobasis = (await client.post("/api/accounts", json={"name": "NoBasis", "account_type": "taxable_brokerage",
                                                         "balance": 10_000})).json()
    r = await _search(client, ctx, conversion=None, harvest={"source_account_id": nobasis["id"]})
    assert r.status_code == 422 and "basis" in r.json()["error"]["message"]
    r = await _search(client, ctx, windows=[{"start_milestone_id": str(uuid.uuid4())}])
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"].startswith("windows[0]")


async def test_search_accepts_year_and_age_windows(client):
    ctx = await _setup(client)
    r = await _search(client, ctx, windows=[
        {"start_age": 65, "end_age": 69},
        {"start_year": 2031, "end_milestone_id": ctx["ms"]["m70"]},
        {"end_year": 2035},
    ])
    assert r.status_code == 200, r.text
    out = r.json()
    assert [w["label"] for w in out["windows"]] == [
        "From age 65 through age 69", "From 2031 to m70", "Through 2035"]
    assert (out["windows"][0]["start_age"], out["windows"][0]["end_age"]) == (65, 69)
    windowed = next(c for c in out["candidates"] if c["window_index"] == 0)
    milestones = windowed["proposal"]["milestones_to_add"]
    # Inclusive ends stop the rule from the following age or year.
    assert [(m["trigger_type"], m["trigger_value"]) for m in milestones] == [("age", 65.0), ("age", 70.0)]
    rule = windowed["proposal"]["priorities_to_add"][0]
    assert (rule["start_milestone_id"], rule["end_milestone_id"]) == (milestones[0]["id"], milestones[1]["id"])
    assert sum(ch["target"] == "milestone" for ch in windowed["changes"]) == 2
    mixed = next(c for c in out["candidates"] if c["window_index"] == 1)
    assert [m["trigger_date"] for m in mixed["proposal"]["milestones_to_add"]] == ["2031-01-01"]
    assert mixed["proposal"]["priorities_to_add"][0]["end_milestone_id"] == ctx["ms"]["m70"]
    whole = next(c for c in out["candidates"] if c["window_index"] is None and not c["is_baseline"])
    assert whole["proposal"]["milestones_to_add"] == []


@pytest.mark.parametrize("override", [
    {"conversion": None},  # rates without an action
    {"bracket_rates": []},  # an action without rates
    {"bracket_rates": [0.12, 0.12]},
    {"max_simulations": 129},
    {"max_simulations": 1},
    {"max_simulations": 2},  # cannot cover the baseline plus two rates
    {"bracket_rates": [0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37, 0.12]},
    {"drawdown_presets": ["saved"]},
    {"drawdown_presets": ["pretax_first", "pretax_first"]},
    {"windows": [{}]},
    {"windows": [{"start_milestone_id": None}]},
    {"windows": [{"start_year": 2030, "start_age": 60}]},
    {"windows": [{"start_year": 2035, "end_year": 2030}]},
    {"windows": [{"start_age": 60}, {"start_age": 60}]},
    {"windows": [{"end_age": 121}]},
    {"unknown_field": 1},
    {"bracket_rates": [float("nan")]},
    {"bracket_rates": [0]},
])
async def test_search_rejects_malformed_bodies_without_simulating(client, monkeypatch, override):
    ctx = await _setup(client)
    monkeypatch.setattr(tax_strategy_search, "run_simulation",
                        lambda *_a, **_k: pytest.fail("a rejected request must not run the engine"))
    body = _body(ctx)
    body.update(override)
    if "bracket_rates" in override and override["bracket_rates"] and override["bracket_rates"][0] != override["bracket_rates"][0]:
        r = await client.post(f"/api/plans/{ctx['pid']}/tax-strategies/search", content='{"bracket_rates":[NaN],'
                              f'"conversion":{{"source_account_id":"{ctx["ira"]}","target_account_id":"{ctx["roth"]}"}}}}',
                              headers={"content-type": "application/json"})
    else:
        r = await client.post(f"/api/plans/{ctx['pid']}/tax-strategies/search", json=body)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_search_with_only_drawdown_presets_needs_no_rates(client):
    ctx = await _setup(client)
    r = await client.post(f"/api/plans/{ctx['pid']}/tax-strategies/search",
                          json={"objective": "final_net_worth", "drawdown_presets": ["taxable_first"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert {c["key"] for c in out["candidates"]} == {"baseline", "order@-/taxable_first/all"}
    assert out["survivor_rates"] == [] and out["objective_direction"] == "higher"


async def test_search_answers_429_while_engine_capacity_is_taken(client, monkeypatch):
    ctx = await _setup(client)
    slots = BoundedSemaphore(1)
    monkeypatch.setattr(engine_capacity, "_slots", slots)
    slots.acquire()
    busy = await _search(client, ctx)
    assert busy.status_code == 429 and busy.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    slots.release()
    assert (await _search(client, ctx, max_simulations=6)).status_code == 200
