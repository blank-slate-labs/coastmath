"""/api/ledger/imports: preview, commit, coverage, duplicates, revert, account removal and the gate.

Every file is synthetic and built here; account numbers are placeholders.
"""
import base64
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.ledger import file_imports
from app.ledger.importers import ImportFileError
from app.middleware.body_limit import MIB, BodySizeLimitMiddleware
from app.models.account import CurrentAccount
from app.models.financial_connection import (
    FinancialBalanceLink,
    FinancialSource,
    FinancialSpendingFeed,
    FinancialTransaction,
    utcnow,
)
from app.models.ledger import FinancialImport, FinancialRule
from app.models.user import User
from app.routers.ledger import lock_user
from app.schemas.ledger_imports import MAX_BASE64_LENGTH
from app.sqlite_support import create_sqlite_engine, install_python_defaults
from tests.ledger_fixture import (
    make_import,
    make_source,
    make_txn,
    other_user,
    plan_with_feed,
)

pytestmark = pytest.mark.anyio
TODAY = utcnow().date()
# A complete month comfortably in the past, and the one before it.
MONTH = (TODAY.replace(day=1) - timedelta(days=40)).replace(day=1)
MONTH_END = file_imports.month_end(MONTH)
PREV = (MONTH - timedelta(days=1)).replace(day=1)
PREV_END = MONTH - timedelta(days=1)
KEY = f"{MONTH.year:04d}-{MONTH.month:02d}"
PREV_KEY = f"{PREV.year:04d}-{PREV.month:02d}"


def day(base: date, offset: int) -> date:
    return base + timedelta(days=offset)


def csv_file(rows: list[tuple[date, str, str, str]], status: list[str] | None = None) -> bytes:
    header = "Date,Description,Amount,Category" + (",Status" if status else "")
    lines = [header]
    for index, (when, text, amount, category) in enumerate(rows):
        line = f"{when.isoformat()},{text},{amount},{category}"
        lines.append(line + (f",{status[index]}" if status else ""))
    return ("\n".join(lines) + "\n").encode()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


JUNE_ROWS = [
    (day(MONTH, 1), "Synthetic Grocer", "-80.00", "Groceries"),
    (day(MONTH, 4), "Synthetic Diner", "-25.50", "Restaurants"),
    (day(MONTH, 9), "Synthetic Widgets", "-40.00", "Zeta stuff"),
    (day(MONTH, 14), "Payroll deposit", "2000.00", "Paycheck"),
    (day(MONTH, 20), "Synthetic Grocer", "-60.00", "Groceries"),
    (day(MONTH, 25), "Payroll deposit", "2000.00", "Paycheck"),
]
JUNE = csv_file(JUNE_ROWS)


async def preview(client, data: bytes, **extra):
    return await client.post("/api/ledger/imports/preview",
                             json={"filename": "statement.csv", "content_base64": b64(data), **extra})


async def commit(client, data: bytes, filename="statement.csv", **extra):
    return await client.post("/api/ledger/imports", json={"filename": filename, "content_base64": b64(data), **extra})


NEW_CARD = {"name": "Synthetic card", "account_type": "CREDIT", "subtype": "CREDIT_CARD"}


async def commit_csv(client, data=JUNE, period=(MONTH, MONTH_END), **extra):
    mapping = (await preview(client, data)).json()["mapping"]
    target = {"source_id": extra.pop("source_id")} if "source_id" in extra else {"new_account": NEW_CARD}
    return await commit(client, data, mapping=mapping, period={"start": str(period[0]), "end": str(period[1])},
                        **target, **extra)


async def months_for(client, source_id):
    body = (await client.get("/api/ledger/months", params={"source_ids": [source_id]})).json()
    return {m["month"]: m for m in body["months"]}


# --- CSV ----------------------------------------------------------------------

