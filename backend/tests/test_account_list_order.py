"""An account edit must not reshuffle the editor's rows."""
import uuid

import pytest

from app.models.account import CurrentAccount


@pytest.mark.anyio
async def test_account_list_has_immutable_order(client, db_session, test_user):
    ids = [uuid.UUID(int=n) for n in (3, 1, 2)]
    for index, account_id in enumerate(ids):
        db_session.add(CurrentAccount(
            id=account_id, user_id=test_user.id, name=f"Account {index}",
            account_type="savings", balance=100,
        ))
    db_session.commit()
    before = (await client.get("/api/accounts")).json()
    assert [row["id"] for row in before] == [str(i) for i in sorted(ids)]
    updated = await client.put(f"/api/accounts/{ids[1]}", json={"name": "Renamed", "balance": 101})
    assert updated.status_code == 200
    after = (await client.get("/api/accounts")).json()
    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert after[0]["name"] == "Renamed"
