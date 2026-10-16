"""A milestone that saved settings still use cannot be deleted.

Each reference below lives in JSON (or a foreign key that does not clear), so
deleting the milestone would leave a dangling id and silently switch the
setting off. The delete returns 409 in the shared envelope and keeps the
milestone; once the reference is changed the delete succeeds.
"""
import uuid

import pytest

from app.models.spouse import Spouse
from tests.scenario_support import get, post, put


async def _plan(client, **extra):
    plan = await post(client, "/plans", {"name": "Delete guards", "birth_year": 1980, **extra})
    milestone = await post(client, f"/plans/{plan['id']}/milestones",
                           {"name": "Trigger", "trigger_type": "age", "trigger_value": 47})
    return plan["id"], milestone["id"]


async def _assert_blocked(client, pid, mid, message):
    response = await client.delete(f"/api/plans/{pid}/milestones/{mid}")
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "CONFLICT"
    assert error["message"] == message
    assert error["details"] == []
    assert mid in {row["id"] for row in (await get(client, f"/plans/{pid}"))["milestones"]}


async def _assert_deleted(client, pid, mid):
    response = await client.delete(f"/api/plans/{pid}/milestones/{mid}")
    assert response.status_code == 204, response.text
    assert mid not in {row["id"] for row in (await get(client, f"/plans/{pid}"))["milestones"]}


@pytest.mark.anyio
async def test_unreferenced_milestone_deletes(client):
    pid, mid = await _plan(client)
    await _assert_deleted(client, pid, mid)


@pytest.mark.anyio
async def test_loan_forgiveness_blocks_delete(client):
    pid, mid = await _plan(client)
    loan = await post(client, f"/plans/{pid}/liabilities", {
        "name": "Student loan", "principal_balance": 100000, "interest_rate": 0,
        "monthly_payment": 1, "forgiveness": {"milestone_id": mid}})
    before = (await client.post(f"/api/plans/{pid}/simulate", json={})).json()["yearly_snapshots"]
    await _assert_blocked(client, pid, mid, "This milestone forgives a loan. Update that loan before deleting it.")
    after = (await client.post(f"/api/plans/{pid}/simulate", json={})).json()["yearly_snapshots"]
    assert sum(row.get("debt_forgiven") or 0 for row in after) == pytest.approx(
        sum(row.get("debt_forgiven") or 0 for row in before))
    assert sum(row.get("debt_forgiven") or 0 for row in after) > 99_000
    await put(client, f"/plans/{pid}/liabilities/{loan['id']}", {"forgiveness": {"year": 2030}})
    await _assert_deleted(client, pid, mid)


@pytest.mark.anyio
async def test_country_benefit_start_blocks_delete(client, fixture_pack):
    pid, mid = await _plan(client, tax_country="QZ", tax_region="N", currency="EUR")
    await put(client, f"/plans/{pid}", {"intl_settings": {"benefits": [
        {"rule": "QZ:basic_pension", "start_milestone_id": mid, "params": {"monthly_amount": 1000}}]}})
    await _assert_blocked(client, pid, mid, "This milestone starts a country benefit. Update that benefit before deleting it.")
    await put(client, f"/plans/{pid}", {"intl_settings": {"benefits": [
        {"rule": "QZ:basic_pension", "start_age": 65, "params": {"monthly_amount": 1000}}]}})
    await _assert_deleted(client, pid, mid)


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["aca_start_milestone_id", "aca_end_milestone_id"])
async def test_marketplace_coverage_window_blocks_delete(client, field):
    pid, mid = await _plan(client)
    aca = {"enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 9000, "aca_plan_premium_annual": 8000}
    await put(client, f"/plans/{pid}", {"healthcare_settings": {**aca, field: mid}})
    await _assert_blocked(client, pid, mid,
                          "This milestone bounds marketplace coverage. Update the healthcare settings before deleting it.")
    await put(client, f"/plans/{pid}", {"healthcare_settings": aca})
    await _assert_deleted(client, pid, mid)


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["start_milestone_id", "end_milestone_id"])
async def test_charitable_gift_window_blocks_delete(client, field):
    pid, mid = await _plan(client)
    gift = await post(client, f"/plans/{pid}/charities", {
        "name": "Food bank", "entity_type": "direct", "annual_amount": 5000, field: mid})
    await _assert_blocked(client, pid, mid, "This milestone times a charitable gift. Update that gift before deleting it.")
    response = await client.patch(f"/api/plans/{pid}/charities/{gift['id']}", json={field: None})
    assert response.status_code == 200, response.text
    await _assert_deleted(client, pid, mid)


