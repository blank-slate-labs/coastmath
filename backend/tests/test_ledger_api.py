"""/api/ledger routes: every route, refusal paths, ownership and the release gate."""
import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.expense import Expense
from app.models.financial_connection import FinancialTransaction, utcnow
from app.models.ledger import FinancialRule
from app.models.user import User
from app.routers.ledger import retention_start
from tests.ledger_fixture import (
    make_import,
    make_source,
    make_txn,
    other_user,
    plan_with_feed,
)

pytestmark = pytest.mark.anyio
TODAY = utcnow().date()
THIS_MONTH = TODAY.replace(day=1)
LAST_MONTH_END = THIS_MONTH - timedelta(days=1)
LAST_MONTH = LAST_MONTH_END.replace(day=1)
LAST_KEY = f"{LAST_MONTH.year:04d}-{LAST_MONTH.month:02d}"
DAY = LAST_MONTH + timedelta(days=9)


@pytest.fixture
def ledger(db_session, test_user):
    card = make_source(db_session, test_user)
    checking = make_source(db_session, test_user, provider="simplefin", external="acct-2", account_type="DEPOSITORY",
                           subtype="CHECKING", name="Synthetic checking",
                           coverage_start=LAST_MONTH - timedelta(days=60),
                           synced_at=datetime.now(UTC))
    make_import(db_session, test_user, card, LAST_MONTH - timedelta(days=60), LAST_MONTH_END)
    rows = {
        "grocery": make_txn(db_session, test_user, card, 80, DAY, "Groceries", description="SYNTHETIC GROCER 12",
                            merchant="Synthetic Grocer"),
        "coffee": make_txn(db_session, test_user, card, 5, DAY, None, description="Synthetic Coffee Bar"),
        "pay": make_txn(db_session, test_user, checking, -3000, DAY, "Paycheck", description="Payroll"),
        "payment": make_txn(db_session, test_user, checking, 400, DAY, None, description="Card payment"),
        "card_side": make_txn(db_session, test_user, card, -400, DAY, None, description="Payment received"),
    }
    db_session.commit()
    return card, checking, rows


async def test_categories_and_accounts(client, transactions_on, ledger):
    card, checking, _ = ledger
    categories = (await client.get("/api/ledger/categories")).json()
    assert {"id": "groceries", "role": "spending", "bucket": "essential", "kind": None, "label": "Groceries"} in categories
    accounts = {a["id"]: a for a in (await client.get("/api/ledger/accounts")).json()}
    assert accounts[str(card.id)]["provider"] == "file" and accounts[str(card.id)]["transaction_count"] == 3
    assert accounts[str(card.id)]["coverage"] == [{"start": str(LAST_MONTH - timedelta(days=60)),
                                                   "end": str(LAST_MONTH_END)}]
    assert accounts[str(card.id)]["spending_eligible"] and accounts[str(card.id)]["editable"]
    assert accounts[str(checking.id)]["last_read_at"] is not None


async def test_account_coverage_ends_on_the_client_date(client, transactions_on, ledger):
    _, checking, _ = ledger
    yesterday = TODAY - timedelta(days=1)

    async def coverage_end(headers):
        accounts = {a["id"]: a for a in (await client.get("/api/ledger/accounts", headers=headers)).json()}
        return accounts[str(checking.id)]["coverage"][-1]["end"]

    assert await coverage_end({"X-Client-Date": str(yesterday)}) == str(yesterday)
    assert await coverage_end({}) == str(TODAY)


