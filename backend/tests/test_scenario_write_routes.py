"""Every plan-scoped write route: editing Main through it reaches its scenario.

A new non-GET route under ``/api/plans/{plan_id}`` or ``/api/accounts``
fails ``test_every_plan_write_route_has_a_decision`` until it is added to
``WRITES`` (with a case proving the scenario reflects it) or to
``NOT_INPUT_WRITES`` (with the reason it changes no inherited input).
"""
import pytest

from app.main import app
from tests.scenario_support import build_main, by_name, create_scenario, get, post, put


async def _scenario(client, sid):
    return await get(client, f"/plans/{sid}")


async def _accounts(client, sid):
    return {row["name"]: row for row in await get(client, f"/plans/{sid}/accounts")}


async def create_account_pool(client, ids, sid):
    await post(client, f"/accounts?plan_id={ids['plan']}", {"name": "Pool HSA", "account_type": "hsa", "balance": 10})
    assert (await _accounts(client, sid))["Pool HSA"]["balance"] == 10


async def update_account_pool(client, ids, sid):
    await put(client, f"/accounts/{ids['cash']}?plan_id={ids['plan']}", {"balance": 33333})
    assert (await _accounts(client, sid))["Cash"]["balance"] == 33333


async def delete_account_pool(client, ids, sid):
    spare = await post(client, f"/accounts?plan_id={ids['plan']}", {"name": "Spare", "account_type": "checking", "balance": 1})
    assert "Spare" in await _accounts(client, sid)
    assert (await client.delete(f"/api/accounts/{spare['id']}?plan_id={ids['plan']}")).status_code == 204
    assert "Spare" not in await _accounts(client, sid)


async def create_account(client, ids, sid):
    await post(client, f"/plans/{ids['plan']}/accounts", {"name": "Roth", "account_type": "roth_ira", "balance": 7000})
    accounts = await _accounts(client, sid)
    assert accounts["Roth"]["balance"] == 7000
    # The inherited withdrawal order picked the new account up too.
    order = (await _scenario(client, sid))["drawdown_order"]
    assert accounts["Roth"]["id"] in {row["source_account_id"] for row in order}


async def update_account(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}/accounts/{ids['brokerage']}", {"balance": 160000, "cost_basis": 95000})
    brokerage = (await _accounts(client, sid))["Brokerage"]
    assert (brokerage["balance"], brokerage["cost_basis"]) == (160000, 95000)


async def delete_account(client, ids, sid):
    spare = await post(client, f"/plans/{ids['plan']}/accounts", {"name": "Spare", "account_type": "checking", "balance": 1})
    assert "Spare" in await _accounts(client, sid)
    assert (await client.delete(f"/api/plans/{ids['plan']}/accounts/{spare['id']}")).status_code == 204
    assert "Spare" not in await _accounts(client, sid)


async def create_assumption(client, ids, sid):
    await post(client, f"/plans/{ids['plan']}/assumptions", {"curve_type": "market_return", "fixed_rate": 0.06})
    curves = {row["curve_type"]: row for row in (await _scenario(client, sid))["assumption_curves"]}
    assert curves["market_return"]["fixed_rate"] == 0.06


async def update_assumption(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}/assumptions/{ids['curve']}", {"fixed_rate": 0.031})
    assert (await _scenario(client, sid))["assumption_curves"][0]["fixed_rate"] == 0.031


async def delete_assumption(client, ids, sid):
    assert (await client.delete(f"/api/plans/{ids['plan']}/assumptions/{ids['curve']}")).status_code == 204
    assert (await _scenario(client, sid))["assumption_curves"] == []


async def _charities(client, sid):
    return {row["name"]: row for row in await get(client, f"/plans/{sid}/charities")}


async def create_charity(client, ids, sid):
    await post(client, f"/plans/{ids['plan']}/charities", {"name": "Library", "entity_type": "direct", "annual_amount": 250})
    assert (await _charities(client, sid))["Library"]["annual_amount"] == 250


async def update_charity(client, ids, sid):
    response = await client.patch(f"/api/plans/{ids['plan']}/charities/{ids['gift']}", json={"annual_amount": 1500})
    assert response.status_code == 200, response.text
    assert (await _charities(client, sid))["Food bank"]["annual_amount"] == 1500


async def delete_charity(client, ids, sid):
    assert (await client.delete(f"/api/plans/{ids['plan']}/charities/{ids['gift']}")).status_code == 204
    assert await _charities(client, sid) == {}


