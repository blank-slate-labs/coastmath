"""Month summaries: coverage, settle, completeness, duplicates and model amounts."""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.ledger.classify import LedgerTxn
from app.ledger.months import (
    MonthSelectionError,
    MonthSummary,
    covers,
    merge_intervals,
    model_amounts,
    month_summaries,
    trailing_summary,
)
from tests.ledger_fixture import make_import, make_source, make_txn

TODAY = date(2026, 10, 10)
D = Decimal


def by_month(result):
    return {month.month: month for month in result.months}


def test_interval_helpers():
    assert merge_intervals([(date(2026, 1, 10), date(2026, 1, 20)), (date(2026, 1, 1), date(2026, 1, 9)),
                            (date(2026, 2, 5), date(2026, 2, 1))]) == [(date(2026, 1, 1), date(2026, 1, 20))]
    assert covers([(date(2026, 1, 1), date(2026, 1, 31))], date(2026, 1, 1), date(2026, 1, 31))
    assert not covers([], date(2026, 1, 1), date(2026, 1, 2))


def test_file_coverage_is_the_union_of_imports_and_gaps_matter(db_session, test_user):
    card = make_source(db_session, test_user)
    make_import(db_session, test_user, card, date(2026, 7, 1), date(2026, 7, 15))
    make_import(db_session, test_user, card, date(2026, 7, 16), date(2026, 7, 31))
    make_import(db_session, test_user, card, date(2026, 8, 1), date(2026, 8, 20))
    make_import(db_session, test_user, card, date(2026, 8, 25), date(2026, 9, 30))
    make_import(db_session, test_user, card, date(2026, 5, 1), date(2026, 5, 31), status="reverted")
    months = by_month(month_summaries(db_session, test_user.id, today=TODAY))
    assert list(months) == ["2026-07", "2026-08", "2026-09"]
    assert months["2026-07"].complete and months["2026-07"].reasons == []
    assert months["2026-08"].reasons == [{"code": "partial_coverage", "source_ids": [str(card.id)]}]
    # Files need no settle delay.
    assert months["2026-09"].complete


def test_synced_coverage_settles_and_the_current_month_is_in_progress(db_session, test_user):
    card = make_source(db_session, test_user, provider="simplefin", coverage_start=date(2026, 6, 15),
                       synced_at=datetime(2026, 10, 4, 12, tzinfo=UTC))
    months = by_month(month_summaries(db_session, test_user.id, today=TODAY))
    assert list(months) == ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert months["2026-06"].reasons[0]["code"] == "partial_coverage"
    assert months["2026-07"].complete and months["2026-08"].complete
    assert months["2026-09"].reasons == [{"code": "settling", "source_ids": [str(card.id)]}]
    assert months["2026-10"].reasons == [{"code": "in_progress", "source_ids": []}]


def test_waiting_source_blocks_every_month_and_no_sources_means_no_months(db_session, test_user):
    card = make_source(db_session, test_user)
    make_import(db_session, test_user, card, date(2026, 8, 1), date(2026, 8, 31))
    loading = make_source(db_session, test_user, provider="simplefin", external="acct-2", account_type="DEPOSITORY",
                          subtype="CHECKING")
    months = by_month(month_summaries(db_session, test_user.id, today=TODAY))
    assert months["2026-08"].reasons == [{"code": "waiting_for_history", "source_ids": [str(loading.id)]}]
    assert month_summaries(db_session, test_user.id, source_ids=[], today=TODAY).months == []


def test_retention_and_inactive_environments(db_session, test_user, monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "production")
    card = make_source(db_session, test_user)
    make_import(db_session, test_user, card, date(2024, 1, 1), date(2026, 9, 30))
    sandbox = make_source(db_session, test_user, provider="plaid", environment="sandbox", external="p1",
                          coverage_start=date(2026, 1, 1), synced_at=datetime(2026, 10, 1, tzinfo=UTC))
    result = month_summaries(db_session, test_user.id, today=TODAY)
    # 760 days before 2026-10-10 is 2024-09-10: the first month fully inside retention is October 2024.
    assert result.months[0].month == "2024-10" and result.months[-1].month == "2026-09"
    assert [c.source_id for c in result.sources] == [str(card.id)]
    assert month_summaries(db_session, test_user.id, source_ids=[sandbox.id], today=TODAY).sources == []


def test_default_sources_follow_eligibility_and_overrides(db_session, test_user):
    card = make_source(db_session, test_user)
    savings = make_source(db_session, test_user, external="acct-2", account_type="DEPOSITORY", subtype="SAVINGS")
    opted_out = make_source(db_session, test_user, external="acct-3", include_in_spending=False)
    opted_in = make_source(db_session, test_user, external="acct-4", account_type="DEPOSITORY", subtype="SAVINGS",
                           include_in_spending=True)
    ids = {c.source_id for c in month_summaries(db_session, test_user.id, today=TODAY).sources}
    assert ids == {str(card.id), str(opted_in.id)}
    assert str(savings.id) not in ids and str(opted_out.id) not in ids