async def test_csv_preview_suggests_mapping_categories_and_period(client, transactions_on):
    response = await preview(client, JUNE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "csv" and body["previous_import_id"] is None and body["statements"] == []
    assert [c["suggested_role"] for c in body["csv"]["columns"]] == ["date", "description", "amount", "category"]
    assert body["csv"]["sign"]["convention"] == "inflows_positive"
    assert body["mapping"] == body["csv"]["suggested_mapping"]
    parsed = body["parsed"]
    assert parsed["transaction_count"] == 6 and parsed["existing_count"] is None and parsed["issue_count"] == 0
    # Sample rows as they would import: a purchase leaves the account (positive).
    assert parsed["rows"][0]["amount"] == 80.0 and parsed["rows"][3]["amount"] == -2000.0
    categories = {c["value"]: c for c in body["categories"]}
    assert categories["Groceries"]["suggested"] == "groceries" and categories["Groceries"]["suggested_source"] == "alias"
    assert categories["Zeta stuff"]["suggested"] is None and categories["Groceries"]["count"] == 2
    assert body["period"] == {"suggested": {"start": str(day(MONTH, 1)), "end": str(day(MONTH, 25))},
                              "earliest": str(MONTH), "latest": str(MONTH_END)}
    assert body["parse_error"] is None


async def test_csv_commit_creates_account_rows_rules_and_complete_month(client, transactions_on, db_session, test_user):
    response = await commit_csv(client, categories=[{"value": "Zeta stuff", "category": "shopping"},
                                                    {"value": "Groceries", "category": "groceries"}])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created_account"] and body["inserted"] == 6 and body["existing"] == 0 and body["rules_saved"] == 1
    assert body["account"]["provider"] == "file" and body["account"]["transaction_count"] == 6
    assert body["account"]["coverage"] == [{"start": str(MONTH), "end": str(MONTH_END)}]
    record = body["import"]
    assert record["status"] == "committed" and record["format"] == "csv" and record["transaction_count"] == 6
    assert (record["date_from"], record["date_to"]) == (str(MONTH), str(MONTH_END))
    source = db_session.get(FinancialSource, uuid.UUID(body["account"]["id"]))
    assert source.environment == "production" and source.provider_account_id.startswith("csv-")
    saved = db_session.get(FinancialImport, uuid.UUID(record["id"]))
    assert saved.mapping["date_format"] == "%Y-%m-%d" and len(saved.file_sha256) == 64
    rules = db_session.query(FinancialRule).filter_by(user_id=test_user.id).all()
    assert [(r.match_field, r.match_type, r.pattern, r.category, r.source_id) for r in rules] == [
        ("provider_category", "equals", "zeta stuff", "shopping", source.id)]
    month = (await months_for(client, str(source.id)))[KEY]
    assert month["complete"] and month["by_category"]["shopping"] == 40.0
    assert month["essential"] == 140.0 and month["discretionary"] == 65.5 and month["income"] == 4000.0
    # Rows carry the account currency; the filename is kept without any path.
    assert {row.currency for row in db_session.query(FinancialTransaction)} == {"USD"}
    history = (await client.get("/api/ledger/imports", params={"source_id": str(source.id)})).json()
    assert [item["id"] for item in history] == [record["id"]]


async def test_reimport_counts_duplicates_and_refuses_the_same_file(client, transactions_on, db_session):
    first = (await commit_csv(client)).json()
    source_id = first["account"]["id"]
    again = (await preview(client, JUNE, source_id=source_id)).json()
    assert again["parsed"]["existing_count"] == 6 and again["previous_import_id"] == first["import"]["id"]
    refused = await commit_csv(client, source_id=source_id)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ALREADY_IMPORTED"
    # An overlapping statement: two rows repeat, one is new; whole previous month plus this one.
    overlap = csv_file([(day(PREV, 3), "Synthetic Fuel", "-30.00", "Gas"), *JUNE_ROWS[:2],
                        (day(MONTH, 27), "Synthetic Books", "-12.00", "Zeta stuff")])
    result = await commit_csv(client, overlap, period=(PREV, MONTH_END), source_id=source_id)
    assert result.status_code == 201, result.text
    body = result.json()
    assert (body["inserted"], body["existing"], body["created_account"]) == (2, 2, False)
    assert body["import"]["duplicate_count"] == 2 and body["import"]["imported_count"] == 2
    assert db_session.query(FinancialTransaction).count() == 8
    months = await months_for(client, source_id)
    assert months[PREV_KEY]["complete"] and months[KEY]["complete"]


async def test_revert_reassigns_overlapping_rows_and_removes_coverage(client, transactions_on, db_session):
    first = (await commit_csv(client)).json()
    source_id = first["account"]["id"]
    second_rows = JUNE_ROWS[3:] + [(day(MONTH, 27), "Synthetic Books", "-12.00", "Books")]
    second = (await commit_csv(client, csv_file(second_rows), period=(day(MONTH, 14), MONTH_END),
                               source_id=source_id)).json()
    assert second["inserted"] == 1 and second["existing"] == 3
    reverted = await client.delete(f"/api/ledger/imports/{first['import']['id']}")
    assert reverted.status_code == 200, reverted.text
    body = reverted.json()
    # Rows dated inside the second statement move to it; the rest go.
    assert (body["removed"], body["reassigned"]) == (3, 3)
    assert body["import"]["status"] == "reverted" and body["import"]["reverted_at"] and body["import"]["transaction_count"] == 0
    assert db_session.query(FinancialTransaction).count() == 4
    months = await months_for(client, source_id)
    assert not months[KEY]["complete"]
    assert {r["code"] for r in months[KEY]["reasons"]} == {"partial_coverage"}
    history = {item["id"]: item for item in (await client.get("/api/ledger/imports")).json()}
    assert history[second["import"]["id"]]["transaction_count"] == 4
    again = await client.delete(f"/api/ledger/imports/{first['import']['id']}")
    assert again.status_code == 409 and again.json()["error"]["code"] == "CONFLICT"
    await client.delete(f"/api/ledger/imports/{second['import']['id']}")
    assert db_session.query(FinancialTransaction).count() == 0
    assert await months_for(client, source_id) == {}


async def test_partial_period_leaves_the_month_incomplete(client, transactions_on):
    body = (await commit_csv(client, period=(day(MONTH, 1), day(MONTH, 25)))).json()
    month = (await months_for(client, body["account"]["id"]))[KEY]
    assert not month["complete"] and month["reasons"] == [{"code": "partial_coverage", "source_ids": [body["account"]["id"]]}]


@pytest.mark.parametrize("period, reason", [
    ((day(MONTH, 2), MONTH_END), "rows_outside"),
    ((MONTH, day(MONTH, 24)), "rows_outside"),
    ((MONTH - timedelta(days=1), MONTH_END), "beyond_file"),
    ((MONTH, MONTH_END + timedelta(days=1)), "beyond_file"),
    ((MONTH_END, MONTH), "order"),
])
async def test_period_must_hold_the_file_and_stay_in_its_months(client, transactions_on, period, reason):
    response = await commit_csv(client, period=period)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_PERIOD" and error["details"] == [{"field": "period", "reason": reason}]


async def test_period_never_reaches_past_today(client, transactions_on):
    rows = [(TODAY.replace(day=1), "Synthetic Grocer", "-5.00", "Groceries")]
    body = (await preview(client, csv_file(rows))).json()
    assert body["period"]["latest"] == str(min(file_imports.month_end(TODAY), TODAY))


async def test_commit_requires_mapping_period_and_known_target(client, transactions_on, db_session, test_user):
    mapping = (await preview(client, JUNE)).json()["mapping"]
    no_mapping = await commit(client, JUNE, new_account=NEW_CARD, period={"start": str(MONTH), "end": str(MONTH_END)})
    assert no_mapping.status_code == 422 and no_mapping.json()["error"]["details"][0]["field"] == "mapping"
    no_period = await commit(client, JUNE, new_account=NEW_CARD, mapping=mapping)
    assert no_period.json()["error"]["details"][0]["field"] == "period"
    both = await commit(client, JUNE, new_account=NEW_CARD, source_id=str(uuid.uuid4()), mapping=mapping)
    assert both.status_code == 422 and both.json()["error"]["code"] == "VALIDATION_ERROR"
    missing = await commit(client, JUNE, source_id=str(uuid.uuid4()), mapping=mapping,
                           period={"start": str(MONTH), "end": str(MONTH_END)})
    assert missing.status_code == 404
    synced = make_source(db_session, test_user, provider="simplefin", external="sf-1")
    stranger = make_source(db_session, other_user(db_session), external="file-x")
    db_session.commit()
    wrong = await commit(client, JUNE, source_id=str(synced.id), mapping=mapping,
                         period={"start": str(MONTH), "end": str(MONTH_END)})
    assert wrong.status_code == 422 and wrong.json()["error"]["details"][0]["field"] == "source_id"
    theirs = await preview(client, JUNE, source_id=str(stranger.id))
    assert theirs.status_code == 404
    bad_mapping = await commit(client, JUNE, new_account=NEW_CARD, mapping={**mapping, "date_column": 9},
                               period={"start": str(MONTH), "end": str(MONTH_END)})
    assert bad_mapping.status_code == 422 and bad_mapping.json()["error"]["code"] == "INVALID_MAPPING"
    assert db_session.query(FinancialSource).filter_by(user_id=test_user.id, provider="file").count() == 0


async def test_ambiguous_dates_need_a_chosen_format(client, transactions_on):
    data = b"Date,Description,Amount\n03/04/2026,Synthetic Grocer,-10.00\n05/06/2026,Synthetic Diner,-4.00\n"
    body = (await preview(client, data)).json()
    assert body["csv"]["date_ambiguous"] and body["parsed"] is None
    assert body["parse_error"]["code"] == "INVALID_MAPPING" and body["parse_error"]["field"] == "date_format"
    assert body["categories"] == [] and body["period"] is None
    chosen = (await preview(client, data, mapping={**body["mapping"], "date_format": "%d/%m/%Y"})).json()
    assert chosen["parse_error"] is None and chosen["parsed"]["date_from"] == "2026-04-03"
    unknown = (await preview(client, data, mapping={"delimiter": ","})).json()
    assert unknown["parse_error"]["code"] == "INVALID_MAPPING" and unknown["parse_error"]["field"] is None


async def test_csv_without_suggested_mapping(client, transactions_on):
    data = b"Memo,Note\nSynthetic,one\nSynthetic,two\n"
    body = (await preview(client, data)).json()
    assert body["mapping"] is None and body["parse_error"]["message"] == "Choose the date and amount columns."


@pytest.mark.parametrize("header,fmt", [("Posting Date", "%m/%d/%Y"), ("Posted", "%d-%b-%Y")])
async def test_posted_date_only_files_preview_and_import(client, transactions_on, db_session, header, fmt):
    first, second = day(MONTH, 13), day(MONTH, 20)
    lines = [f"{header},Memo,Amount"] + [f"{when.strftime(fmt)},{text},{amount}" for when, text, amount in (
        (first, "Synthetic Grocer", "-12.00"), (second, "Synthetic Diner", "-8.00"))]
    data = ("\n".join(lines) + "\n").encode()
    body = (await preview(client, data)).json()
    assert body["parse_error"] is None and body["mapping"]["date_column"] == 0
    assert [c["format"] for c in body["csv"]["date_formats"]] == [fmt]
    assert (body["parsed"]["date_from"], body["parsed"]["date_to"]) == (str(first), str(second))
    response = await commit_csv(client, data)
    assert response.status_code == 201, response.text
    assert response.json()["inserted"] == 2
    assert sorted(r.transaction_date for r in db_session.query(FinancialTransaction)) == [first, second]


async def test_remapped_date_column_gets_its_own_formats(client, transactions_on):
    # The customer moves the date from the transaction date (ISO) to the posting date (US order).
    data = (b"Transaction Date,Posting Date,Description,Amount\n"
            b"2026-03-01,03/14/2026,Synthetic Grocer,-1.00\n2026-03-02,03/15/2026,Synthetic Diner,-2.00\n")
    body = (await preview(client, data)).json()
    assert [c["label"] for c in body["csv"]["date_formats"]] == ["YYYY-MM-DD"]
    moved = {**body["mapping"], "date_column": 1, "posted_date_column": 0}
    remapped = (await preview(client, data, mapping=moved)).json()
    assert [c["label"] for c in remapped["csv"]["date_formats"]] == ["MM/DD/YYYY"]
    assert remapped["mapping"]["date_format"] == "%m/%d/%Y" and remapped["parse_error"] is None
    assert remapped["parsed"]["date_from"] == "2026-03-14"
    # A posting date that reads both ways is never guessed.
    ambiguous = data.replace(b"03/14/2026", b"03/04/2026").replace(b"03/15/2026", b"03/05/2026")
    remapped = (await preview(client, ambiguous, mapping=moved)).json()
    assert remapped["csv"]["date_ambiguous"] and remapped["mapping"]["date_format"] is None
    assert [c["label"] for c in remapped["csv"]["date_formats"]] == ["MM/DD/YYYY", "DD/MM/YYYY"]
    assert remapped["parse_error"]["field"] == "date_format"
    # A chosen format that fits the column stays.
    chosen = (await preview(client, ambiguous, mapping={**moved, "date_format": "%d/%m/%Y"})).json()
    assert chosen["mapping"]["date_format"] == "%d/%m/%Y" and chosen["parsed"]["date_from"] == "2026-04-03"


async def test_dates_that_fit_no_format_name_the_column(client, transactions_on):
    data = b"Posted,Description,Amount\nsoon,Synthetic Grocer,-1.00\nlater,Synthetic Diner,-2.00\n"
    body = (await preview(client, data)).json()
    assert body["mapping"] is None and body["csv"]["date_formats"] == []
    assert body["parse_error"] == {"code": "INVALID_MAPPING", "message": "Dates in “Posted” match no supported format.",
                                   "field": "date_column"}
    good = b"Date,Description,Amount\n2026-03-01,Synthetic Grocer,-1.00\n2026-03-02,Synthetic Diner,-2.00\n"
    mapping = (await preview(client, good)).json()["mapping"]
    remapped = (await preview(client, good, mapping={**mapping, "date_column": 1, "description_columns": [0]})).json()
    assert remapped["csv"]["date_formats"] == [] and remapped["parsed"] is None
    assert remapped["parse_error"]["message"] == "Dates in “Description” match no supported format."


async def test_pending_rows_that_posted_with_a_new_amount_are_replaced(client, transactions_on, db_session):
    rows = [(day(MONTH, 2), "Synthetic Grocer", "-10.00", "Groceries"),
            (day(MONTH, 26), "Synthetic Diner", "-20.00", "Restaurants")]
    first = (await commit_csv(client, csv_file(rows, status=["Posted", "Pending"]))).json()
    assert db_session.query(FinancialTransaction).filter_by(status="PENDING").count() == 1
    posted = [rows[0], (day(MONTH, 26), "Synthetic Diner", "-24.00", "Restaurants")]
    body = (await commit_csv(client, csv_file(posted, status=["Posted", "Posted"]),
                             source_id=first["account"]["id"])).json()
    assert (body["inserted"], body["existing"], body["removed"]) == (1, 1, 1)
    amounts = sorted(float(r.amount) for r in db_session.query(FinancialTransaction))
    assert amounts == [10.0, 24.0]


async def test_category_rules_follow_existing_choices(client, transactions_on, db_session, test_user):
    first = (await commit_csv(client, categories=[{"value": "Zeta stuff", "category": "shopping"}])).json()
    source_id = first["account"]["id"]
    later = csv_file([(day(MONTH, 3), "Synthetic Widgets", "-9.00", "Zeta stuff")])
    body = (await preview(client, later, source_id=source_id)).json()
    assert body["categories"] == [{"value": "Zeta stuff", "count": 1, "suggested": "shopping", "suggested_source": "rule"}]
    # Without a target account, account-scoped rules do not apply.
    assert (await preview(client, later)).json()["categories"][0]["suggested"] is None
    # A new choice for the same value updates the account's rule rather than adding one.
    changed = (await commit_csv(client, later, source_id=source_id,
                                categories=[{"value": "Zeta stuff", "category": "gifts_donations"},
                                            {"value": "Unmapped", "category": "uncategorized"}])).json()
    assert changed["rules_saved"] == 1
    rules = db_session.query(FinancialRule).filter_by(user_id=test_user.id).all()
    assert [(r.pattern, r.category) for r in rules] == [("zeta stuff", "gifts_donations")]


async def test_rule_limit_refuses_new_category_rules(client, transactions_on, monkeypatch):
    monkeypatch.setattr(file_imports, "MAX_RULES", 0)
    response = await commit_csv(client, categories=[{"value": "Zeta stuff", "category": "shopping"}])
    assert response.status_code == 422 and "unused rule" in response.json()["error"]["message"]


async def test_rows_older_than_retention_are_skipped(client, transactions_on, db_session):
    old = TODAY - timedelta(days=800)
    rows = [(old, "Synthetic Grocer", "-5.00", "Groceries"), (day(MONTH, 2), "Synthetic Diner", "-6.00", "Dining")]
    cutoff = str(TODAY - timedelta(days=760))
    shown = (await preview(client, csv_file(rows))).json()
    assert shown["parsed"]["transaction_count"] == 2 and shown["parsed"]["before_retention"] == 1
    assert shown["retention_start"] == cutoff
    body = (await commit_csv(client, csv_file(rows), period=(old.replace(day=1), MONTH_END))).json()
    assert (body["inserted"], body["skipped"]) == (1, 1)
    assert (body["before_retention"], body["retention_start"]) == (1, cutoff)
    assert body["import"]["skipped_count"] == 1


# --- OFX ----------------------------------------------------------------------

def ofx(statements: str) -> bytes:
    header = ("OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:USASCII\nCHARSET:1252\n"
              "COMPRESSION:NONE\nOLDFILEUID:NONE\nNEWFILEUID:NONE\n\n")
    signon = ("<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>20260201120000"
              "<LANGUAGE>ENG<FI><ORG>Example Credit Union<FID>9999</FI></SONRS></SIGNONMSGSRSV1>")
    return (header + "<OFX>" + signon + statements + "</OFX>").encode()


def stamp(value: date) -> str:
    return value.strftime("%Y%m%d")


def trn(fitid: str, amount: str, when: date, name: str = "SYNTHETIC SHOP", **extra: str) -> str:
    parts = [f"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>{stamp(when)}<TRNAMT>{amount}<FITID>{fitid}<NAME>{name}"]
    parts += [f"<{key.upper()}>{value}" for key, value in extra.items()]
    return "".join(parts) + "</STMTTRN>\n"


def bank(transactions: str, *, acct="000012345678", start=MONTH, end=MONTH_END, currency="USD") -> str:
    return ("<BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS><STMTRS>"
            f"<CURDEF>{currency}<BANKACCTFROM><BANKID>000000000<ACCTID>{acct}<ACCTTYPE>CHECKING</BANKACCTFROM>"
            f"<BANKTRANLIST><DTSTART>{stamp(start)}<DTEND>{stamp(end)}\n{transactions}</BANKTRANLIST>"
            "</STMTRS></STMTTRNRS></BANKMSGSRSV1>")


def card(transactions: str, *, acct="4000000000001111") -> str:
    return ("<CREDITCARDMSGSRSV1><CCSTMTTRNRS><TRNUID>2<STATUS><CODE>0<SEVERITY>INFO</STATUS><CCSTMTRS><CURDEF>USD"
            f"<CCACCTFROM><ACCTID>{acct}</CCACCTFROM><BANKTRANLIST>\n{transactions}</BANKTRANLIST>"
            "</CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1>")


CHECKING = ofx(bank(trn("F1", "-42.00", day(MONTH, 3)) + trn("F2", "1500.00", day(MONTH, 15), "PAYROLL")))
NEW_CHECKING = {"name": "Synthetic checking", "account_type": "DEPOSITORY", "subtype": "CHECKING"}


async def test_ofx_preview_and_commit_use_the_file_period(client, transactions_on, db_session):
    body = (await preview(client, CHECKING)).json()
    assert body["format"] == "ofx" and body["csv"] is None and body["parsed"] is None
    (statement,) = body["statements"]
    assert statement["account_type"] == "DEPOSITORY" and statement["mask"] == "5678"
    assert statement["period"] == {"start": str(MONTH), "end": str(MONTH_END)}
    assert statement["matched_source_id"] is None and statement["existing_count"] is None
    assert statement["before_retention"] == 0 and body["retention_start"] is not None
    assert statement["rows"][0]["amount"] == 42.0 and statement["institution_name"] == "Example Credit Union"
    result = await commit(client, CHECKING, filename="C:\\Downloads\\checking.qfx", new_account=NEW_CHECKING)
    assert result.status_code == 201, result.text
    created = result.json()
    assert created["inserted"] == 2 and created["import"]["filename"] == "checking.qfx"
    assert created["account"]["institution_name"] == "Example Credit Union" and created["account"]["mask"] == "5678"
    record = db_session.get(FinancialImport, uuid.UUID(created["import"]["id"]))
    assert record.mapping == {"statement_index": 0, "row_from": str(day(MONTH, 3)), "row_to": str(day(MONTH, 15))}
    assert (await months_for(client, created["account"]["id"]))[KEY]["complete"]
    matched = (await preview(client, CHECKING)).json()["statements"][0]
    assert matched["matched_source_id"] == created["account"]["id"] and matched["existing_count"] == 2
    again = await commit(client, CHECKING, new_account=NEW_CHECKING)
    assert again.status_code == 409 and again.json()["error"]["details"][0]["reason"] == created["account"]["id"]
    mapped = await preview(client, CHECKING, mapping={"delimiter": ","})
    assert mapped.status_code == 422 and mapped.json()["error"]["details"][0]["field"] == "mapping"


async def test_ofx_corrections_remove_stored_rows(client, transactions_on, db_session):
    first = (await commit(client, CHECKING, new_account=NEW_CHECKING)).json()
    correction = ofx(bank(trn("F3", "-50.00", day(MONTH, 3), correctfitid="F1", correctaction="REPLACE")))
    body = (await commit(client, correction, source_id=first["account"]["id"])).json()
    assert (body["inserted"], body["removed"]) == (1, 1)
    ids = sorted(r.provider_transaction_id.split(":")[1] for r in db_session.query(FinancialTransaction))
    assert ids == ["F2", "F3"]


async def test_ofx_with_two_accounts_needs_a_choice(client, transactions_on):
    data = ofx(bank(trn("B1", "-5.00", day(MONTH, 2))) + card(trn("C1", "-7.00", day(MONTH, 5))))
    statements = (await preview(client, data)).json()["statements"]
    assert [s["kind"] for s in statements] == ["bank", "credit_card"]
    # The card statement has no DTSTART/DTEND: its rows' dates stand in.
    assert statements[1]["period"] == {"start": str(day(MONTH, 5)), "end": str(day(MONTH, 5))}
    unchosen = await commit(client, data, new_account=NEW_CARD)
    assert unchosen.status_code == 422 and unchosen.json()["error"]["code"] == "STATEMENT_REQUIRED"
    outside = await commit(client, data, new_account=NEW_CARD, statement_index=5)
    assert outside.status_code == 422 and outside.json()["error"]["details"][0]["field"] == "statement_index"
    chosen = await commit(client, data, new_account={"name": "Card", "account_type": "CREDIT"}, statement_index=1)
    assert chosen.status_code == 201 and chosen.json()["account"]["currency"] == "USD"


async def test_ofx_statement_without_period_or_rows_is_refused(client, transactions_on):
    data = ofx(card(""))
    assert (await preview(client, data)).json()["statements"][0]["period"] is None
    response = await commit(client, data, new_account=NEW_CARD)
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_PERIOD"


# --- refusals, history, removal, feeds and the gate ---------------------------

async def test_unreadable_uploads_are_refused(client, transactions_on):
    bad = await client.post("/api/ledger/imports/preview", json={"filename": "x.csv", "content_base64": "%%%"})
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "content_base64"
    unknown = await preview(client, b"just some words without delimiters")
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "UNSUPPORTED_FORMAT"
    empty = await preview(client, b"   ")
    assert empty.json()["error"]["code"] == "EMPTY_FILE"
    header_only = await preview(client, b"Date,Description,Amount\n")
    assert header_only.json()["error"]["code"] == "NO_USABLE_ROWS"
    broken = await commit(client, ofx("<BANKMSGSRSV1></BANKMSGSRSV1>"), new_account=NEW_CARD)
    assert broken.json()["error"]["code"] == "NO_STATEMENTS"


def test_parser_errors_keep_field_names_only():
    error = file_imports.from_parser(ImportFileError("INVALID_MAPPING", "Choose a date format.", {"field": "date_format"}))
    assert error.details == [{"field": "date_format", "reason": "Choose a date format."}]
    limit = file_imports.from_parser(ImportFileError("FILE_TOO_LARGE", "Too large.", {"max_bytes": 10}))
    assert limit.details == [{"field": "max_bytes", "reason": "10"}] and limit.status == 422


def test_commit_needs_a_target(db_session, test_user):
    upload = file_imports.decode_upload(b64(CHECKING))
    with pytest.raises(file_imports.FileImportError) as caught:
        file_imports.commit_import(db_session, test_user.id, upload, "x.ofx", source_id=None, new_account=None,
                                   mapping=None, statement_index=None, period=None, categories=[])
    assert caught.value.details == [{"field": "source_id", "reason": "required"}]


def test_owned_range_widens_to_row_dates_and_ignores_bad_values():
    record = FinancialImport(date_from=MONTH, date_to=MONTH_END,
                             mapping={"row_from": str(day(MONTH, -3)), "row_to": "not a date"})
    assert file_imports.owned_range(record) == (day(MONTH, -3), MONTH_END)
    assert file_imports.owned_range(FinancialImport(date_from=MONTH, date_to=MONTH_END, mapping=None)) == (MONTH, MONTH_END)


async def test_history_and_revert_are_scoped_to_the_user(client, transactions_on, db_session):
    mine = (await commit_csv(client)).json()
    stranger = other_user(db_session)
    theirs = make_source(db_session, stranger, external="file-theirs")
    their_import = make_import(db_session, stranger, theirs, MONTH, MONTH_END)
    db_session.commit()
    history = (await client.get("/api/ledger/imports")).json()
    assert [item["id"] for item in history] == [mine["import"]["id"]]
    assert (await client.delete(f"/api/ledger/imports/{their_import.id}")).status_code == 404
    assert (await client.delete(f"/api/ledger/accounts/{theirs.id}")).status_code == 404
    assert db_session.get(FinancialImport, their_import.id).status == "committed"


async def test_delete_file_account_removes_everything(client, transactions_on, db_session, test_user):
    body = (await commit_csv(client, categories=[{"value": "Zeta stuff", "category": "shopping"}])).json()
    source_id = uuid.UUID(body["account"]["id"])
    kept = make_source(db_session, test_user, external="file-kept")
    make_txn(db_session, test_user, kept, 5, day(MONTH, 3))
    plan, feed = plan_with_feed(db_session, test_user, [source_id, kept.id])
    deleted = await client.delete(f"/api/ledger/accounts/{source_id}")
    assert deleted.status_code == 204
    db_session.expire_all()
    assert db_session.get(FinancialSource, source_id) is None
    assert db_session.query(FinancialTransaction).filter_by(source_id=source_id).count() == 0
    assert db_session.query(FinancialImport).filter_by(source_id=source_id).count() == 0
    assert db_session.query(FinancialRule).count() == 0
    assert db_session.get(FinancialSpendingFeed, feed.id).source_ids == [str(kept.id)]
    assert db_session.query(FinancialTransaction).filter_by(source_id=kept.id).count() == 1
    assert (await client.delete(f"/api/ledger/accounts/{source_id}")).status_code == 404
    synced = make_source(db_session, test_user, provider="simplefin", external="sf-2")
    db_session.commit()
    refused = await client.delete(f"/api/ledger/accounts/{synced.id}")
    assert refused.status_code == 422


async def test_a_repeated_commit_into_a_new_account_is_refused(client, transactions_on, db_session):
    first = await commit_csv(client)
    assert first.status_code == 201, first.text
    again = await commit_csv(client)
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_IMPORTED"
    assert again.json()["error"]["details"] == [{"field": "source_id", "reason": first.json()["account"]["id"]}]
    assert db_session.query(FinancialSource).count() == 1 and db_session.query(FinancialImport).count() == 1
    # Another file, or the same file into a differently named account, still imports.
    other = csv_file([(day(MONTH, 2), "Synthetic Fuel", "-30.00", "Gas")])
    assert (await commit_csv(client, other)).status_code == 201
    renamed = {**NEW_CARD, "name": "Synthetic second card"}
    mapping = (await preview(client, JUNE)).json()["mapping"]
    assert (await commit(client, JUNE, mapping=mapping, period={"start": str(MONTH), "end": str(MONTH_END)},
                         new_account=renamed)).status_code == 201
    # So does the same file once its import is reverted, and once the window has passed.
    await client.delete(f"/api/ledger/imports/{first.json()['import']['id']}")
    assert (await commit_csv(client)).status_code == 201
    db_session.query(FinancialImport).update({"created_at": utcnow() - file_imports.REPEAT_WINDOW * 2})
    db_session.commit()
    assert (await commit_csv(client)).status_code == 201


def test_concurrent_commits_of_one_file_create_one_account(tmp_path):
    """Two simultaneous commits of one file into a new account, on a self-hosted SQLite file."""
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'race.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    install_python_defaults(sessions)
    try:
        with sessions() as db:
            user = User(is_anonymous=True, settings={}, created_at=datetime.now(UTC))
            db.add(user)
            db.commit()
            user_id = user.id
            upload = file_imports.decode_upload(b64(JUNE))
            mapping = file_imports.preview_import(db, user_id, upload, source_id=None, mapping=None)["mapping"]
        start = threading.Barrier(2)

        def attempt() -> str:
            with sessions() as db:
                start.wait()
                lock_user(db, user_id)
                try:
                    file_imports.commit_import(
                        db, user_id, upload, "statement.csv", source_id=None,
                        new_account=file_imports.NewAccount(**NEW_CARD), mapping=mapping, statement_index=None,
                        period=(MONTH, MONTH_END), categories=[])
                except file_imports.FileImportError as error:
                    db.rollback()
                    return error.code
                db.commit()
                return "committed"

        with ThreadPoolExecutor(2) as pool:
            outcomes = sorted(future.result() for future in [pool.submit(attempt), pool.submit(attempt)])
        assert outcomes == ["ALREADY_IMPORTED", "committed"]
        with sessions() as db:
            assert db.query(FinancialSource).count() == 1
            assert db.query(FinancialTransaction).count() == len(JUNE_ROWS)
    finally:
        engine.dispose()


async def test_revert_removes_the_account_it_created_when_asked(client, transactions_on, db_session, test_user):
    body = (await commit_csv(client)).json()
    source_id = uuid.UUID(body["account"]["id"])
    assert body["import"]["revert_removes_account"]
    history = (await client.get("/api/ledger/imports")).json()
    assert [item["revert_removes_account"] for item in history] == [True]
    plan, feed = plan_with_feed(db_session, test_user, [source_id])
    reverted = await client.delete(f"/api/ledger/imports/{body['import']['id']}", params={"remove_account": True})
    assert reverted.status_code == 200, reverted.text
    result = reverted.json()
    assert result["account_removed"] and result["removed"] == len(JUNE_ROWS)
    assert result["import"]["status"] == "reverted" and not result["import"]["revert_removes_account"]
    db_session.expire_all()
    assert db_session.get(FinancialSource, source_id) is None
    assert db_session.query(FinancialImport).count() == db_session.query(FinancialTransaction).count() == 0
    assert db_session.get(FinancialSpendingFeed, feed.id).source_ids == []
    assert (await client.get("/api/ledger/accounts")).json() == []


async def test_revert_keeps_accounts_with_other_data(client, transactions_on, db_session, test_user):
    # Without the option the account stays, as older clients expect.
    lone = (await commit_csv(client)).json()
    kept = await client.delete(f"/api/ledger/imports/{lone['import']['id']}")
    assert kept.status_code == 200 and not kept.json()["account_removed"]
    assert db_session.get(FinancialSource, uuid.UUID(lone["account"]["id"])) is not None
    # A second import into the account: neither revert removes it.
    other = csv_file([(day(MONTH, 2), "Synthetic Fuel", "-30.00", "Gas")])
    first = (await commit_csv(client, other)).json()
    source_id = first["account"]["id"]
    second = (await commit_csv(client, period=(MONTH, MONTH_END), source_id=source_id)).json()
    history = {item["id"]: item for item in (await client.get("/api/ledger/imports")).json()}
    assert not history[first["import"]["id"]]["revert_removes_account"]
    assert not history[second["import"]["id"]]["revert_removes_account"]
    for record in (first, second):
        result = await client.delete(f"/api/ledger/imports/{record['import']['id']}", params={"remove_account": True})
        assert result.status_code == 200 and not result.json()["account_removed"]
    assert db_session.get(FinancialSource, uuid.UUID(source_id)) is not None
    # An account whose balance a plan account reads stays too.
    linked = (await commit_csv(client, csv_file([(day(MONTH, 3), "Synthetic Books", "-12.00", "Books")]))).json()
    plan, _ = plan_with_feed(db_session, test_user, [])
    savings = CurrentAccount(user_id=test_user.id, plan_id=plan.id, name="Synthetic savings", account_type="savings",
                             balance=5)
    db_session.add(savings)
    db_session.flush()
    db_session.add(FinancialBalanceLink(user_id=test_user.id, source_id=uuid.UUID(linked["account"]["id"]),
                                        plan_id=plan.id, account_id=savings.id, last_applied_balance=5,
                                        source_revision=1, source_type="CREDIT"))
    db_session.commit()
    history = {item["id"]: item for item in (await client.get("/api/ledger/imports")).json()}
    assert not history[linked["import"]["id"]]["revert_removes_account"]
    result = await client.delete(f"/api/ledger/imports/{linked['import']['id']}", params={"remove_account": True})
    assert result.status_code == 200 and not result.json()["account_removed"]
    assert db_session.get(FinancialSource, uuid.UUID(linked["account"]["id"])) is not None


async def test_imports_and_reverts_reapply_feeds(client, transactions_on, db_session, test_user, monkeypatch):
    first = (await commit_csv(client)).json()
    source_id = uuid.UUID(first["account"]["id"])
    _, feed = plan_with_feed(db_session, test_user, [source_id])
    feed.error = "stale"
    db_session.commit()
    calls = []
    original = file_imports.refresh_feeds

    def spy(db, user_id, source_ids):
        calls.append(set(source_ids))
        return original(db, user_id, source_ids)

    monkeypatch.setattr(file_imports, "refresh_feeds", spy)
    later = csv_file([(day(MONTH, 3), "Synthetic Widgets", "-9.00", "Gifts")])
    await commit_csv(client, later, source_id=str(source_id))
    db_session.refresh(feed)
    assert feed.error is None and calls == [{str(source_id)}]
    await client.delete(f"/api/ledger/imports/{first['import']['id']}")
    assert calls[-1] == {str(source_id)}


async def test_gate_refuses_changes_but_keeps_history_revert_and_removal(client, db_session, test_user, monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "true")
    body = (await commit_csv(client)).json()
    monkeypatch.setenv("TRANSACTIONS_ENABLED", "false")
    for response in (await preview(client, JUNE), await commit(client, JUNE, new_account=NEW_CARD)):
        assert response.status_code == 503 and response.json()["error"]["code"] == "FEATURE_DISABLED"
    assert (await client.get("/api/ledger/imports")).status_code == 200
    assert (await client.delete(f"/api/ledger/imports/{body['import']['id']}")).status_code == 200
    assert (await client.delete(f"/api/ledger/accounts/{body['account']['id']}")).status_code == 204


async def test_uploads_get_a_larger_body_limit_than_other_routes(client, transactions_on):
    middleware = BodySizeLimitMiddleware(None)
    assert middleware.limit_for("/api/ledger/imports") == 15 * MIB
    assert middleware.limit_for("/api/ledger/imports/preview") == 15 * MIB
    assert middleware.limit_for("/api/ledger/rules") == 2 * MIB
    # A full-size file in base64 fits; anything larger is refused before parsing.
    assert len(b64(b"x" * (10 * MIB))) <= 15 * MIB - 4096
    oversized = await client.post("/api/ledger/imports/preview", content=b"{" + b" " * (15 * MIB) + b"}",
                                  headers={"content-type": "application/json"})
    assert oversized.status_code == 413 and oversized.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    too_long = await client.post("/api/ledger/imports/preview", json={
        "filename": "x.csv", "content_base64": "A" * (file_imports_max() + 4)})
    assert too_long.status_code == 422


def file_imports_max() -> int:
    return MAX_BASE64_LENGTH


async def test_unauthenticated_requests_are_refused(client, transactions_on):
    client.cookies.clear()
    assert (await client.get("/api/ledger/imports")).status_code == 401
    assert (await preview(client, JUNE)).status_code == 401
