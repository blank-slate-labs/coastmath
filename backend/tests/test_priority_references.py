"""Allocation rules may name only accounts, incomes, milestones and loans in scope.

Pins the full error envelope of each reference check on the bulk replacement.
"""
import uuid

import pytest

from app.models.account import CurrentAccount
from app.models.income import IncomeStream
from app.models.milestone import Milestone
from app.models.user import User
from app.seed import seed_demo_plan

pytestmark = pytest.mark.anyio


@pytest.fixture
def plans(db_session, test_user):
    other = User(is_anonymous=False, settings={})
    db_session.add(other)
    db_session.flush()
    own, foreign = seed_demo_plan(test_user.id, db_session), seed_demo_plan(other.id, db_session)
    db_session.commit()
    return own, foreign


async def _current(client, plan_id):
    current = (await client.get(f"/api/plans/{plan_id}/priorities")).json()
    items = [{key: value for key, value in item.items() if key not in {"id", "plan_id"}} for item in current["items"]]
    return current["revision"], items


def _envelope(message, field, reason):
    return {"error": {"code": "VALIDATION_ERROR", "message": message, "details": [{"field": field, "reason": reason}]}}


async def test_unchanged_rules_save_and_bump_the_revision(client, plans):
    own, _foreign = plans
    revision, items = await _current(client, own.id)
    response = await client.put(f"/api/plans/{own.id}/priorities", json={"expected_revision": revision, "items": items})
    assert response.status_code == 200
    assert response.json()["revision"] == revision + 1
    assert (await client.get(f"/api/plans/{own.id}/priorities")).json()["revision"] == revision + 1


async def test_foreign_target_account_is_rejected(client, db_session, plans):
    own, foreign = plans
    theirs = db_session.query(CurrentAccount).filter_by(user_id=foreign.user_id).first()
    revision, items = await _current(client, own.id)
    items[0]["target_account_id"] = str(theirs.id)
    response = await client.put(f"/api/plans/{own.id}/priorities", json={"expected_revision": revision, "items": items})
    assert response.status_code == 422
    assert response.json() == _envelope("Invalid target_account_id references", "target_account_id", f"{theirs.id} not found")


async def test_foreign_source_account_is_rejected(client, db_session, plans):
    own, foreign = plans
    theirs = db_session.query(CurrentAccount).filter_by(user_id=foreign.user_id).first()
    revision, items = await _current(client, own.id)
    items[0]["source_account_id"] = str(theirs.id)
    response = await client.put(f"/api/plans/{own.id}/priorities", json={"expected_revision": revision, "items": items})
    assert response.status_code == 422
    assert response.json() == _envelope(
        "Invalid priority source", "source", "Account must belong to you and income must belong to this plan")


async def test_foreign_source_income_is_rejected(client, db_session, plans):
    own, foreign = plans
    theirs = db_session.query(IncomeStream).filter_by(plan_id=foreign.id).first()
    revision, items = await _current(client, own.id)
    items[0]["source_income_id"] = str(theirs.id)
    response = await client.put(f"/api/plans/{own.id}/priorities", json={"expected_revision": revision, "items": items})
    assert response.status_code == 422
    assert response.json() == _envelope(
        "Invalid priority source", "source", "Account must belong to you and income must belong to this plan")


async def test_foreign_window_milestone_is_rejected(client, db_session, plans):
    own, foreign = plans
    theirs = db_session.query(Milestone).filter_by(plan_id=foreign.id).first()
    revision, items = await _current(client, own.id)
    items[0]["end_milestone_id"] = str(theirs.id)
    response = await client.put(f"/api/plans/{own.id}/priorities", json={"expected_revision": revision, "items": items})
    assert response.status_code == 422
    assert response.json() == _envelope("Rule milestones must belong to this plan.", "start_milestone_id", "not found in plan")


async def test_unknown_debt_target_is_rejected(client, plans):
    own, _foreign = plans
    revision, items = await _current(client, own.id)
    rank = max(item["priority_rank"] for item in items) + 1
    items.append({"priority_rank": rank, "priority_type": "debt_payment", "target_liability_id": str(uuid.uuid4())})
    response = await client.put(f"/api/plans/{own.id}/priorities", json={"expected_revision": revision, "items": items})
    assert response.status_code == 422
    assert response.json() == _envelope(
        "A debt payment rule must name a loan in this plan.", "target_liability_id", "not found in plan")


async def test_another_users_plan_is_not_found_on_both_routes(client, plans):
    _own, foreign = plans
    assert (await client.get(f"/api/plans/{foreign.id}/priorities")).status_code == 404
    response = await client.put(f"/api/plans/{foreign.id}/priorities", json={"expected_revision": 0, "items": []})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
