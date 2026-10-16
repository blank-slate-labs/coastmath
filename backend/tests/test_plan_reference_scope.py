"""Records a plan points at must belong to that plan."""
import pytest

from app.models.cash_flow_priority import CashFlowPriority
from app.models.expense import Expense
from app.models.income import IncomeStream
from app.models.milestone import Milestone
from app.models.residency_period import ResidencyPeriod
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


def first(db_session, model, plan):
    return db_session.query(model).filter_by(plan_id=plan.id).first()


async def test_residency_periods_cannot_use_another_users_milestones(client, db_session, plans):
    own, foreign = plans
    theirs, mine = first(db_session, Milestone, foreign), first(db_session, Milestone, own)
    response = await client.put(f"/api/plans/{own.id}", json={"residency_periods": [
        {"state_code": "CA", "end_milestone_id": str(mine.id)}, {"state_code": "NV", "start_milestone_id": str(theirs.id)}]})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "residency_periods.1.start_milestone_id"
    assert db_session.query(ResidencyPeriod).filter_by(plan_id=own.id).count() == 0
    accepted = await client.put(f"/api/plans/{own.id}", json={"residency_periods": [{"state_code": "CA", "end_milestone_id": str(mine.id)}]})
    assert accepted.status_code == 200


async def test_allocation_rules_cannot_use_another_users_milestones(client, db_session, plans):
    own, foreign = plans
    current = (await client.get(f"/api/plans/{own.id}/priorities")).json()
    items = [{key: value for key, value in item.items() if key not in {"id", "plan_id"}} for item in current["items"]]
    items[0]["start_milestone_id"] = str(first(db_session, Milestone, foreign).id)
    response = await client.put(f"/api/plans/{own.id}/priorities", json={"expected_revision": current["revision"], "items": items})
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Rule milestones must belong to this plan."
    assert db_session.query(CashFlowPriority).filter_by(plan_id=own.id).count() == len(items)
    items[0]["start_milestone_id"] = str(first(db_session, Milestone, own).id)
    response = await client.put(f"/api/plans/{own.id}/priorities", json={"expected_revision": current["revision"], "items": items})
    assert response.status_code == 200


async def test_expenses_cannot_tie_to_another_users_income(client, db_session, plans):
    own, foreign = plans
    theirs, mine = first(db_session, IncomeStream, foreign), first(db_session, IncomeStream, own)
    created = await client.post(f"/api/plans/{own.id}/expenses", json={"name": "Dues", "tied_income_id": str(theirs.id)})
    assert created.status_code == 422
    assert created.json()["error"]["details"][0]["field"] == "tied_income_id"
    expense = first(db_session, Expense, own)
    updated = await client.put(f"/api/plans/{own.id}/expenses/{expense.id}", json={"tied_income_id": str(theirs.id)})
    assert updated.status_code == 422
    assert (await client.post(f"/api/plans/{own.id}/expenses", json={"name": "Dues", "tied_income_id": str(mine.id)})).status_code == 201