async def update_drawdown(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}/drawdown-order", {"items": [{"rank": 1, "source_account_id": ids["brokerage"]}]})
    brokerage = (await _accounts(client, sid))["Brokerage"]["id"]
    assert [row["source_account_id"] for row in (await _scenario(client, sid))["drawdown_order"]] == [brokerage]


async def create_expense(client, ids, sid):
    await post(client, f"/plans/{ids['plan']}/expenses", {"name": "Boat", "annual_amount": 9000, "start_milestone_id": ids["retire"]})
    scenario = await _scenario(client, sid)
    assert by_name(scenario["expenses"], "Boat")["start_milestone_id"] == by_name(scenario["milestones"], "Retire")["id"]


async def update_expense(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}/expenses/{ids['spending']}", {"annual_amount": 51000})
    assert by_name((await _scenario(client, sid))["expenses"], "Spending")["annual_amount"] == 51000


async def delete_expense(client, ids, sid):
    assert (await client.delete(f"/api/plans/{ids['plan']}/expenses/{ids['spending']}")).status_code == 204
    assert (await _scenario(client, sid))["expenses"] == []


async def create_income(client, ids, sid):
    await post(client, f"/plans/{ids['plan']}/incomes", {"name": "Pension", "annual_amount": 20000, "start_milestone_id": ids["retire"]})
    assert by_name((await _scenario(client, sid))["income_streams"], "Pension")["annual_amount"] == 20000


async def update_income(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}/incomes/{ids['salary']}", {"annual_amount": 126000})
    assert by_name((await _scenario(client, sid))["income_streams"], "Salary")["annual_amount"] == 126000


async def delete_income(client, ids, sid):
    assert (await client.delete(f"/api/plans/{ids['plan']}/incomes/{ids['salary']}")).status_code == 204
    assert (await _scenario(client, sid))["income_streams"] == []


async def create_liability(client, ids, sid):
    await post(client, f"/plans/{ids['plan']}/liabilities", {"name": "Car loan", "principal_balance": 15000, "interest_rate": 7, "term_months": 48})
    assert by_name((await _scenario(client, sid))["liabilities"], "Car loan")["principal_balance"] == 15000


async def update_liability(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}/liabilities/{ids['mortgage']}", {"principal_balance": 190000})
    assert by_name((await _scenario(client, sid))["liabilities"], "Mortgage")["principal_balance"] == 190000


async def delete_liability(client, ids, sid):
    assert (await client.delete(f"/api/plans/{ids['plan']}/liabilities/{ids['mortgage']}")).status_code == 204
    assert (await _scenario(client, sid))["liabilities"] == []


async def create_milestone(client, ids, sid):
    await post(client, f"/plans/{ids['plan']}/milestones", {"name": "Kids leave", "trigger_type": "age", "trigger_value": 52})
    assert by_name((await _scenario(client, sid))["milestones"], "Kids leave")["trigger_value"] == 52


async def update_milestone(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}/milestones/{ids['retire']}", {"trigger_value": 62})
    assert by_name((await _scenario(client, sid))["milestones"], "Retire")["trigger_value"] == 62


async def delete_milestone(client, ids, sid):
    extra = await post(client, f"/plans/{ids['plan']}/milestones", {"name": "Spare", "trigger_type": "age", "trigger_value": 70})
    assert "Spare" in {row["name"] for row in (await _scenario(client, sid))["milestones"]}
    assert (await client.delete(f"/api/plans/{ids['plan']}/milestones/{extra['id']}")).status_code == 204
    assert "Spare" not in {row["name"] for row in (await _scenario(client, sid))["milestones"]}


async def update_plan(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}", {"life_expectancy": 94, "residency_periods": [{"state_code": "FL", "rank": 0}]})
    scenario = await _scenario(client, sid)
    assert scenario["life_expectancy"] == 94
    assert [row["state_code"] for row in scenario["residency_periods"]] == ["FL"]


async def delete_plan(client, ids, sid):
    assert (await client.delete(f"/api/plans/{ids['plan']}")).status_code == 204
    scenario = await _scenario(client, sid)
    assert "parent_plan_id" not in scenario and scenario["life_expectancy"] == 92


async def apply_intake(client, ids, sid):
    response = await client.post(f"/api/plans/{ids['plan']}/intake", json={"retirement_age": 61, "retirement_spending": 60000})
    assert response.status_code == 200, response.text
    scenario = await _scenario(client, sid)
    retirement = {row["name"]: row for row in scenario["milestones"]}
    spending = {row["name"]: row for row in scenario["expenses"]}
    main = await get(client, f"/plans/{ids['plan']}")
    added = [row for row in main["expenses"] if row["name"] != "Spending"]
    assert added and spending[added[0]["name"]]["start_milestone_id"] in {row["id"] for row in retirement.values()}


