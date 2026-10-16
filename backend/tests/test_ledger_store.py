"""The provider-neutral transaction store."""
from datetime import date, timedelta
from decimal import Decimal

from app.ledger.store import remove_transactions, stored_id, upsert_transactions
from app.models.financial_connection import FinancialTransaction
from tests.ledger_fixture import make_import, make_source, normalized, plugin_provider

TODAY = date(2026, 9, 20)


def rows(db, source):
    return {row.provider_transaction_id: row for row in db.query(FinancialTransaction).filter_by(source_id=source.id)}


def test_ids_are_scoped_to_the_account_unless_a_plugin_keeps_raw_ids(db_session, test_user, monkeypatch):
    file_source = make_source(db_session, test_user, external="acct-1")
    raw = plugin_provider(monkeypatch, raw_transaction_ids=True)
    raw_source = make_source(db_session, test_user, provider=raw, environment="sandbox", external="m1")
    assert stored_id(file_source, "fit-9") == "acct-1:fit-9"
    assert stored_id(raw_source, "raw") == "raw"
    long_id = stored_id(file_source, "x" * 300)
    assert long_id.startswith("sha256:") and len(long_id) == 71


def test_insert_update_unchanged_skipped_duplicate_and_import_stamp(db_session, test_user):
    source = make_source(db_session, test_user)
    imported = make_import(db_session, test_user, source, date(2026, 9, 1), date(2026, 9, 10))
    first = upsert_transactions(db_session, source, [
        normalized("a", "12.345", date(2026, 9, 2), merchant_name="  Synthetic   Grocer ", provider_category="Groceries",
                   currency="usd-long-currency-code"),
        normalized("a", "12.34", date(2026, 9, 2)),
        normalized("bad", Decimal("NaN"), date(2026, 9, 2)),
        normalized("huge", Decimal("1e14"), date(2026, 9, 2)),
        normalized("b", "-5", date(2026, 9, 3), description="   "),
    ], import_id=imported.id, today=TODAY)
    assert (first.inserted, first.duplicates, first.skipped) == (2, 1, 2)
    assert first.inserted_ids == ["acct-1:a", "acct-1:b"]
    saved = rows(db_session, source)
    assert saved["acct-1:a"].amount == Decimal("12.34") and saved["acct-1:a"].merchant_name == "Synthetic Grocer"
    assert saved["acct-1:a"].currency == "usd-long-c" and saved["acct-1:a"].import_id == imported.id
    assert saved["acct-1:b"].description == "Transaction" and saved["acct-1:b"].provider == "file"
    saved["acct-1:a"].category_override, saved["acct-1:a"].excluded, saved["acct-1:a"].one_time = "dining", True, True
    db_session.flush()
    second = upsert_transactions(db_session, source, [
        normalized("a", "13", date(2026, 9, 2), description="Renamed"),
        normalized("b", "-5", date(2026, 9, 3), description=""),
    ], today=TODAY)
    assert (second.inserted, second.updated, second.unchanged) == (0, 1, 1)
    row = rows(db_session, source)["acct-1:a"]
    # Corrections survive provider updates; later reads never re-stamp the import.
    assert (row.amount, row.description, row.category_override, row.excluded, row.one_time) == (
        Decimal("13.00"), "Renamed", "dining", True, True)
    assert row.import_id == imported.id


def test_window_reconcile_removes_vanished_rows_away_from_the_start_edge(db_session, test_user):
    source = make_source(db_session, test_user)
    start, end = date(2026, 8, 1), date(2026, 9, 1)
    upsert_transactions(db_session, source, [normalized(x, 10, d) for x, d in (
        ("edge", date(2026, 8, 2)), ("gone", date(2026, 8, 15)), ("kept", date(2026, 8, 16)),
        ("unusable", date(2026, 8, 17)), ("after", date(2026, 9, 5)))], today=TODAY)
    result = upsert_transactions(db_session, source, [normalized("kept", 10, date(2026, 8, 16))],
                                 window=(start, end), unusable_ids=["unusable"], today=TODAY)
    assert result.removed == 1 and result.skipped == 1
    assert set(rows(db_session, source)) == {"acct-1:edge", "acct-1:kept", "acct-1:unusable", "acct-1:after"}


def test_posted_replaces_pending_and_inherits_corrections(db_session, test_user):
    source = make_source(db_session, test_user)
    upsert_transactions(db_session, source, [normalized("p1", 20, date(2026, 9, 5), status="PENDING"),
                                             normalized("p2", 30, date(2026, 9, 6), status="PENDING"),
                                             normalized("posted2", 30, date(2026, 9, 7))], today=TODAY)
    saved = rows(db_session, source)
    saved["acct-1:p1"].category_override = "travel"
    saved["acct-1:p2"].excluded = True
    db_session.flush()
    result = upsert_transactions(db_session, source, [
        normalized("posted1", 21, date(2026, 9, 6), pending_external_id="p1"),
        normalized("posted2", 30, date(2026, 9, 7), pending_external_id="p2"),
        normalized("self", 5, date(2026, 9, 7), pending_external_id="self"),
    ], today=TODAY)
    assert result.updated == 2 and result.inserted == 1
    saved = rows(db_session, source)
    assert set(saved) == {"acct-1:posted1", "acct-1:posted2", "acct-1:self"}
    assert saved["acct-1:posted1"].category_override == "travel" and saved["acct-1:posted1"].status == "POSTED"
    assert saved["acct-1:posted2"].excluded is True


def test_retention_prunes_old_rows_and_removal_by_external_id(db_session, test_user):
    source = make_source(db_session, test_user)
    upsert_transactions(db_session, source, [normalized("old", 1, TODAY - timedelta(days=761)),
                                             normalized("r1", 1, TODAY), normalized("r2", 1, TODAY)], today=TODAY)
    assert set(rows(db_session, source)) == {"acct-1:r1", "acct-1:r2"}
    assert remove_transactions(db_session, source, ["r1", "r1", "missing"]) == 1
    assert set(rows(db_session, source)) == {"acct-1:r2"}