@pytest.mark.anyio
async def test_existing_guards_keep_their_messages(client):
    pid, mid = await _plan(client)
    await put(client, f"/plans/{pid}", {"withdrawal_strategy": {"enabled": True, "start_milestone_id": mid}})
    await _assert_blocked(client, pid, mid,
                          "This milestone starts the withdrawal strategy. Update that strategy before deleting it.")


@pytest.mark.anyio
async def test_missing_milestone_is_not_found(client):
    pid, mid = await _plan(client)
    await _assert_deleted(client, pid, mid)
    response = await client.delete(f"/api/plans/{pid}/milestones/{mid}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# Foreign keys declared ON DELETE SET NULL would clear silently (a salary that
# ends at retirement would run for life), so each one blocks the delete too.

_ONE = " uses this milestone. Point it at another milestone before deleting this one."
_MANY = " use this milestone. Point them at another milestone before deleting this one."


async def _blocks_until_cleared(client, pid, mid, message, path, field, clear=None):
    await _assert_blocked(client, pid, mid, message)
    await put(client, f"/plans/{pid}" + (f"/{path}" if path else ""), clear if clear is not None else {field: None})
    await _assert_deleted(client, pid, mid)


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["start_milestone_id", "end_milestone_id"])
async def test_income_window_blocks_delete(client, field):
    pid, mid = await _plan(client)
    income = await post(client, f"/plans/{pid}/incomes", {"name": "Salary", "annual_amount": 90000, field: mid})
    await _blocks_until_cleared(client, pid, mid, "Salary" + _ONE, f"incomes/{income['id']}", field)


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["start_milestone_id", "end_milestone_id"])
async def test_expense_window_blocks_delete(client, field):
    pid, mid = await _plan(client)
    expense = await post(client, f"/plans/{pid}/expenses", {"name": "Rent", "annual_amount": 24000, field: mid})
    await _blocks_until_cleared(client, pid, mid, "Rent" + _ONE, f"expenses/{expense['id']}", field)


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["start_milestone_id", "end_milestone_id"])
async def test_allocation_rule_window_blocks_delete(client, field):
    pid, mid = await _plan(client)
    account = await post(client, f"/plans/{pid}/accounts", {
        "name": "Brokerage", "account_type": "taxable_brokerage", "balance": 1000})
    rule = {"priority_rank": 1, "priority_type": "contribution", "target_account_id": account["id"],
            "allocation_mode": "amount", "allocation_value": 5000}
    saved = await put(client, f"/plans/{pid}/priorities", {"expected_revision": 0, "items": [{**rule, field: mid}]})
    await _blocks_until_cleared(client, pid, mid, "Brokerage allocation" + _ONE, "priorities", field,
                                {"expected_revision": saved["revision"], "items": [rule]})


@pytest.mark.anyio
async def test_loan_payoff_blocks_delete(client):
    pid, mid = await _plan(client)
    loan = await post(client, f"/plans/{pid}/liabilities", {
        "name": "Car loan", "principal_balance": 20000, "interest_rate": 4, "term_months": 60,
        "payoff_milestone_id": mid})
    await _blocks_until_cleared(client, pid, mid, "Car loan" + _ONE, f"liabilities/{loan['id']}", "payoff_milestone_id")


