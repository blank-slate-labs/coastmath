"""Scenario resets and restores refuse what would leave a dangling or duplicate row."""
import pytest

from app.models.plan_link import PlanLink
from app.scenarios.registry import PLAN_KIND
from tests.scenario_support import (
    build_main,
    by_name,
    create_scenario,
    get,
    item,
    post,
    put,
)


async def _refused(client, sid, action, payload, message):
    response = await client.post(f"/api/plans/{sid}/inheritance/{action}", json=payload)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert message in error["message"]


async def _removed_milestone(client, ids, sid):
    """Main adds "Move abroad"; the scenario removes its copy. Returns Main's id."""
    move = await post(client, f"/plans/{ids['plan']}/milestones",
                      {"name": "Move abroad", "trigger_type": "age", "trigger_value": 58})
    s_move = by_name((await get(client, f"/plans/{sid}"))["milestones"], "Move abroad")["id"]
    assert (await client.delete(f"/api/plans/{sid}/milestones/{s_move}")).status_code == 204
    return move["id"]


@pytest.mark.anyio
async def test_reset_naming_a_row_the_scenario_removed_asks_for_its_restore(client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"]))["id"]
    move = await _removed_milestone(client, ids, sid)
    await put(client, f"/plans/{ids['plan']}/incomes/{ids['salary']}", {"end_milestone_id": move})
    s_salary = by_name((await get(client, f"/plans/{sid}"))["income_streams"], "Salary")
    await _refused(client, sid, "reset", {"kind": "income", "row_id": s_salary["id"], "fields": ["end_milestone_id"]},
                   "Restore the milestone “Move abroad” first.")
    # Nothing changed: the salary still ends at the scenario's own retirement milestone.
    after = by_name((await get(client, f"/plans/{sid}"))["income_streams"], "Salary")
    assert after["end_milestone_id"] == s_salary["end_milestone_id"]


@pytest.mark.anyio
async def test_reset_of_a_list_that_names_a_removed_account_is_refused(client, db_session):
    ids = await build_main(client, db_session)
    pid = ids["plan"]
    sid = (await create_scenario(client, pid))["id"]
    hsa = await post(client, f"/plans/{pid}/accounts", {"name": "HSA", "account_type": "hsa", "balance": 5000})
    s_hsa = by_name(await get(client, f"/plans/{sid}/accounts"), "HSA")["id"]
    assert (await client.delete(f"/api/plans/{sid}/accounts/{s_hsa}")).status_code == 204
    await put(client, f"/plans/{pid}/drawdown-order", {"items": [
        {"rank": 1, "source_account_id": ids["cash"]}, {"rank": 2, "source_account_id": hsa["id"]}]})
    await _refused(client, sid, "reset", {"kind": "drawdown"}, "Restore the account “HSA” first.")
    # Restoring the account (an owned row) brings it back and the reset then applies.
    restored = await post(client, f"/plans/{sid}/inheritance/restore",
                          {"kind": "account", "parent_row_id": hsa["id"]}, status=200)
    assert item(restored, "account", "HSA")["state"] == "inherited"
    s_hsa = by_name(await get(client, f"/plans/{sid}/accounts"), "HSA")["id"]
    await post(client, f"/plans/{sid}/inheritance/reset", {"kind": "drawdown"}, status=200)
    s_cash = by_name(await get(client, f"/plans/{sid}/accounts"), "Cash")["id"]
    order = (await get(client, f"/plans/{sid}"))["drawdown_order"]
    assert [row["source_account_id"] for row in order] == [s_cash, s_hsa]


@pytest.mark.anyio
async def test_restoring_a_row_whose_reference_was_removed_names_the_dependency(client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"]))["id"]
    move = await _removed_milestone(client, ids, sid)
    s_salary = by_name((await get(client, f"/plans/{sid}"))["income_streams"], "Salary")["id"]
    assert (await client.delete(f"/api/plans/{sid}/incomes/{s_salary}")).status_code == 204
    await put(client, f"/plans/{ids['plan']}/incomes/{ids['salary']}", {"end_milestone_id": move})
    await _refused(client, sid, "restore", {"kind": "income", "parent_row_id": ids["salary"]},
                   "Restore the milestone “Move abroad” first.")
    assert (await get(client, f"/plans/{sid}"))["income_streams"] == []


@pytest.mark.anyio
async def test_whole_list_kinds_cannot_be_restored(client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"]))["id"]
    await _refused(client, sid, "restore", {"kind": "drawdown", "parent_row_id": ids["plan"]},
                   "Only removed rows can be restored.")


@pytest.mark.anyio
async def test_plan_reset_without_a_plan_settings_record_asks_for_a_sync(client, db_session):
    ids = await build_main(client, db_session)
    sid = (await create_scenario(client, ids["plan"]))["id"]
    await put(client, f"/plans/{sid}", {"life_expectancy": 80})
    db_session.query(PlanLink).filter(PlanLink.kind == PLAN_KIND).delete(synchronize_session=False)
    db_session.commit()
    await _refused(client, sid, "reset", {"kind": "plan", "fields": ["life_expectancy"]},
                   "no record of Main's plan settings")
    assert (await get(client, f"/plans/{sid}"))["life_expectancy"] == 80


@pytest.mark.anyio
async def test_a_scenario_partner_is_kept_over_main_and_blocks_restoring_mains(client, db_session):
    household = await post(client, "/clients/personal", status=200)
    pid = (await post(client, "/plans", {"name": "Main", "birth_year": 1985, "client_id": household["id"]}))["id"]
    sid = (await create_scenario(client, pid))["id"]
    await put(client, f"/plans/{sid}", {"spouse": {"name": "Riley", "birth_year": 1984}})
    await put(client, f"/plans/{pid}", {"spouse": {"name": "Ana", "birth_year": 1986}})
    assert (await get(client, f"/plans/{sid}"))["spouse"]["name"] == "Riley"
    inheritance = await get(client, f"/plans/{sid}/inheritance")
    assert [row["reason"] for row in inheritance["skipped"] if row["kind"] == "spouse"] == [
        "This scenario already has its own partner, so Main's partner was not added."]

    # A scenario that removed Main's partner and added its own cannot restore Main's.
    second = (await create_scenario(client, pid, "Second"))["id"]
    await put(client, f"/plans/{second}", {"spouse": None})
    main_partner = item(await get(client, f"/plans/{second}/inheritance"), "spouse")["parent_row_id"]
    await put(client, f"/plans/{second}", {"spouse": {"name": "Riley", "birth_year": 1984}})
    await _refused(client, second, "restore", {"kind": "spouse", "parent_row_id": main_partner},
                   "This scenario already has a partner.")
    assert (await get(client, f"/plans/{second}"))["spouse"]["name"] == "Riley"
