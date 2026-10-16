"""Plan scenarios: creation, three-way sync, inheritance reads and changes."""
import uuid

import pytest

from app.models.plan import Plan
from app.models.plan_link import PlanLink
from app.scenarios import sync
from tests.scenario_support import (
    build_main,
    by_name,
    create_scenario,
    extra_workspace,
    get,
    item,
    post,
    put,
)


@pytest.mark.anyio
async def test_create_scenario_links_every_row_and_reads_inherited(client, db_session):
    ids = await build_main(client, db_session)
    main = await get(client, f"/plans/{ids['plan']}")
    assert "parent_plan_id" not in main
    scenario = await create_scenario(client, ids["plan"])
    assert scenario["parent_plan_id"] == ids["plan"]
    assert scenario["name"] == "Main (scenario)"
    assert scenario["client_id"] == ids["client"]
    sid = scenario["id"]
    # The scenario is a complete copy in its own IDs.
    assert by_name(scenario["milestones"], "Retire")["id"] != ids["retire"]
    assert (await get(client, f"/plans/{sid}"))["parent_plan_id"] == ids["plan"]
    summaries = {row["id"]: row for row in await get(client, "/plans/summaries")}
    assert summaries[sid]["parent_plan_id"] == ids["plan"]
    assert "parent_plan_id" not in summaries[ids["plan"]]
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert inheritance["parent_plan_id"] == ids["plan"] and inheritance["parent_name"] == "Main"
    assert inheritance["status"] == "ok" and inheritance["skipped"] == [] and inheritance["plan_fields"] == []
    states = {(row["kind"], row["name"]): row["state"] for row in inheritance["items"]}
    assert set(states.values()) == {"inherited"}
    assert {kind for kind, _name in states} == {
        "spouse", "milestone", "income", "expense", "account", "real_asset", "liability", "assumption_curve",
        "charity", "priorities", "drawdown", "residency"}
    assert states[("priorities", "Savings rules")] == "inherited"
    # A plan that is not a scenario reads as empty.
    plain = await get(client, f"/plans/{ids['plan']}/inheritance")
    assert plain == {"plan_id": ids["plan"], "parent_plan_id": None, "parent_name": None, "status": "ok",
                     "synced_at": None, "plan_fields": [], "items": [], "skipped": []}