def test_month_totals_by_kind(db_session, test_user):
    card = make_source(db_session, test_user)
    checking = make_source(db_session, test_user, external="acct-2", account_type="DEPOSITORY", subtype="CHECKING")
    other = make_source(db_session, test_user, external="acct-3", include_in_spending=False)
    for source in (card, checking, other):
        make_import(db_session, test_user, source, date(2026, 8, 1), date(2026, 8, 31))
    day = date(2026, 8, 10)
    make_txn(db_session, test_user, card, 100, day, "Groceries")
    make_txn(db_session, test_user, card, 60, day, "Restaurants")
    make_txn(db_session, test_user, card, -10, day, "Restaurants")
    make_txn(db_session, test_user, card, 25, day, None)
    make_txn(db_session, test_user, card, 900, day, "Travel", one_time=True)
    make_txn(db_session, test_user, card, 15, day, "Groceries", status="PENDING")
    make_txn(db_session, test_user, card, 40, day, "Groceries", excluded=True)
    make_txn(db_session, test_user, checking, -4000, day, "Paycheck")
    make_txn(db_session, test_user, checking, -300, day, "Bonus")
    make_txn(db_session, test_user, checking, -20, day, "Interest")
    make_txn(db_session, test_user, checking, 1200, day, "Mortgage")
    make_txn(db_session, test_user, checking, -50, day, None)
    make_txn(db_session, test_user, other, 999, day, "Groceries")
    month = by_month(month_summaries(db_session, test_user.id, today=TODAY))["2026-08"]
    assert month.complete
    assert (month.essential, month.discretionary) == (D("125"), D("50"))
    assert month.by_category == {"dining": D("50"), "groceries": D("100"), "uncategorized": D("25")}
    assert (month.income, month.income_wages) == (D("4300"), D("4000"))
    assert month.income_by_category == {"income_interest_dividends": D("20"), "income_other": D("300"),
                                        "income_wages": D("4000")}
    assert month.excluded == {"debt_payment": D("1200"), "excluded": D("40"), "other_deposit": D("50")}
    assert (month.one_time, month.one_time_count) == (D("900"), 1)
    assert month.uncategorized_outflow == D("25")
    assert (month.transaction_count, month.pending_count) == (12, 1)


def test_duplicate_account_warning_needs_ten_and_half(db_session, test_user):
    first = make_source(db_session, test_user)
    second = make_source(db_session, test_user, external="acct-2")
    third = make_source(db_session, test_user, external="acct-3")
    for source in (first, second, third):
        make_import(db_session, test_user, source, date(2026, 8, 1), date(2026, 8, 31))
    for index in range(12):
        make_txn(db_session, test_user, first, 10 + index, date(2026, 8, 1 + index))
        if index < 7:
            make_txn(db_session, test_user, second, 10 + index, date(2026, 8, 2 + index))
    make_txn(db_session, test_user, second, 500, date(2026, 8, 20))
    make_txn(db_session, test_user, second, 501, date(2026, 8, 20))
    make_txn(db_session, test_user, second, 502, date(2026, 8, 20))
    for index in range(5):
        make_txn(db_session, test_user, third, 10 + index, date(2026, 8, 1 + index))
    result = month_summaries(db_session, test_user.id, today=TODAY)
    assert len(result.duplicates) == 1
    warning = result.duplicates[0]
    assert set(warning.source_ids) == {str(first.id), str(second.id)}
    assert (warning.matched, warning.compared) == (7, 10)


def test_model_amounts_from_chosen_months():
    months = [MonthSummary("2026-07", True, [], essential=D("2000"), discretionary=D("-100"), income=D("5000")),
              MonthSummary("2026-08", True, [], essential=D("3000"), discretionary=D("50"), income=D("5500")),
              MonthSummary("2026-09", False, [{"code": "settling", "source_ids": []}])]
    amounts = model_amounts(months, ["2026-07", "2026-08", "2026-07"])
    assert amounts.months == ["2026-07", "2026-08"]
    assert amounts.annual_essential == D("30000.00")
    assert amounts.annual_discretionary == D("0.00")
    assert amounts.monthly_take_home == D("5250.00")
    for chosen, code in (([], "MONTH_REQUIRED"), (["2026-01"], "MONTH_UNKNOWN"), (["2026-09"], "MONTH_INCOMPLETE")):
        with pytest.raises(MonthSelectionError) as error:
            model_amounts(months, chosen)
        assert error.value.code == code
    with pytest.raises(MonthSelectionError) as error:
        model_amounts(months, ["2026-08", "2026-09"])
    assert error.value.months == ["2026-09"]


def test_trailing_summary_counts_only_take_home_income():
    rows = [LedgerTxn("w", "c", D("-1000"), "USD", "POSTED", date(2026, 8, 3), "plaid", "INCOME_WAGES"),
            LedgerTxn("i", "c", D("-50"), "USD", "POSTED", date(2026, 8, 3), "plaid", "INCOME_DIVIDENDS")]
    summary = trailing_summary(rows, {"c": (date(2026, 8, 1), date(2026, 9, 30))}, {}, date(2026, 9, 30))
    assert [m.month for m in summary.months] == ["2026-08"]
    assert summary.months[0].income == D("1000")
