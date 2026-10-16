"""Personal plans reuse the client ownership boundary without requiring setup."""
import uuid

import pytest

from app.auth.router import create_jwt
from app.models.planning_client import PlanningClient
from app.models.user import User
from tests.scenario_support import extra_workspace


@pytest.mark.anyio
async def test_personal_workspace_is_idempotent_and_preserves_existing_clients(client, db_session, test_user):
    test_user.settings = {"display_preference": "keep"}
    db_session.commit()
    existing = extra_workspace(db_session, test_user.id, "Existing household")
    first = await client.post("/api/clients/personal")
    assert first.status_code == 200, first.text
    second = await client.post("/api/clients/personal")
    assert second.json()["id"] == first.json()["id"] != existing["id"]
    db_session.refresh(test_user)
    assert test_user.settings == {"display_preference": "keep", "personal_workspace_client_id": first.json()["id"]}
    assert db_session.get(PlanningClient, uuid.UUID(existing["id"])).name == "Existing household"
    # Renaming the container cannot create a second one or move any plans.
    await client.put("/api/clients/" + first.json()["id"], json={"name": "Renamed"})
    assert (await client.post("/api/clients/personal")).json()["id"] == first.json()["id"]
    plans = [(await client.post("/api/plans", json={"name": name, "birth_year": 1990, "client_id": first.json()["id"]})).json()
             for name in ["My plan", "Alternative"]]
    account = await client.post(f'/api/plans/{plans[0]["id"]}/accounts', json={"name": "Cash", "account_type": "checking", "balance": 100000})
    assert account.status_code == 201
    assert (await client.get(f'/api/plans/{plans[1]["id"]}/accounts')).json() == []


@pytest.mark.anyio
async def test_personal_workspace_repairs_deleted_or_foreign_pointer_without_accessing_other_user(client, db_session, test_user):
    original = (await client.post("/api/clients/personal")).json()
    assert (await client.delete("/api/clients/" + original["id"])).status_code == 204
    replacement = (await client.post("/api/clients/personal")).json()
    assert replacement["id"] != original["id"]
    intruder = User(id=uuid.uuid4(), is_anonymous=True, settings={"personal_workspace_client_id": replacement["id"]})
    db_session.add(intruder)
    db_session.commit()
    client.cookies.clear()
    client.cookies.set("session", create_jwt(intruder.id))
    other = (await client.post("/api/clients/personal")).json()
    assert other["user_id"] == str(intruder.id)
    assert other["id"] != replacement["id"]
    assert db_session.get(PlanningClient, uuid.UUID(replacement["id"])).user_id == test_user.id