@pytest.mark.anyio
async def test_loan_recurrence_end_blocks_delete(client):
    pid, mid = await _plan(client)
    loan = await post(client, f"/plans/{pid}/liabilities", {
        "name": "Car loan", "principal_balance": 20000, "interest_rate": 4, "term_months": 60,
        "recurrence_years": 6, "recurrence_end_milestone_id": mid})
    await _blocks_until_cleared(client, pid, mid, "Car loan" + _ONE, f"liabilities/{loan['id']}",
                                "recurrence_end_milestone_id")


@pytest.mark.anyio
@pytest.mark.parametrize("field", ["start_milestone_id", "end_milestone_id"])
async def test_residency_period_blocks_delete(client, field):
    pid, mid = await _plan(client)
    await put(client, f"/plans/{pid}", {"residency_periods": [{"state_code": "TX", "rank": 0, field: mid}]})
    await _blocks_until_cleared(client, pid, mid, "Residence in TX" + _ONE, "", field,
                                {"residency_periods": [{"state_code": "TX", "rank": 0, "start_year": 2030}]})


@pytest.mark.anyio
async def test_partner_retirement_reference_does_not_block(client, db_session):
    # No client can change it and the engine never reads it, so it clears.
    pid, mid = await _plan(client)
    await put(client, f"/plans/{pid}", {"spouse": {"name": "Sam", "birth_year": 1982}})
    spouse = db_session.query(Spouse).filter(Spouse.plan_id == uuid.UUID(pid)).one()
    spouse.retirement_milestone_id = uuid.UUID(mid)
    db_session.commit()
    await _assert_deleted(client, pid, mid)


@pytest.mark.anyio
async def test_relative_milestone_blocks_delete(client):
    pid, mid = await _plan(client)
    relative = await post(client, f"/plans/{pid}/milestones", {
        "name": "Two years later", "trigger_type": "relative", "relative_to_id": mid, "offset_years": 2})
    await _blocks_until_cleared(client, pid, mid, "Two years later" + _ONE, f"milestones/{relative['id']}", "",
                                {"trigger_type": "age", "trigger_value": 49, "relative_to_id": None})


@pytest.mark.anyio
async def test_message_names_two_or_three_dependents_then_counts(client):
    pid, mid = await _plan(client)
    await post(client, f"/plans/{pid}/incomes", {"name": "Salary", "annual_amount": 90000, "end_milestone_id": mid})
    rent = await post(client, f"/plans/{pid}/expenses", {"name": "Rent", "annual_amount": 24000, "end_milestone_id": mid})
    await _assert_blocked(client, pid, mid, "Salary and Rent" + _MANY)
    await post(client, f"/plans/{pid}/liabilities", {
        "name": "Car loan", "principal_balance": 20000, "interest_rate": 4, "term_months": 60, "payoff_milestone_id": mid})
    await _assert_blocked(client, pid, mid, "Salary, Rent and Car loan" + _MANY)
    await post(client, f"/plans/{pid}/expenses", {"name": "Travel", "annual_amount": 8000, "start_milestone_id": mid})
    await _assert_blocked(client, pid, mid, "Salary, Rent and 2 more" + _MANY)
    # The engine still sees every reference while the delete is refused.
    plan = await get(client, f"/plans/{pid}")
    assert next(row for row in plan["expenses"] if row["id"] == rent["id"])["end_milestone_id"] == mid


@pytest.mark.anyio
async def test_json_reference_message_comes_before_foreign_keys(client):
    pid, mid = await _plan(client)
    await post(client, f"/plans/{pid}/incomes", {"name": "Salary", "annual_amount": 90000, "end_milestone_id": mid})
    await put(client, f"/plans/{pid}", {"withdrawal_strategy": {"enabled": True, "start_milestone_id": mid}})
    await _assert_blocked(client, pid, mid,
                          "This milestone starts the withdrawal strategy. Update that strategy before deleting it.")


@pytest.mark.anyio
async def test_other_plans_rows_do_not_block(client):
    pid, mid = await _plan(client)
    other, other_mid = await _plan(client)
    await post(client, f"/plans/{other}/incomes", {"name": "Salary", "annual_amount": 90000, "end_milestone_id": other_mid})
    await _assert_deleted(client, pid, mid)
