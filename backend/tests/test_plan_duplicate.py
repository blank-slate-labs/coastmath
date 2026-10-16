"""Duplicating a plan preserves its inputs without copying user accounts."""
import uuid

import pytest
from sqlalchemy import inspect, text

from app.models.account import CurrentAccount
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.user import User
from app.seed import seed_demo_plan


@pytest.mark.anyio
async def test_duplicate_preserves_seeded_projection_and_remaps_inputs(client, db_session, test_user):
    seed_demo_plan(test_user.id, db_session)
    db_session.commit()
    source = db_session.query(Plan).filter_by(user_id=test_user.id).one()
    account_ids = {a.id for a in db_session.query(CurrentAccount).all()}
    # Exercise a relative milestone even when it appears before its anchor.
    anchor = source.milestones[0]
    relative = Milestone(id=uuid.uuid4(), plan_id=source.id, name="Before retirement",
                         trigger_type="relative", relative_to_id=anchor.id, offset_years=-1)
    db_session.add(relative)
    db_session.commit()
    # Production enforces FKs; the normal SQLite fixture does not.
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    source_id = source.id
    original = (await client.get(f"/api/plans/{source_id}")).json()
    forecast = await client.post(f"/api/plans/{source_id}/simulate", headers={"X-Client-Date": "2026-09-07"})
    assert forecast.status_code == 200, forecast.text
    response = await client.post(f"/api/plans/{source_id}/duplicate")
    assert response.status_code == 201, response.text
    data = response.json()
    copied = db_session.get(Plan, uuid.UUID(data["id"]))
    assert data["name"] == source.name + " (copy)"
    assert copied.user_id == test_user.id
    assert copied.priorities_revision == 0
    assert {a.id for a in db_session.query(CurrentAccount).all()} == account_ids
    identities = {source.id: copied.id}
    for relation in inspect(Plan).relationships:
        if not relation.cascade.delete_orphan:
            continue
        old = getattr(source, relation.key)
        new = getattr(copied, relation.key)
        old_rows = old if relation.uselist else ([old] if old else [])
        new_rows = new if relation.uselist else ([new] if new else [])
        assert len(old_rows) == len(new_rows)
        # Collection insertion order is preserved by the copying operation.
        for a, b in zip(old_rows, new_rows, strict=True):
            assert a.id != b.id
            identities[a.id] = b.id
    for relation in inspect(Plan).relationships:
        if not relation.cascade.delete_orphan:
            continue
        old, new = getattr(source, relation.key), getattr(copied, relation.key)
        old_rows = old if relation.uselist else ([old] if old else [])
        new_rows = new if relation.uselist else ([new] if new else [])
        for a, b in zip(old_rows, new_rows, strict=True):
            for col in inspect(type(a)).columns:
                if col.key == "created_at":
                    continue
                value = getattr(a, col.key)
                expected = identities.get(value, value) if isinstance(value, uuid.UUID) else value
                assert getattr(b, col.key) == expected, (relation.key, col.key)
    copied_forecast = await client.post(f"/api/plans/{copied.id}/simulate", headers={"X-Client-Date": "2026-09-07"})
    assert copied_forecast.status_code == 200, copied_forecast.text
    for a, b in zip(forecast.json()["yearly_snapshots"], copied_forecast.json()["yearly_snapshots"], strict=True):
        for key in ("year", "net_worth", "gross_income", "expenses", "taxes", "net_cash_flow", "accounts"):
            assert a[key] == b[key], (a["year"], key)
    assert (await client.get(f"/api/plans/{source_id}")).json() == original
    assert (await client.put(f"/api/plans/{copied.id}", json={"name": "My scenario"})).status_code == 200
    assert (await client.get(f"/api/plans/{source_id}")).json() == original
    db_session.execute(text("PRAGMA foreign_keys=OFF"))


@pytest.mark.anyio
async def test_duplicate_rejects_other_users_and_missing_plans(client, db_session):
    other = User(id=uuid.uuid4(), is_anonymous=True, settings={})
    db_session.add(other)
    db_session.flush()
    plan = Plan(id=uuid.uuid4(), user_id=other.id, name="Private", birth_year=1990)
    db_session.add(plan)
    db_session.commit()
    before = db_session.query(Plan).count()
    for plan_id in (plan.id, uuid.uuid4()):
        response = await client.post(f"/api/plans/{plan_id}/duplicate")
        assert response.status_code == 404
    assert db_session.query(Plan).count() == before