@pytest.mark.anyio
async def test_main_edits_flow_into_scenario_except_overrides(client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"], "Retire early"))["id"]
    scenario = await get(client, f"/plans/{sid}")
    assert scenario["name"] == "Retire early"
    s_salary = by_name(scenario["income_streams"], "Salary")["id"]
    s_spending = by_name(scenario["expenses"], "Spending")["id"]
    # Scenario overrides the salary amount and its life expectancy.
    await put(client, f"/plans/{sid}/incomes/{s_salary}", {"annual_amount": 90000})
    await put(client, f"/plans/{sid}", {"life_expectancy": 88})
    # Main changes the salary amount and growth, spending, and life expectancy.
    await put(client, f"/plans/{ids['plan']}/incomes/{ids['salary']}", {"annual_amount": 130000, "growth_rate": 0.03})
    await put(client, f"/plans/{ids['plan']}/expenses/{ids['spending']}", {"annual_amount": 50000})
    await put(client, f"/plans/{ids['plan']}", {"life_expectancy": 97, "state_code": "WA"})
    scenario = await get(client, f"/plans/{sid}")
    salary = by_name(scenario["income_streams"], "Salary")
    assert salary["annual_amount"] == 90000  # override kept
    assert salary["growth_rate"] == 0.03  # inherited field follows
    assert by_name(scenario["expenses"], "Spending")["annual_amount"] == 50000
    assert scenario["life_expectancy"] == 88 and scenario["state_code"] == "WA"
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert inheritance["plan_fields"] == [{"field": "life_expectancy", "value": 88, "parent_value": 97}]
    row = item(inheritance, "income", "Salary")
    assert row["state"] == "changed" and row["row_id"] == s_salary and row["parent_row_id"] == ids["salary"]
    assert row["fields"] == [{"field": "annual_amount", "value": 90000, "parent_value": 130000}]
    assert item(inheritance, "expense", "Spending")["state"] == "inherited"
    # Setting the value back to Main's makes it inherited again.
    await put(client, f"/plans/{sid}/incomes/{s_salary}", {"annual_amount": 130000})
    await put(client, f"/plans/{ids['plan']}/incomes/{ids['salary']}", {"annual_amount": 140000})
    assert by_name((await get(client, f"/plans/{sid}"))["income_streams"], "Salary")["annual_amount"] == 140000
    # Saves on a scenario never change Main.
    await put(client, f"/plans/{sid}/expenses/{s_spending}", {"annual_amount": 1})
    assert by_name((await get(client, f"/plans/{ids['plan']}"))["expenses"], "Spending")["annual_amount"] == 50000


@pytest.mark.anyio
async def test_decimal_values_never_read_as_overrides(client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"]))["id"]
    # Re-saving the same amounts (as floats) on both sides changes nothing.
    s_brokerage = by_name(await get(client, f"/plans/{sid}/accounts"), "Brokerage")["id"]
    await put(client, f"/plans/{sid}/accounts/{s_brokerage}", {"balance": 150000.1})
    await put(client, f"/plans/{ids['plan']}/accounts/{ids['brokerage']}", {"balance": 150000.10, "cost_basis": 90000.0})
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert {row["state"] for row in inheritance["items"]} == {"inherited"}
    await put(client, f"/plans/{ids['plan']}/accounts/{ids['brokerage']}", {"balance": 175000.25})
    accounts = await get(client, f"/plans/{sid}/accounts")
    assert by_name(accounts, "Brokerage")["balance"] == 175000.25
    links = db_session.query(PlanLink).filter(PlanLink.scenario_plan_id == uuid.UUID(sid), PlanLink.kind == "account").all()
    stored = {link.base["name"]: link.base for link in links}
    assert stored["Brokerage"]["balance"] == "175000.25" and stored["Brokerage"]["cost_basis"] == "90000"


@pytest.mark.anyio
async def test_new_main_rows_with_cross_references_are_created(client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"]))["id"]
    pid = ids["plan"]
    move = await post(client, f"/plans/{pid}/milestones", {"name": "Move", "trigger_type": "age", "trigger_value": 55})
    later = await post(client, f"/plans/{pid}/milestones", {
        "name": "After move", "trigger_type": "relative", "relative_to_id": move["id"], "offset_years": 3})
    car = await post(client, f"/plans/{pid}/expenses", {"name": "New car", "annual_amount": 30000,
                                                         "frequency": "once", "start_milestone_id": move["id"]})
    cabin = await post(client, f"/plans/{pid}/real-assets", {"name": "Cabin", "current_value": 250000})
    await post(client, f"/plans/{pid}/liabilities", {"name": "Cabin loan", "principal_balance": 100000,
                                                     "interest_rate": 6, "term_months": 120, "linked_asset_id": cabin["id"]})
    hsa = await post(client, f"/plans/{pid}/accounts", {"name": "HSA", "account_type": "hsa", "balance": 5000})
    revision = (await get(client, f"/plans/{pid}/priorities"))["revision"]
    await put(client, f"/plans/{pid}/priorities", {"expected_revision": revision, "items": [
        {"priority_rank": 1, "priority_type": "contribution", "target_account_id": hsa["id"],
         "allocation_mode": "amount", "allocation_value": 1000}]})
    scenario = await get(client, f"/plans/{sid}")
    s_move = by_name(scenario["milestones"], "Move")
    assert s_move["id"] != move["id"]
    assert by_name(scenario["milestones"], "After move")["relative_to_id"] == s_move["id"]
    assert by_name(scenario["expenses"], "New car")["start_milestone_id"] == s_move["id"]
    s_cabin = by_name(scenario["real_assets"], "Cabin")
    assert by_name(scenario["liabilities"], "Cabin loan")["linked_asset_id"] == s_cabin["id"]
    s_hsa = by_name(await get(client, f"/plans/{sid}/accounts"), "HSA")
    assert [row["target_account_id"] for row in scenario["priorities"]] == [s_hsa["id"]]
    # Replacing the inherited allocation bumped the scenario's revision.
    assert scenario["priorities_revision"] == 1
    assert later["id"] not in {row["id"] for row in scenario["milestones"]}
    assert car["id"] not in {row["id"] for row in scenario["expenses"]}
    # The new rows are linked: Main's next change flows in.
    await put(client, f"/plans/{pid}/expenses/{car['id']}", {"annual_amount": 35000})
    assert by_name((await get(client, f"/plans/{sid}"))["expenses"], "New car")["annual_amount"] == 35000


@pytest.mark.anyio
async def test_main_deletes_unmodified_modified_and_referenced_rows(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    extra = await post(client, f"/plans/{pid}/incomes", {"name": "Side gig", "annual_amount": 5000})
    bonus = await post(client, f"/plans/{pid}/incomes", {"name": "Bonus", "annual_amount": 7000})
    sabbatical = await post(client, f"/plans/{pid}/milestones", {"name": "Sabbatical", "trigger_type": "age", "trigger_value": 50})
    sid = (await create_scenario(client, pid))["id"]
    scenario = await get(client, f"/plans/{sid}")
    s_bonus = by_name(scenario["income_streams"], "Bonus")["id"]
    s_sabbatical = by_name(scenario["milestones"], "Sabbatical")["id"]
    await put(client, f"/plans/{sid}/incomes/{s_bonus}", {"annual_amount": 9000})
    # The scenario's own expense uses the milestone Main is about to delete.
    await post(client, f"/plans/{sid}/expenses", {"name": "Trip", "annual_amount": 8000, "start_milestone_id": s_sabbatical})
    reasons = {}
    for path in (f"incomes/{extra['id']}", f"incomes/{bonus['id']}", f"milestones/{sabbatical['id']}"):
        assert (await client.delete(f"/api/plans/{pid}/{path}")).status_code == 204
        # Each sync explains the rows it kept.
        reasons.update({row["name"]: row["reason"] for row in (await get(client, f"/plans/{sid}/inheritance"))["skipped"]})
    scenario = await get(client, f"/plans/{sid}")
    names = {row["name"] for row in scenario["income_streams"]}
    assert "Side gig" not in names  # unmodified: deleted
    assert "Bonus" in names  # modified: kept as the scenario's own
    assert by_name(scenario["milestones"], "Sabbatical")["id"] == s_sabbatical  # referenced: kept
    assert by_name(scenario["expenses"], "Trip")["start_milestone_id"] == s_sabbatical
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert item(inheritance, "income", "Bonus")["state"] == "scenario_only"
    assert item(inheritance, "milestone", "Sabbatical")["state"] == "scenario_only"
    assert inheritance["status"] == "needs_review"
    assert set(reasons) == {"Bonus", "Sabbatical"}
    assert "changed it" in reasons["Bonus"] and "uses it" in reasons["Sabbatical"]


@pytest.mark.anyio
async def test_removed_rows_ignore_main_until_restored(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    scenario = await get(client, f"/plans/{sid}")
    s_mortgage = by_name(scenario["liabilities"], "Mortgage")["id"]
    assert (await client.delete(f"/api/plans/{sid}/liabilities/{s_mortgage}")).status_code == 204
    await put(client, f"/plans/{pid}/liabilities/{ids['mortgage']}", {"principal_balance": 180000})
    assert (await get(client, f"/plans/{sid}"))["liabilities"] == []
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    removed = item(inheritance, "liability", "Mortgage")
    assert removed == {"kind": "liability", "row_id": None, "parent_row_id": ids["mortgage"], "name": "Mortgage",
                       "state": "removed", "fields": []}
    restored = await post(client, f"/plans/{sid}/inheritance/restore",
                          {"kind": "liability", "parent_row_id": ids["mortgage"]}, status=200)
    assert item(restored, "liability", "Mortgage")["state"] == "inherited"
    liability = by_name((await get(client, f"/plans/{sid}"))["liabilities"], "Mortgage")
    assert liability["principal_balance"] == 180000
    assert liability["linked_asset_id"] == by_name((await get(client, f"/plans/{sid}"))["real_assets"], "Home")["id"]
    # Restoring something that is not removed is refused.
    response = await client.post(f"/api/plans/{sid}/inheritance/restore",
                                 json={"kind": "liability", "parent_row_id": ids["mortgage"]})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_unmappable_reference_is_skipped_retried_and_restore_needs_dependency(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    scenario = await get(client, f"/plans/{sid}")
    s_before = by_name(scenario["milestones"], "Before retiring")["id"]
    s_spending = by_name(scenario["expenses"], "Spending")["id"]
    move = await post(client, f"/plans/{pid}/milestones", {"name": "Move abroad", "trigger_type": "age", "trigger_value": 58})
    s_move = by_name((await get(client, f"/plans/{sid}"))["milestones"], "Move abroad")["id"]
    assert (await client.delete(f"/api/plans/{sid}/milestones/{s_move}")).status_code == 204
    # Main points spending at the milestone the scenario removed, and adds a new expense using it.
    await put(client, f"/plans/{pid}/expenses/{ids['spending']}", {"end_milestone_id": move["id"]})
    await post(client, f"/plans/{pid}/expenses", {"name": "Moving costs", "annual_amount": 20000,
                                                 "frequency": "once", "start_milestone_id": move["id"]})
    scenario = await get(client, f"/plans/{sid}")
    assert by_name(scenario["expenses"], "Spending")["end_milestone_id"] == s_before  # unchanged, retried later
    assert "Moving costs" not in {row["name"] for row in scenario["expenses"]}
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert inheritance["status"] == "needs_review"
    skipped = {(row["name"], row["field"]) for row in inheritance["skipped"]}
    assert ("Spending", "end_milestone_id") in skipped and ("Moving costs", "start_milestone_id") in skipped
    assert all("Move abroad" in row["reason"] for row in inheritance["skipped"])
    # Restoring the expense first is refused with the dependency's name.
    moving = await get(client, f"/plans/{pid}")
    moving_id = by_name(moving["expenses"], "Moving costs")["id"]
    response = await client.post(f"/api/plans/{sid}/inheritance/restore",
                                 json={"kind": "expense", "parent_row_id": moving_id})
    assert response.status_code == 422
    restored = await post(client, f"/plans/{sid}/inheritance/restore",
                          {"kind": "milestone", "parent_row_id": move["id"]}, status=200)
    assert restored["status"] == "ok" and restored["skipped"] == []
    scenario = await get(client, f"/plans/{sid}")
    s_move = by_name(scenario["milestones"], "Move abroad")["id"]
    assert by_name(scenario["expenses"], "Spending")["end_milestone_id"] == s_move
    assert by_name(scenario["expenses"], "Moving costs")["start_milestone_id"] == s_move
    assert by_name(scenario["expenses"], "Spending")["id"] == s_spending


@pytest.mark.anyio
async def test_whole_lists_follow_main_unless_changed(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    s_accounts = {row["name"]: row["id"] for row in await get(client, f"/plans/{sid}/accounts")}
    # The scenario reorders withdrawals; Main changes its order and residency.
    await put(client, f"/plans/{sid}/drawdown-order", {"items": [
        {"rank": 1, "source_account_id": s_accounts["Brokerage"]}, {"rank": 2, "source_account_id": s_accounts["Cash"]}]})
    await put(client, f"/plans/{pid}/drawdown-order", {"items": [{"rank": 1, "source_account_id": ids["cash"]}]})
    await put(client, f"/plans/{pid}", {"residency_periods": [{"state_code": "NV", "rank": 0}]})
    scenario = await get(client, f"/plans/{sid}")
    assert [row["source_account_id"] for row in scenario["drawdown_order"]] == [s_accounts["Brokerage"], s_accounts["Cash"]]
    assert [row["state_code"] for row in scenario["residency_periods"]] == ["NV"]
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert item(inheritance, "drawdown")["state"] == "changed"
    assert item(inheritance, "residency")["state"] == "inherited"
    reset = await post(client, f"/plans/{sid}/inheritance/reset", {"kind": "drawdown"}, status=200)
    assert item(reset, "drawdown")["state"] == "inherited"
    assert [row["source_account_id"] for row in (await get(client, f"/plans/{sid}"))["drawdown_order"]] == [s_accounts["Cash"]]


@pytest.mark.anyio
async def test_spouse_added_by_main_and_kept_removed_by_scenario(client, db_session):
    household = await post(client, "/clients/personal", status=200)
    pid = (await post(client, "/plans", {"name": "Main", "birth_year": 1985, "client_id": household["id"]}))["id"]
    first = (await create_scenario(client, pid, "Keeps partner"))["id"]
    await put(client, f"/plans/{pid}", {"spouse": {"name": "Ana", "birth_year": 1986}})
    assert (await get(client, f"/plans/{first}"))["spouse"]["name"] == "Ana"
    assert (await put(client, f"/plans/{first}", {"spouse": None}))["spouse"] is None
    await put(client, f"/plans/{pid}", {"spouse": {"name": "Ana", "birth_year": 1987}})
    assert (await get(client, f"/plans/{first}"))["spouse"] is None
    assert item(await get(client, f"/plans/{first}/inheritance"), "spouse")["state"] == "removed"
    # Main removing an unchanged partner removes it from the scenario.
    second = (await create_scenario(client, pid, "Second"))["id"]
    await put(client, f"/plans/{pid}", {"spouse": None})
    assert (await get(client, f"/plans/{second}"))["spouse"] is None


@pytest.mark.anyio
async def test_reset_row_plan_field_and_priorities_revision(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    scenario = await get(client, f"/plans/{sid}")
    s_salary = by_name(scenario["income_streams"], "Salary")["id"]
    s_brokerage = by_name(await get(client, f"/plans/{sid}/accounts"), "Brokerage")["id"]
    await put(client, f"/plans/{sid}/incomes/{s_salary}", {"annual_amount": 1, "growth_rate": 0.05})
    await put(client, f"/plans/{sid}", {"life_expectancy": 80, "state_code": "OR"})
    revision = (await get(client, f"/plans/{sid}/priorities"))["revision"]
    await put(client, f"/plans/{sid}/priorities", {"expected_revision": revision, "items": [
        {"priority_rank": 1, "priority_type": "contribution", "target_account_id": s_brokerage}]})
    result = await post(client, f"/plans/{sid}/inheritance/reset",
                        {"kind": "income", "row_id": s_salary, "fields": ["annual_amount"]}, status=200)
    assert item(result, "income", "Salary")["fields"] == [{"field": "growth_rate", "value": 0.05, "parent_value": None}]
    result = await post(client, f"/plans/{sid}/inheritance/reset", {"kind": "income", "row_id": s_salary}, status=200)
    assert item(result, "income", "Salary")["state"] == "inherited"
    result = await post(client, f"/plans/{sid}/inheritance/reset", {"kind": "plan", "fields": ["life_expectancy"]}, status=200)
    assert result["plan_fields"] == [{"field": "state_code", "value": "OR", "parent_value": None}]
    assert (await get(client, f"/plans/{sid}"))["life_expectancy"] == 92
    # Not inheritable, scenario-only rows and unknown kinds are refused.
    for payload in ({"kind": "plan", "fields": ["name"]}, {"kind": "income", "row_id": s_salary, "fields": ["plan_id"]},
                    {"kind": "income", "row_id": str(uuid.uuid4())}, {"kind": "budget"}, {"kind": "priorities"}):
        response = await client.post(f"/api/plans/{sid}/inheritance/reset", json=payload)
        assert response.status_code == 422, payload
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    current = (await get(client, f"/plans/{sid}/priorities"))["revision"]
    stale = await client.post(f"/api/plans/{sid}/inheritance/reset", json={"kind": "priorities", "expected_revision": current - 1})
    assert stale.status_code == 409
    assert stale.json()["error"]["details"][0]["field"] == "expected_revision"
    assert (await get(client, f"/plans/{sid}/priorities"))["revision"] == current
    result = await post(client, f"/plans/{sid}/inheritance/reset", {"kind": "priorities", "expected_revision": current}, status=200)
    assert item(result, "priorities")["state"] == "inherited"
    priorities = await get(client, f"/plans/{sid}/priorities")
    assert priorities["revision"] == current + 1
    assert [row["allocation_value"] for row in priorities["items"]] == [5000]


@pytest.mark.anyio
async def test_creation_validation_and_plain_duplicates(client, db_session, test_user):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    response = await client.post(f"/api/plans/{sid}/duplicate", json={"as_scenario": True})
    assert response.status_code == 422 and "Main" in response.json()["error"]["message"]
    other_client = extra_workspace(db_session, test_user.id, "Other")
    response = await client.post(f"/api/plans/{pid}/duplicate", json={"as_scenario": True, "client_id": other_client["id"]})
    assert response.status_code == 422
    legacy = await post(client, "/plans", {"name": "Legacy", "birth_year": 1980})
    response = await client.post(f"/api/plans/{legacy['id']}/duplicate", json={"as_scenario": True})
    assert response.status_code == 422
    archived = await post(client, "/plans", {"name": "Old", "birth_year": 1980, "client_id": ids["client"]})
    await post(client, f"/plans/{archived['id']}/archive", status=200)
    response = await client.post(f"/api/plans/{archived['id']}/duplicate", json={"as_scenario": True})
    assert response.status_code == 422
    response = await client.post(f"/api/plans/{pid}/duplicate", json={"as_scenario": True, "name": ""})
    assert response.status_code == 422
    # A plain duplicate of a scenario is independent; a named copy keeps its name.
    copy = await post(client, f"/plans/{sid}/duplicate", {"name": "Snapshot"})
    assert copy["name"] == "Snapshot" and "parent_plan_id" not in copy
    assert db_session.get(Plan, uuid.UUID(copy["id"])).scenario_sync is None
    await put(client, f"/plans/{pid}", {"life_expectancy": 99})
    assert (await get(client, f"/plans/{copy['id']}"))["life_expectancy"] == 92
    assert (await get(client, f"/plans/{sid}"))["life_expectancy"] == 99
    assert (await post(client, f"/plans/{pid}/duplicate"))["name"] == "Main (copy)"
    # Plans cannot be re-parented through the update body.
    await put(client, f"/plans/{copy['id']}", {"parent_plan_id": pid})
    assert db_session.get(Plan, uuid.UUID(copy["id"])).parent_plan_id is None
    response = await client.post(f"/api/plans/{pid}/inheritance/reset", json={"kind": "plan"})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_detach_and_delete_main_leave_independent_plans(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    first = (await create_scenario(client, pid, "First"))["id"]
    second = (await create_scenario(client, pid, "Second"))["id"]
    await put(client, f"/plans/{first}", {"life_expectancy": 85})
    detached = await post(client, f"/plans/{first}/detach", status=200)
    assert "parent_plan_id" not in detached and detached["life_expectancy"] == 85
    assert await post(client, f"/plans/{first}/detach", status=200) == detached
    assert db_session.query(PlanLink).filter(PlanLink.scenario_plan_id == uuid.UUID(first)).count() == 0
    await put(client, f"/plans/{pid}", {"life_expectancy": 100})
    assert (await get(client, f"/plans/{first}"))["life_expectancy"] == 85
    assert (await get(client, f"/plans/{second}"))["life_expectancy"] == 100
    assert (await client.delete(f"/api/plans/{pid}")).status_code == 204
    kept = await get(client, f"/plans/{second}")
    assert "parent_plan_id" not in kept and kept["life_expectancy"] == 100
    assert len(kept["income_streams"]) == 1
    assert db_session.query(PlanLink).count() == 0
    assert (await get(client, f"/plans/{second}/inheritance"))["parent_plan_id"] is None


@pytest.mark.anyio
async def test_archived_scenario_skipped_then_synced_on_restore(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    await post(client, f"/plans/{sid}/archive", status=200)
    await put(client, f"/plans/{pid}", {"life_expectancy": 101})
    assert (await get(client, f"/plans/{sid}"))["life_expectancy"] == 92
    restored = await post(client, f"/plans/{sid}/restore", status=200)
    assert restored["life_expectancy"] == 101
    response = await client.post(f"/api/plans/{sid}/inheritance/sync")
    assert response.status_code == 200 and response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_scenario_simulates_like_an_equivalent_duplicate(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    await put(client, f"/plans/{pid}/incomes/{ids['salary']}", {"annual_amount": 135000})
    await post(client, f"/plans/{pid}/expenses", {"name": "Travel", "annual_amount": 6000})
    copy = (await post(client, f"/plans/{pid}/duplicate"))["id"]
    headers = {"X-Client-Date": "2026-09-07"}
    scenario_run = await client.post(f"/api/plans/{sid}/simulate", headers=headers)
    copy_run = await client.post(f"/api/plans/{copy}/simulate", headers=headers)
    assert scenario_run.status_code == 200 and copy_run.status_code == 200
    for a, b in zip(scenario_run.json()["yearly_snapshots"], copy_run.json()["yearly_snapshots"], strict=True):
        for key in ("year", "net_worth", "gross_income", "expenses", "taxes", "net_cash_flow"):
            assert a[key] == b[key], (a["year"], key)


@pytest.mark.anyio
async def test_sync_is_idempotent_and_other_users_get_404(client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"]))["id"]
    await put(client, f"/plans/{ids['plan']}/incomes/{ids['salary']}", {"annual_amount": 125000})
    before = await get(client, f"/plans/{sid}")
    first = await post(client, f"/plans/{sid}/inheritance/sync", status=200)
    second = await post(client, f"/plans/{sid}/inheritance/sync", status=200)
    assert (await get(client, f"/plans/{sid}")) == before
    assert {k: v for k, v in first.items() if k != "synced_at"} == {k: v for k, v in second.items() if k != "synced_at"}
    for path in ("/inheritance",):
        assert (await client.get(f"/api/plans/{uuid.uuid4()}{path}")).status_code == 404
    response = await client.post(f"/api/plans/{uuid.uuid4()}/detach")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_merge_that_breaks_projection_rules_needs_review(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    await put(client, f"/plans/{sid}", {"birth_year": 1960})
    # Fine for Main (born 1985); the scenario's own birth year ends it before it starts.
    await put(client, f"/plans/{pid}", {"life_expectancy": 60})
    assert (await get(client, f"/plans/{sid}"))["life_expectancy"] == 60
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert inheritance["status"] == "needs_review"
    review = [row for row in inheritance["skipped"] if row["kind"] == "plan"]
    assert len(review) == 1 and "Life expectancy" in review[0]["reason"] and review[0]["field"] is None
    await put(client, f"/plans/{pid}", {"life_expectancy": 95})
    assert (await get(client, f"/plans/{sid}/inheritance"))["status"] == "ok"


@pytest.mark.anyio
async def test_failing_scenario_rolls_back_alone_and_main_still_saves(client, db_session, monkeypatch):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    broken = (await create_scenario(client, pid, "Broken"))["id"]
    healthy = (await create_scenario(client, pid, "Healthy"))["id"]
    record = sync._Sync.record

    def fail_after_writes(self, names):
        if str(self.scenario.id) == broken:
            raise RuntimeError("injected")
        return record(self, names)

    monkeypatch.setattr(sync._Sync, "record", fail_after_writes)
    await put(client, f"/plans/{pid}/incomes/{ids['salary']}", {"annual_amount": 150000})
    await put(client, f"/plans/{pid}", {"life_expectancy": 90})
    monkeypatch.setattr(sync._Sync, "record", record)
    salary = lambda plan: by_name(plan["income_streams"], "Salary")["annual_amount"]  # noqa: E731
    assert salary(await get(client, f"/plans/{pid}")) == 150000
    assert salary(await get(client, f"/plans/{healthy}")) == 150000
    assert (await get(client, f"/plans/{healthy}"))["life_expectancy"] == 90
    # The broken scenario's partial writes were rolled back with its savepoint.
    assert salary(await get(client, f"/plans/{broken}")) == 120000
    inheritance = await get(client, f"/plans/{broken}/inheritance")
    assert inheritance["status"] == "needs_review"
    assert any("Sync now" in row["reason"] for row in inheritance["skipped"])
    synced = await post(client, f"/plans/{broken}/inheritance/sync", status=200)
    assert synced["status"] == "ok" and synced["skipped"] == []
    assert salary(await get(client, f"/plans/{broken}")) == 150000
    assert (await get(client, f"/plans/{broken}"))["life_expectancy"] == 90


def _scenario_sync(db_session, sid):
    db_session.expire_all()
    return db_session.get(Plan, uuid.UUID(sid)).scenario_sync


@pytest.mark.anyio
async def test_completed_sync_clears_an_earlier_failure_even_when_it_writes_nothing(client, db_session, monkeypatch):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid, "Broken"))["id"]
    s_salary = by_name((await get(client, f"/plans/{sid}"))["income_streams"], "Salary")["id"]
    # The scenario overrides the salary amount, so Main's later amount edits write nothing to it.
    await put(client, f"/plans/{sid}/incomes/{s_salary}", {"annual_amount": 90000})
    record = sync._Sync.record

    def fail(self, names):
        if str(self.scenario.id) == sid:
            raise RuntimeError("injected")
        return record(self, names)

    monkeypatch.setattr(sync._Sync, "record", fail)
    await put(client, f"/plans/{pid}/incomes/{ids['salary']}", {"annual_amount": 150000})
    monkeypatch.setattr(sync._Sync, "record", record)
    assert "Sync now" in _scenario_sync(db_session, sid)["failed"]
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert inheritance["status"] == "needs_review"
    (failed,) = inheritance["skipped"]
    assert (failed["kind"], failed["parent_row_id"], failed["name"], failed["field"]) == ("plan", pid, "Broken", None)
    assert "Sync now" in failed["reason"]
    # The next completed sync merges nothing new but still clears the failure.
    await put(client, f"/plans/{pid}/incomes/{ids['salary']}", {"annual_amount": 160000})
    assert by_name((await get(client, f"/plans/{sid}"))["income_streams"], "Salary")["annual_amount"] == 90000
    assert "failed" not in _scenario_sync(db_session, sid)
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert inheritance["status"] == "ok" and inheritance["skipped"] == []


@pytest.mark.anyio
async def test_review_problem_survives_a_sync_that_writes_nothing(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    s_salary = by_name((await get(client, f"/plans/{sid}"))["income_streams"], "Salary")["id"]
    await put(client, f"/plans/{sid}/incomes/{s_salary}", {"annual_amount": 90000})
    await put(client, f"/plans/{sid}", {"birth_year": 1960})
    await put(client, f"/plans/{pid}", {"life_expectancy": 60})
    review = _scenario_sync(db_session, sid)["review"]
    assert "Life expectancy" in review
    # A Main edit the scenario overrides writes nothing and keeps the review.
    await put(client, f"/plans/{pid}/incomes/{ids['salary']}", {"annual_amount": 150000})
    assert _scenario_sync(db_session, sid)["review"] == review
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert inheritance["status"] == "needs_review"
    assert [row["reason"] for row in inheritance["skipped"] if row["kind"] == "plan"] == [review]


@pytest.mark.anyio
async def test_main_milestone_delete_waits_until_references_move(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sabbatical = await post(client, f"/plans/{pid}/milestones", {"name": "Sabbatical", "trigger_type": "age", "trigger_value": 50})
    await put(client, f"/plans/{pid}/incomes/{ids['salary']}", {"start_milestone_id": sabbatical["id"]})
    revision = (await get(client, f"/plans/{pid}/priorities"))["revision"]
    await put(client, f"/plans/{pid}/priorities", {"expected_revision": revision, "items": [
        {"priority_rank": 1, "priority_type": "contribution", "target_account_id": ids["brokerage"],
         "start_milestone_id": sabbatical["id"]}]})
    sid = (await create_scenario(client, pid))["id"]
    # Deleting would clear Main's references silently, so it is refused first.
    blocked = await client.delete(f"/api/plans/{pid}/milestones/{sabbatical['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["message"].startswith("Salary and Brokerage allocation use this milestone.")
    await put(client, f"/plans/{pid}/incomes/{ids['salary']}", {"start_milestone_id": None})
    revision = (await get(client, f"/plans/{pid}/priorities"))["revision"]
    await put(client, f"/plans/{pid}/priorities", {"expected_revision": revision, "items": [
        {"priority_rank": 1, "priority_type": "contribution", "target_account_id": ids["brokerage"]}]})
    assert (await client.delete(f"/api/plans/{pid}/milestones/{sabbatical['id']}")).status_code == 204
    scenario = await get(client, f"/plans/{sid}")
    assert "Sabbatical" not in {row["name"] for row in scenario["milestones"]}
    assert by_name(scenario["income_streams"], "Salary")["start_milestone_id"] is None
    assert scenario["priorities"][0]["start_milestone_id"] is None
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert inheritance["status"] == "ok" and {row["state"] for row in inheritance["items"]} == {"inherited"}