async def test_account_updates_and_refusals(client, transactions_on, ledger, db_session, test_user, monkeypatch):
    card, _, _ = ledger
    r = await client.patch(f"/api/ledger/accounts/{card.id}", json={"include_in_spending": False, "name": "Renamed card",
                                                                    "account_type": "DEPOSITORY", "subtype": "CHECKING"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["include_in_spending"], body["counts_toward_spending"], body["name"], body["subtype"]) == (
        False, False, "Renamed card", "CHECKING")
    restored = await client.patch(f"/api/ledger/accounts/{card.id}", json={"include_in_spending": None})
    assert restored.json()["include_in_spending"] is None and restored.json()["counts_toward_spending"]
    assert (await client.patch(f"/api/ledger/accounts/{card.id}", json={"name": None})).status_code == 422
    linked = make_source(db_session, test_user, provider="plaid", environment="sandbox", external="p-1")
    db_session.commit()
    refused = await client.patch(f"/api/ledger/accounts/{linked.id}", json={"name": "No"})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (await client.patch(f"/api/ledger/accounts/{linked.id}", json={"include_in_spending": True})).status_code == 200
    stranger = make_source(db_session, other_user(db_session), external="theirs")
    db_session.commit()
    missing = await client.patch(f"/api/ledger/accounts/{stranger.id}", json={"include_in_spending": True})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"


async def test_transaction_listing_filters_and_pairing(client, transactions_on, ledger):
    card, checking, rows = ledger
    page = (await client.get("/api/ledger/transactions")).json()
    assert page["total"] == 5
    by_id = {row["id"]: row for row in page["transactions"]}
    grocery = by_id[str(rows["grocery"].id)]
    assert (grocery["category"], grocery["category_source"], grocery["kind"], grocery["bucket"]) == (
        "groceries", "provider", "spending", "essential")
    assert by_id[str(rows["payment"].id)]["kind"] == by_id[str(rows["card_side"].id)]["kind"] == "transfer"
    assert by_id[str(rows["pay"].id)]["category"] == "income_wages"

    async def ids(**params):
        payload = (await client.get("/api/ledger/transactions", params=params)).json()
        return {row["id"] for row in payload["transactions"]}

    assert await ids(source_id=str(checking.id)) == {str(rows["pay"].id), str(rows["payment"].id)}
    assert await ids(month=LAST_KEY, category="groceries") == {str(rows["grocery"].id)}
    assert await ids(kind="income") == {str(rows["pay"].id)}
    assert await ids(text="coffee") == {str(rows["coffee"].id)}
    assert await ids(uncategorized=True) == {str(rows["coffee"].id), str(rows["payment"].id),
                                             str(rows["card_side"].id)}
    assert len(await ids(limit=2, offset=1)) == 2
    assert (await client.get("/api/ledger/transactions", params={"month": "2026-13"})).status_code == 422


async def test_transaction_pages_report_the_filtered_total(client, transactions_on, db_session, test_user):
    card = make_source(db_session, test_user)
    for index in range(284):
        make_txn(db_session, test_user, card, 5, DAY - timedelta(days=index % 200), "Groceries")
    db_session.commit()
    first = (await client.get("/api/ledger/transactions")).json()
    assert (len(first["transactions"]), first["total"]) == (100, 284)
    last = (await client.get("/api/ledger/transactions", params={"offset": 200})).json()
    assert (len(last["transactions"]), last["total"]) == (84, 284)


async def test_transaction_export_matches_the_ledger_and_neutralizes_formulas(client, transactions_on, ledger,
                                                                             db_session, test_user):
    card, checking, rows = ledger
    make_txn(db_session, test_user, card, 12.5, DAY, None, description="=HYPERLINK(\"x\")",
                       merchant="@Synthetic", posted_date=DAY + timedelta(days=1), one_time=True)
    make_txn(db_session, test_user, card, 7, retention_start(TODAY) - timedelta(days=1), "Groceries",
             description="Too old")
    stranger = other_user(db_session)
    theirs = make_source(db_session, stranger, external="theirs")
    make_txn(db_session, stranger, theirs, 9, DAY, "Groceries", description="Not mine")
    rows["coffee"].excluded = True
    db_session.commit()
    response = await client.get("/api/ledger/transactions/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="transactions.csv"'
    exported = list(csv.DictReader(io.StringIO(response.text)))
    assert list(exported[0]) == ["date", "posted_date", "description", "merchant", "amount", "currency", "category",
                                 "account", "excluded", "one_time"]
    # The same rows and categories the review lists, and nothing of another user's or past retention.
    listed = (await client.get("/api/ledger/transactions")).json()["transactions"]
    labels = {c["id"]: c["label"] for c in (await client.get("/api/ledger/categories")).json()}
    assert [(r["description"], r["category"]) for r in exported] == [
        (f"'{row['description']}" if row["description"].startswith("=") else row["description"],
         labels[row["category"]]) for row in listed]
    by_description = {r["description"]: r for r in exported}
    grocery = by_description["SYNTHETIC GROCER 12"]
    assert grocery == {"date": str(DAY), "posted_date": "", "description": "SYNTHETIC GROCER 12",
                       "merchant": "Synthetic Grocer", "amount": "80.00", "currency": "USD", "category": "Groceries",
                       "account": grocery["account"], "excluded": "false", "one_time": "false"}
    assert "Synthetic card" in grocery["account"]
    assert by_description["Payroll"]["amount"] == "-3000.00"
    assert by_description["Synthetic Coffee Bar"]["excluded"] == "true"
    escaped = by_description['\'=HYPERLINK("x")']
    assert (escaped["merchant"], escaped["posted_date"], escaped["one_time"]) == (
        "'@Synthetic", str(DAY + timedelta(days=1)), "true")
    assert {"Too old", "Not mine"}.isdisjoint(by_description)


async def test_transaction_corrections_rules_and_feed_reapply(client, transactions_on, ledger, db_session, test_user):
    card, checking, rows = ledger
    plan, feed = plan_with_feed(db_session, test_user, [checking.id])
    coffee = rows["coffee"]
    r = await client.patch(f"/api/ledger/transactions/{coffee.id}", json={"category": "dining", "one_time": True})
    assert r.status_code == 200, r.text
    assert r.json()["transaction"]["category_source"] == "override" and r.json()["transaction"]["kind"] == "one_time"
    assert r.json()["rule"] is None
    cleared = await client.patch(f"/api/ledger/transactions/{coffee.id}", json={"category": None, "one_time": False})
    assert cleared.json()["transaction"]["category"] == "uncategorized"
    assert (await client.patch(f"/api/ledger/transactions/{coffee.id}", json={"excluded": None})).status_code == 422
    assert (await client.patch(f"/api/ledger/transactions/{coffee.id}",
                               json={"apply_to_similar": True})).status_code == 422
    similar = await client.patch(f"/api/ledger/transactions/{rows['grocery'].id}",
                                 json={"category": "shopping", "apply_to_similar": True})
    rule = similar.json()["rule"]
    assert (rule["match_field"], rule["match_type"], rule["pattern"], rule["direction"], rule["match_count"]) == (
        "merchant", "equals", "synthetic grocer", "outflow", 0)
    by_description = await client.patch(f"/api/ledger/transactions/{coffee.id}",
                                        json={"category": "dining", "apply_to_similar": True})
    assert by_description.json()["rule"]["match_field"] == "description"
    # Changing a feed account's spending re-applies that plan's connected expenses.
    paycheck = await client.patch(f"/api/ledger/transactions/{rows['payment'].id}", json={"category": "home"})
    assert paycheck.status_code == 200
    db_session.refresh(feed)
    assert feed.applied_at is not None and feed.months_used >= 1
    expense = db_session.get(Expense, feed.essential_expense_id)
    assert expense.plan_id == plan.id and Decimal(str(expense.annual_amount)) > 0
    stranger = make_txn(db_session, other_user(db_session), make_source(db_session, test_user, external="x"), 1, DAY)
    stranger.user_id = db_session.query(User).filter(User.id != test_user.id).first().id
    db_session.commit()
    assert (await client.patch(f"/api/ledger/transactions/{stranger.id}", json={"one_time": True})).status_code == 404


async def test_bulk_updates(client, transactions_on, ledger):
    _, _, rows = ledger
    ids = [str(rows["grocery"].id), str(rows["coffee"].id)]
    r = await client.post("/api/ledger/transactions/bulk", json={"ids": ids, "excluded": True})
    assert r.status_code == 200, r.text
    assert {row["kind"] for row in r.json()["transactions"]} == {"excluded"}
    assert (await client.post("/api/ledger/transactions/bulk", json={"ids": [], "excluded": True})).status_code == 422
    assert (await client.post("/api/ledger/transactions/bulk",
                              json={"ids": ids, "apply_to_similar": True})).status_code == 422
    missing = await client.post("/api/ledger/transactions/bulk", json={"ids": [*ids, str(uuid.uuid4())],
                                                                       "one_time": True})
    assert missing.status_code == 404


async def test_rules_crud_with_match_counts(client, transactions_on, ledger, db_session, test_user):
    card, _, rows = ledger
    created = await client.post("/api/ledger/rules", json={"match_field": "description", "pattern": "  Synthetic  COFFEE ",
                                                           "category": "dining", "source_id": str(card.id)})
    assert created.status_code == 201, created.text
    rule = created.json()
    assert (rule["pattern"], rule["match_type"], rule["direction"], rule["match_count"]) == (
        "synthetic coffee", "contains", "any", 1)
    listed = (await client.get("/api/ledger/rules")).json()
    assert [r["id"] for r in listed] == [rule["id"]]
    tx = (await client.get("/api/ledger/transactions", params={"text": "coffee"})).json()["transactions"][0]
    assert (tx["category"], tx["category_source"], tx["rule_id"]) == ("dining", "rule", rule["id"])
    updated = await client.patch(f"/api/ledger/rules/{rule['id']}", json={"category": "groceries", "match_type": "equals",
                                                                          "source_id": str(card.id)})
    assert updated.json()["category"] == "groceries" and updated.json()["match_count"] == 0
    for body in ({"pattern": "   "}, {"category": None}, {"category": "bogus"}):
        assert (await client.patch(f"/api/ledger/rules/{rule['id']}", json=body)).status_code == 422
    stranger_source = make_source(db_session, other_user(db_session), external="theirs")
    db_session.commit()
    bad_source = {"match_field": "merchant", "pattern": "x", "category": "dining", "source_id": str(stranger_source.id)}
    assert (await client.post("/api/ledger/rules", json=bad_source)).status_code == 404
    assert (await client.patch(f"/api/ledger/rules/{rule['id']}",
                               json={"source_id": str(stranger_source.id)})).status_code == 404
    assert (await client.patch(f"/api/ledger/rules/{uuid.uuid4()}", json={"category": "dining"})).status_code == 404
    assert (await client.delete(f"/api/ledger/rules/{rule['id']}")).status_code == 204
    assert (await client.delete(f"/api/ledger/rules/{rule['id']}")).status_code == 404


async def test_rule_limit(client, transactions_on, ledger, db_session, test_user):
    for index in range(500):
        db_session.add(FinancialRule(user_id=test_user.id, match_field="description", match_type="contains",
                                     pattern=f"p{index}", category="dining", direction="any",
                                     created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
    db_session.commit()
    r = await client.post("/api/ledger/rules", json={"match_field": "merchant", "pattern": "x", "category": "dining"})
    assert r.status_code == 422


async def test_months_for_sources_and_plans(client, transactions_on, ledger, db_session, test_user):
    card, checking, _ = ledger
    payload = (await client.get("/api/ledger/months")).json()
    assert payload["currency"] == "USD"
    months = {m["month"]: m for m in payload["months"]}
    # The synced checking account settles six days into the month.
    assert months[LAST_KEY]["complete"] is (TODAY.day >= 6)
    assert {s["id"] for s in payload["sources"]} == {str(card.id), str(checking.id)}
    only_card = (await client.get("/api/ledger/months", params={"source_ids": [str(card.id)]})).json()
    last = {m["month"]: m for m in only_card["months"]}[LAST_KEY]
    assert last["complete"] and last["essential"] == 85.0 and last["by_category"] == {"groceries": 80.0,
                                                                                      "uncategorized": 5.0}
    plan, _ = plan_with_feed(db_session, test_user, [card.id])
    plan.currency = "EUR"
    db_session.commit()
    planned = (await client.get("/api/ledger/months", params={"plan_id": str(plan.id)})).json()
    assert planned["currency"] == "EUR" and [s["id"] for s in planned["sources"]] == [str(card.id)]
    assert {m["month"]: m for m in planned["months"]}[LAST_KEY]["essential"] == 0.0
    assert (await client.get("/api/ledger/months", params={"plan_id": str(uuid.uuid4())})).status_code == 404
    too_many = [str(uuid.uuid4()) for _ in range(51)]
    assert (await client.get("/api/ledger/months", params={"source_ids": too_many})).status_code == 422


async def test_release_gate_refuses_changes_but_keeps_reads_and_deletes(client, ledger, db_session, test_user):
    card, _, rows = ledger
    refused = await client.patch(f"/api/ledger/transactions/{rows['coffee'].id}", json={"one_time": True})
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "FEATURE_DISABLED"
    assert (await client.post("/api/ledger/rules", json={"match_field": "merchant", "pattern": "x",
                                                         "category": "dining"})).status_code == 503
    assert (await client.get("/api/ledger/transactions")).status_code == 200
    rule = FinancialRule(user_id=test_user.id, match_field="merchant", match_type="equals", pattern="x",
                         category="dining", direction="any", created_at=datetime.now(UTC),
                         updated_at=datetime.now(UTC))
    db_session.add(rule)
    db_session.commit()
    assert (await client.delete(f"/api/ledger/rules/{rule.id}")).status_code == 204


async def test_routes_require_a_session(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anonymous:
            assert (await anonymous.get("/api/ledger/accounts")).status_code == 401
            assert (await anonymous.get("/api/ledger/transactions/export")).status_code == 401
    finally:
        app.dependency_overrides.clear()


async def test_inactive_environment_rows_are_invisible(client, transactions_on, db_session, test_user, monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "production")
    sandbox = make_source(db_session, test_user, provider="plaid", environment="sandbox", external="p1")
    row = make_txn(db_session, test_user, sandbox, 10, DAY)
    db_session.commit()
    assert (await client.get("/api/ledger/accounts")).json() == []
    assert (await client.get("/api/ledger/transactions")).json()["total"] == 0
    assert (await client.patch(f"/api/ledger/transactions/{row.id}", json={"one_time": True})).status_code == 404
    assert db_session.query(FinancialTransaction).count() == 1
