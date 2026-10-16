"""IRAs, 401(k)s and HSAs cannot be owned jointly; legacy joint rows still save other edits."""

import uuid

import pytest

from app.models.account import CurrentAccount
from app.schemas.account import INDIVIDUAL_ONLY_ACCOUNT_TYPES, JOINT_OWNER_REASON

pytestmark = pytest.mark.anyio

JOINT_ERROR = {
    "code": "VALIDATION_ERROR",
    "message": "Account was not saved: an IRA, 401(k) or HSA cannot be owned jointly",
    "details": [{"field": "owner", "reason": JOINT_OWNER_REASON}],
}


def test_individual_only_types_match_the_web_account_form():
    # AccountForm.tsx hides Joint for INDIVIDUAL_ONLY_ACCOUNT_TYPES in src/domain/account_types.ts.
    assert {
        "traditional_401k", "roth_401k", "traditional_403b", "roth_403b", "traditional_457b", "roth_457b",
        "traditional_401a", "traditional_ira", "roth_ira", "hsa"} == INDIVIDUAL_ONLY_ACCOUNT_TYPES


@pytest.mark.parametrize("account_type", sorted(INDIVIDUAL_ONLY_ACCOUNT_TYPES))
async def test_create_rejects_a_joint_ira_401k_or_hsa(client, db_session, account_type):
    r = await client.post("/api/accounts", json={"name": "Joint", "account_type": account_type, "owner": "joint"})
    assert r.status_code == 422
    assert r.json() == {"error": JOINT_ERROR}
    assert db_session.query(CurrentAccount).count() == 0


@pytest.mark.parametrize("account_type,owner", [
    ("taxable_brokerage", "joint"), ("checking", "joint"), ("five_twenty_nine", "joint"),
    ("roth_ira", "self"), ("traditional_401k", "spouse"), ("hsa", "spouse"),
])
async def test_create_accepts_other_owner_and_type_combinations(client, account_type, owner):
    r = await client.post("/api/accounts", json={"name": "A", "account_type": account_type, "owner": owner})
    assert r.status_code == 201, r.text
    assert r.json()["owner"] == owner


async def test_update_rejects_setting_a_joint_ira_through_owner_or_type(client, db_session):
    brokerage = (await client.post("/api/accounts", json={
        "name": "Joint brokerage", "account_type": "taxable_brokerage", "owner": "joint", "balance": 10,
    })).json()
    ira = (await client.post("/api/accounts", json={"name": "IRA", "account_type": "roth_ira", "balance": 10})).json()

    r = await client.put(f"/api/accounts/{brokerage['id']}", json={"account_type": "traditional_ira"})
    assert r.status_code == 422
    assert r.json() == {"error": JOINT_ERROR}
    r = await client.put(f"/api/accounts/{ira['id']}", json={"owner": "joint", "balance": 20})
    assert r.status_code == 422
    assert r.json() == {"error": JOINT_ERROR}

    # Nothing was saved, including the balance sent with the rejected owner.
    db_session.expire_all()
    rows = {str(a.id): a for a in db_session.query(CurrentAccount).all()}
    assert (rows[brokerage["id"]].account_type, rows[brokerage["id"]].owner) == ("taxable_brokerage", "joint")
    assert (rows[ira["id"]].owner, float(rows[ira["id"]].balance)) == ("self", 10)


async def test_a_legacy_joint_ira_still_saves_other_edits(client, db_session, test_user):
    legacy = CurrentAccount(id=uuid.uuid4(), user_id=test_user.id, name="Old joint IRA",
                            account_type="roth_ira", owner="joint", balance=1_000)
    db_session.add(legacy)
    db_session.commit()
    url = f"/api/accounts/{legacy.id}"

    r = await client.put(url, json={"balance": 2_000})
    assert r.status_code == 200, r.text
    # The web form resends the unchanged owner and type with every edit.
    r = await client.put(url, json={"name": "Renamed", "account_type": "roth_ira", "owner": "joint", "balance": 3_000})
    assert r.status_code == 200, r.text
    assert (r.json()["owner"], r.json()["balance"]) == ("joint", 3_000)

    r = await client.put(url, json={"account_type": "traditional_ira"})
    assert r.status_code == 422
    assert r.json() == {"error": JOINT_ERROR}

    r = await client.put(url, json={"owner": "spouse", "account_type": "traditional_ira"})
    assert r.status_code == 200, r.text
    assert (r.json()["owner"], r.json()["account_type"]) == ("spouse", "traditional_ira")