async def update_priorities(client, ids, sid):
    revision = (await get(client, f"/plans/{ids['plan']}/priorities"))["revision"]
    await put(client, f"/plans/{ids['plan']}/priorities", {"expected_revision": revision, "items": [
        {"priority_rank": 1, "priority_type": "contribution", "target_account_id": ids["cash"]}]})
    cash = (await _accounts(client, sid))["Cash"]["id"]
    assert [row["target_account_id"] for row in (await _scenario(client, sid))["priorities"]] == [cash]


async def create_real_asset(client, ids, sid):
    await post(client, f"/plans/{ids['plan']}/real-assets", {"name": "Lot", "current_value": 50000})
    assert by_name((await _scenario(client, sid))["real_assets"], "Lot")["current_value"] == 50000


async def update_real_asset(client, ids, sid):
    await put(client, f"/plans/{ids['plan']}/real-assets/{ids['home']}", {"current_value": 410000})
    assert by_name((await _scenario(client, sid))["real_assets"], "Home")["current_value"] == 410000


async def delete_real_asset(client, ids, sid):
    lot = await post(client, f"/plans/{ids['plan']}/real-assets", {"name": "Lot", "current_value": 50000})
    assert "Lot" in {row["name"] for row in (await _scenario(client, sid))["real_assets"]}
    assert (await client.delete(f"/api/plans/{ids['plan']}/real-assets/{lot['id']}")).status_code == 204
    assert "Lot" not in {row["name"] for row in (await _scenario(client, sid))["real_assets"]}


async def apply_spending_model(client, ids, sid):
    groceries = await post(client, f"/plans/{ids['plan']}/expenses", {"name": "Groceries", "annual_amount": 12000, "category": "essential"})
    variant = {"kind": "amounts", "essential_annual": 18000, "discretionary_annual": 0}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("TRANSACTIONS_ENABLED", "true")
        preview = await post(client, f"/plans/{ids['plan']}/spending-models/compare", {"variants": [variant]}, 200)
        applied = await post(client, f"/plans/{ids['plan']}/spending-models/apply",
                             {"variant": variant, "expected_fingerprint": preview["fingerprint"]}, 200)
    assert applied["updated_expense_ids"] == [groceries["id"]]
    assert by_name((await _scenario(client, sid))["expenses"], "Groceries")["annual_amount"] == 18000


WRITES = {
    ("POST", "/api/accounts"): create_account_pool,
    ("PUT", "/api/accounts/{account_id}"): update_account_pool,
    ("DELETE", "/api/accounts/{account_id}"): delete_account_pool,
    ("POST", "/api/plans/{plan_id}/accounts"): create_account,
    ("PUT", "/api/plans/{plan_id}/accounts/{account_id}"): update_account,
    ("DELETE", "/api/plans/{plan_id}/accounts/{account_id}"): delete_account,
    ("POST", "/api/plans/{plan_id}/assumptions"): create_assumption,
    ("PUT", "/api/plans/{plan_id}/assumptions/{curve_id}"): update_assumption,
    ("DELETE", "/api/plans/{plan_id}/assumptions/{curve_id}"): delete_assumption,
    ("POST", "/api/plans/{plan_id}/charities"): create_charity,
    ("PATCH", "/api/plans/{plan_id}/charities/{charity_id}"): update_charity,
    ("DELETE", "/api/plans/{plan_id}/charities/{charity_id}"): delete_charity,
    ("PUT", "/api/plans/{plan_id}/drawdown-order"): update_drawdown,
    ("POST", "/api/plans/{plan_id}/expenses"): create_expense,
    ("PUT", "/api/plans/{plan_id}/expenses/{expense_id}"): update_expense,
    ("DELETE", "/api/plans/{plan_id}/expenses/{expense_id}"): delete_expense,
    ("POST", "/api/plans/{plan_id}/incomes"): create_income,
    ("PUT", "/api/plans/{plan_id}/incomes/{income_id}"): update_income,
    ("DELETE", "/api/plans/{plan_id}/incomes/{income_id}"): delete_income,
    ("POST", "/api/plans/{plan_id}/liabilities"): create_liability,
    ("PUT", "/api/plans/{plan_id}/liabilities/{liability_id}"): update_liability,
    ("DELETE", "/api/plans/{plan_id}/liabilities/{liability_id}"): delete_liability,
    ("POST", "/api/plans/{plan_id}/milestones"): create_milestone,
    ("PUT", "/api/plans/{plan_id}/milestones/{milestone_id}"): update_milestone,
    ("DELETE", "/api/plans/{plan_id}/milestones/{milestone_id}"): delete_milestone,
    ("PUT", "/api/plans/{plan_id}"): update_plan,
    ("DELETE", "/api/plans/{plan_id}"): delete_plan,
    ("POST", "/api/plans/{plan_id}/intake"): apply_intake,
    ("PUT", "/api/plans/{plan_id}/priorities"): update_priorities,
    ("POST", "/api/plans/{plan_id}/real-assets"): create_real_asset,
    ("PUT", "/api/plans/{plan_id}/real-assets/{real_asset_id}"): update_real_asset,
    ("DELETE", "/api/plans/{plan_id}/real-assets/{real_asset_id}"): delete_real_asset,
    ("POST", "/api/plans/{plan_id}/spending-models/apply"): apply_spending_model,
}

# Non-GET plan routes that change no input a scenario inherits.
NOT_INPUT_WRITES = {
    ("POST", "/api/plans/{plan_id}/simulate"): "projection only",
    ("POST", "/api/plans/{plan_id}/scenario-stress"): "projection only",
    ("POST", "/api/plans/{plan_id}/compare"): "projection only",
    ("POST", "/api/plans/{plan_id}/monte-carlo"): "projection only",
    ("POST", "/api/plans/{plan_id}/monte-carlo/trials/{index}"): "projection only",
    ("POST", "/api/plans/{plan_id}/tax-strategies/compare"): "analysis only",
    ("POST", "/api/plans/{plan_id}/tax-strategies/search"): "analysis only",
    ("POST", "/api/plans/{plan_id}/tax-suggestions"): "analysis only",
    ("POST", "/api/plans/{plan_id}/withdrawal-strategies/compare"): "analysis only",
    ("POST", "/api/plans/{plan_id}/spending-models/compare"): "analysis only",
    ("POST", "/api/plans/{plan_id}/plan-checks"): "analysis only",
    ("POST", "/api/plans/{plan_id}/social-security/claiming"): "analysis only",
    ("POST", "/api/plans/{plan_id}/wellness"): "analysis only",
    ("POST", "/api/plans/{plan_id}/duplicate"): "creates another plan; the source is unchanged",
    ("POST", "/api/plans/{plan_id}/archive"): "archive state (archived_at) is per plan, never inherited",
    ("POST", "/api/plans/{plan_id}/restore"): "archive state; restoring a scenario syncs it (test_plan_scenarios)",
    ("POST", "/api/plans/{plan_id}/edit-notice"): "edit-window state (edit notice) is per plan, never inherited",
    ("POST", "/api/plans/{plan_id}/inheritance/reset"): "writes the scenario itself (test_plan_scenarios)",
    ("POST", "/api/plans/{plan_id}/inheritance/restore"): "writes the scenario itself (test_plan_scenarios)",
    ("POST", "/api/plans/{plan_id}/inheritance/sync"): "writes the scenario itself (test_plan_scenarios)",
    ("POST", "/api/plans/{plan_id}/detach"): "writes the scenario itself (test_plan_scenarios)",
}


def _plan_write_routes() -> set[tuple[str, str]]:
    routes = set()
    for route in app.routes:
        methods = set(getattr(route, "methods", None) or ()) - {"GET", "HEAD", "OPTIONS"}
        path = getattr(route, "path", "")
        if path.startswith("/api/plans/{plan_id}") or path.startswith("/api/accounts"):
            routes |= {(method, path) for method in methods}
    return routes


def test_every_plan_write_route_has_a_decision():
    routes = _plan_write_routes()
    assert not set(WRITES) & set(NOT_INPUT_WRITES)
    undecided = routes - set(WRITES) - set(NOT_INPUT_WRITES)
    assert not undecided, f"add these routes to WRITES or NOT_INPUT_WRITES: {sorted(undecided)}"
    stale = (set(WRITES) | set(NOT_INPUT_WRITES)) - routes
    assert not stale, f"these routes no longer exist: {sorted(stale)}"


@pytest.mark.anyio
@pytest.mark.parametrize("route", sorted(WRITES), ids=lambda route: f"{route[0]} {route[1]}")
async def test_editing_main_through_route_reaches_scenario(route, client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"]))["id"]
    await WRITES[route](client, ids, sid)
    if route != ("DELETE", "/api/plans/{plan_id}"):
        inheritance = await get(client, f"/plans/{sid}/inheritance")
        assert inheritance["status"] == "ok", inheritance["skipped"]
        assert {row["state"] for row in inheritance["items"]} == {"inherited"}, inheritance["items"]
