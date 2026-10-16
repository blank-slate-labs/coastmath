"""Provider-neutral transaction review: accounts, transactions, rules and months.

Every route is session-authenticated and scoped to the user's rows in active
provider environments. "Today" is the user's calendar date (``ledger_today``):
it sets the retention window, the current month and account coverage. Changes require TRANSACTIONS_ENABLED; reads and
deletions stay available. Changes that affect classification re-apply the
user's connected spending feeds that read the affected accounts.
"""
import csv
import io
import re
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.access import ensure_plan_openable
from app.auth.dependencies import get_current_user
from app.db import get_db
from app.errors import api_error
from app.ledger.accounts import (
    EDITABLE_PROVIDERS,
    counts_toward_spending,
    source_label,
    spending_eligible,
)
from app.ledger.balances import retype_balance
from app.ledger.categories import category_table
from app.ledger.classify import Classification, classify
from app.ledger.environments import active_filter
from app.ledger.feeds import apply_feeds, feed_for_plan
from app.ledger.gating import require_transactions_enabled
from app.ledger.months import (
    first_complete_month,
    import_periods,
    load_ledger,
    load_rules,
    month_start,
    month_summaries,
    next_month,
    source_coverage,
)
from app.ledger.rules import normalize
from app.ledger.store import RETENTION_DAYS
from app.models.financial_connection import (
    FinancialSource,
    FinancialSpendingFeed,
    FinancialTransaction,
    utcnow,
)
from app.models.ledger import FinancialRule
from app.models.user import User
from app.routers.helpers import client_today, get_plan_or_404
from app.schemas.ledger import (
    BulkTransactionUpdate,
    BulkUpdateRead,
    CategoryRead,
    DateRange,
    DuplicateRead,
    LedgerAccountRead,
    LedgerAccountUpdate,
    LedgerTransactionPage,
    LedgerTransactionRead,
    LedgerTransactionUpdate,
    LedgerTransactionUpdateRead,
    MonthRead,
    MonthReason,
    MonthSourceRead,
    MonthsRead,
    RuleCreate,
    RuleRead,
    RuleUpdate,
    TransactionChanges,
)

router = APIRouter(prefix="/ledger", tags=["ledger"], dependencies=[Depends(require_transactions_enabled)])
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# Transaction pairing looks a few days past a month's edges.
PAIR_MARGIN_DAYS = 7


def fail(message: str, status: int = 409, code: str = "CONFLICT") -> None:
    raise api_error(status, code, message)


def lock_user(db: Session, user_id: uuid.UUID) -> None:
    if db.query(User.id).filter(User.id == user_id).with_for_update().first() is None:
        fail("Account no longer exists.", 401, "AUTH_REQUIRED")


def ledger_today(x_client_date: str | None = Header(default=None, alias="X-Client-Date")) -> date:
    """The user's calendar date from ``X-Client-Date`` (see ``client_today``); the UTC date without the header."""
    return client_today(x_client_date) if x_client_date else utcnow().date()


def retention_start(today: date) -> date:
    return first_complete_month(today - timedelta(days=RETENTION_DAYS)) - timedelta(days=PAIR_MARGIN_DAYS)


def source_for_user(db: Session, user_id: uuid.UUID, source_id: uuid.UUID) -> FinancialSource:
    source = db.query(FinancialSource).filter(FinancialSource.id == source_id, FinancialSource.user_id == user_id,
                                              active_filter(FinancialSource)).first()
    if source is None:
        fail("Account not found.", 404, "NOT_FOUND")
    return source


def reapply_feeds(db: Session, user_id: uuid.UUID, source_ids: set[str] | None = None) -> None:
    """Re-apply feeds reading these accounts; every feed of the user when None (rules)."""
    feeds = db.query(FinancialSpendingFeed).filter_by(user_id=user_id).all()
    if source_ids is not None:
        feeds = [feed for feed in feeds if source_ids & set(feed.source_ids)]
    if feeds:
        apply_feeds(db, feeds)


# --- categories and accounts --------------------------------------------------

@router.get("/categories", response_model=list[CategoryRead])
def list_categories(current_user: User = Depends(get_current_user)) -> list[CategoryRead]:
    return [CategoryRead(**row) for row in category_table()]


def account_read(source: FinancialSource, coverage, count: int) -> LedgerAccountRead:
    return LedgerAccountRead(
        id=source.id, provider=source.provider, institution_name=source.institution_name, name=source.name,
        mask=source.mask, account_type=source.account_type, subtype=source.subtype, currency=source.currency,
        status=source.status, spending_eligible=spending_eligible(source),
        include_in_spending=source.include_in_spending, counts_toward_spending=counts_toward_spending(source),
        coverage=[DateRange(start=start, end=end) for start, end in coverage.seen],
        last_read_at=source.transactions_synced_at, transaction_count=count,
        editable=source.provider in EDITABLE_PROVIDERS)


def account_reads(db: Session, user_id: uuid.UUID, sources: list[FinancialSource], *,
                  today: date | None = None) -> list[LedgerAccountRead]:
    today = today or utcnow().date()
    ids = [source.id for source in sources]
    counts = dict(db.query(FinancialTransaction.source_id, func.count(FinancialTransaction.id)).filter(
        FinancialTransaction.user_id == user_id, FinancialTransaction.source_id.in_(ids)).group_by(
        FinancialTransaction.source_id).all()) if ids else {}
    periods = import_periods(db, [source.id for source in sources if source.provider == "file"])
    return [account_read(source, source_coverage(source, today, periods.get(str(source.id), [])),
                         counts.get(source.id, 0)) for source in sources]


@router.get("/accounts", response_model=list[LedgerAccountRead])
def list_accounts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  today: date = Depends(ledger_today)) -> list[LedgerAccountRead]:
    sources = db.query(FinancialSource).filter(FinancialSource.user_id == current_user.id,
                                               active_filter(FinancialSource)).order_by(
        FinancialSource.institution_name, FinancialSource.name, FinancialSource.id).all()
    return account_reads(db, current_user.id, sources, today=today)


@router.patch("/accounts/{source_id}", response_model=LedgerAccountRead)
def update_account(source_id: uuid.UUID, body: LedgerAccountUpdate, current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db), today: date = Depends(ledger_today)) -> LedgerAccountRead:
    lock_user(db, current_user.id)
    source = source_for_user(db, current_user.id, source_id)
    details = {"name", "account_type", "subtype"} & body.model_fields_set
    if details and source.provider not in EDITABLE_PROVIDERS:
        fail("This institution reports the account's name and type.", 422, "VALIDATION_ERROR")
    previous_type = source.account_type
    for name in ("include_in_spending", *sorted(details)):
        if name in body.model_fields_set:
            setattr(source, name, getattr(body, name))
    if "account_type" in details:
        source.revision += 1
        retype_balance(source, previous_type)
    db.commit()
    return account_reads(db, current_user.id, [source], today=today)[0]


# --- transactions -------------------------------------------------------------

def transaction_read(row: FinancialTransaction, source: FinancialSource, label: Classification) -> LedgerTransactionRead:
    return LedgerTransactionRead(
        id=row.id, source_id=source.id, source_name=source_label(source), provider=row.provider,
        date=row.transaction_date, posted_date=row.posted_date, description=row.description,
        merchant_name=row.merchant_name, amount=float(row.amount), currency=row.currency, status=row.status,
        provider_category=row.provider_category, category=label.category, category_source=label.source,
        rule_id=uuid.UUID(label.rule_id) if label.rule_id else None, category_override=row.category_override,
        kind=label.kind, bucket=label.bucket if label.kind in {"spending", "refund", "one_time"} else None,
        excluded=row.excluded, one_time=row.one_time, recurring=row.recurring_status == "RECURRING")


def labels_for(db: Session, user_id: uuid.UUID, since: date, currency: str = "USD") -> dict[str, Classification]:
    # Classify against every account so card payments pair with their other side.
    return classify(load_ledger(db, user_id, since), load_rules(db, user_id), currency)


def retained_rows(db: Session, user_id: uuid.UUID, since: date):
    """The user's transactions inside the retention window with their accounts, newest first."""
    return db.query(FinancialTransaction, FinancialSource).join(
        FinancialSource, FinancialSource.id == FinancialTransaction.source_id).filter(
        FinancialTransaction.user_id == user_id, active_filter(FinancialTransaction),
        FinancialTransaction.transaction_date >= since)


def order_rows(query):
    return query.order_by(FinancialTransaction.transaction_date.desc(), FinancialTransaction.id).all()


@router.get("/transactions", response_model=LedgerTransactionPage)
def list_transactions(
    source_id: uuid.UUID | None = None, month: str | None = Query(None, pattern=MONTH.pattern),
    category: str | None = Query(None, max_length=40), kind: str | None = Query(None, max_length=20),
    text: str | None = Query(None, max_length=100), uncategorized: bool = False,
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0, le=100000),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
    today: date = Depends(ledger_today),
) -> LedgerTransactionPage:
    since = retention_start(today)
    query = retained_rows(db, current_user.id, since)
    if source_id:
        query = query.filter(FinancialTransaction.source_id == source_id)
    if month:
        start = month_start(month)
        query = query.filter(FinancialTransaction.transaction_date >= start,
                             FinancialTransaction.transaction_date < next_month(start))
    rows = order_rows(query)
    labels = labels_for(db, current_user.id, since)
    needle = normalize(text)
    chosen = []
    for row, source in rows:
        label = labels[str(row.id)]
        if category and label.category != category or kind and label.kind != kind:
            continue
        if uncategorized and label.category != "uncategorized":
            continue
        if needle and needle not in normalize(f"{row.description} {row.merchant_name or ''}"):
            continue
        chosen.append(transaction_read(row, source, label))
    return LedgerTransactionPage(transactions=chosen[offset:offset + limit], total=len(chosen))


EXPORT_COLUMNS = ("date", "posted_date", "description", "merchant", "amount", "currency", "category", "account",
                  "excluded", "one_time")
#: Text a spreadsheet would run as a formula.
FORMULA_START = re.compile(r"^\s*[=+\-@]")


def text_cell(value: str | None) -> str:
    """A text cell; one that starts like a formula gets a leading apostrophe."""
    value = value or ""
    return f"'{value}" if FORMULA_START.match(value) else value


@router.get("/transactions/export")
def export_transactions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                        today: date = Depends(ledger_today)) -> Response:
    """Every retained transaction as CSV, with the category it counts under. Amounts are
    positive when money leaves the account, as in the ledger."""
    since = retention_start(today)
    rows = order_rows(retained_rows(db, current_user.id, since))
    labels = labels_for(db, current_user.id, since)
    names = {row["id"]: row["label"] for row in category_table()}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for row, source in rows:
        category = labels[str(row.id)].category
        writer.writerow([
            row.transaction_date.isoformat(), row.posted_date.isoformat() if row.posted_date else "",
            text_cell(row.description), text_cell(row.merchant_name), f"{row.amount:.2f}", text_cell(row.currency),
            text_cell(names.get(category, category)), text_cell(source_label(source)),
            "true" if row.excluded else "false", "true" if row.one_time else "false"])
    return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="transactions.csv"',
                             "Cache-Control": "no-store"})


def apply_changes(row: FinancialTransaction, body: TransactionChanges) -> None:
    if "category" in body.model_fields_set:
        row.category_override = body.category
    for name in ("excluded", "one_time"):
        if name in body.model_fields_set:
            setattr(row, name, getattr(body, name))


def rule_reads(db: Session, user_id: uuid.UUID, rules: list[FinancialRule], *,
               today: date | None = None) -> list[RuleRead]:
    labels = labels_for(db, user_id, retention_start(today or utcnow().date()))
    counts: dict[str, int] = {}
    for label in labels.values():
        if label.rule_id:
            counts[label.rule_id] = counts.get(label.rule_id, 0) + 1
    return [RuleRead.model_validate(rule).model_copy(update={"match_count": counts.get(str(rule.id), 0)})
            for rule in rules]


def transactions_for_user(db: Session, user_id: uuid.UUID, ids: list[uuid.UUID]) -> list[FinancialTransaction]:
    rows = db.query(FinancialTransaction).filter(FinancialTransaction.user_id == user_id,
                                                 FinancialTransaction.id.in_(ids),
                                                 active_filter(FinancialTransaction)).all()
    if len(rows) != len(set(ids)):
        fail("Transaction not found.", 404, "NOT_FOUND")
    return rows


def reads_for(db: Session, user_id: uuid.UUID, rows: list[FinancialTransaction], *,
              today: date | None = None) -> list[LedgerTransactionRead]:
    since = min([retention_start(today or utcnow().date()), *(row.transaction_date for row in rows)])
    labels = labels_for(db, user_id, since)
    sources = {source.id: source for source in db.query(FinancialSource).filter(
        FinancialSource.id.in_({row.source_id for row in rows})).all()}
    return [transaction_read(row, sources[row.source_id], labels[str(row.id)]) for row in rows]


@router.patch("/transactions/{transaction_id}", response_model=LedgerTransactionUpdateRead)
def update_transaction(transaction_id: uuid.UUID, body: LedgerTransactionUpdate,
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                       today: date = Depends(ledger_today)) -> LedgerTransactionUpdateRead:
    lock_user(db, current_user.id)
    (row,) = transactions_for_user(db, current_user.id, [transaction_id])
    apply_changes(row, body)
    rule = None
    if body.apply_to_similar:
        field, value = ("merchant", row.merchant_name) if normalize(row.merchant_name) else ("description", row.description)
        rule = FinancialRule(user_id=current_user.id, match_field=field, match_type="equals",
                             pattern=normalize(value)[:100].strip(), direction="outflow" if row.amount > 0 else "inflow",
                             category=body.category)
        db.add(rule)
    db.flush()
    reapply_feeds(db, current_user.id, None if rule else {str(row.source_id)})
    db.commit()
    (read,) = reads_for(db, current_user.id, [row], today=today)
    return LedgerTransactionUpdateRead(
        transaction=read, rule=rule_reads(db, current_user.id, [rule], today=today)[0] if rule else None)


@router.post("/transactions/bulk", response_model=BulkUpdateRead)
def bulk_update_transactions(body: BulkTransactionUpdate, current_user: User = Depends(get_current_user),
                             db: Session = Depends(get_db), today: date = Depends(ledger_today)) -> BulkUpdateRead:
    lock_user(db, current_user.id)
    rows = transactions_for_user(db, current_user.id, body.ids)
    for row in rows:
        apply_changes(row, body)
    db.flush()
    reapply_feeds(db, current_user.id, {str(row.source_id) for row in rows})
    db.commit()
    rows.sort(key=lambda row: (row.transaction_date, str(row.id)), reverse=True)
    return BulkUpdateRead(transactions=reads_for(db, current_user.id, rows, today=today))


# --- rules --------------------------------------------------------------------

def rule_for_user(db: Session, user_id: uuid.UUID, rule_id: uuid.UUID) -> FinancialRule:
    rule = db.query(FinancialRule).filter_by(id=rule_id, user_id=user_id).first()
    if rule is None:
        fail("Rule not found.", 404, "NOT_FOUND")
    return rule


@router.get("/rules", response_model=list[RuleRead])
def list_rules(current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
               today: date = Depends(ledger_today)) -> list[RuleRead]:
    rules = db.query(FinancialRule).filter_by(user_id=current_user.id).order_by(
        FinancialRule.created_at.desc(), FinancialRule.id).all()
    return rule_reads(db, current_user.id, rules, today=today)


@router.post("/rules", response_model=RuleRead, status_code=201)
def create_rule(body: RuleCreate, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db), today: date = Depends(ledger_today)) -> RuleRead:
    lock_user(db, current_user.id)
    if body.source_id:
        source_for_user(db, current_user.id, body.source_id)
    if db.query(FinancialRule.id).filter_by(user_id=current_user.id).count() >= 500:
        fail("Remove an unused rule before adding another.", 422, "VALIDATION_ERROR")
    rule = FinancialRule(user_id=current_user.id, **body.model_dump())
    db.add(rule)
    db.flush()
    reapply_feeds(db, current_user.id)
    db.commit()
    return rule_reads(db, current_user.id, [rule], today=today)[0]


@router.patch("/rules/{rule_id}", response_model=RuleRead)
def update_rule(rule_id: uuid.UUID, body: RuleUpdate, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db), today: date = Depends(ledger_today)) -> RuleRead:
    lock_user(db, current_user.id)
    rule = rule_for_user(db, current_user.id, rule_id)
    if body.source_id:
        source_for_user(db, current_user.id, body.source_id)
    for name in body.model_fields_set:
        setattr(rule, name, getattr(body, name))
    rule.updated_at = utcnow()
    db.flush()
    reapply_feeds(db, current_user.id)
    db.commit()
    return rule_reads(db, current_user.id, [rule], today=today)[0]


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> Response:
    lock_user(db, current_user.id)
    db.delete(rule_for_user(db, current_user.id, rule_id))
    db.flush()
    reapply_feeds(db, current_user.id)
    db.commit()
    return Response(status_code=204)


# --- months -------------------------------------------------------------------

@router.get("/months", response_model=MonthsRead)
def list_months(source_ids: list[uuid.UUID] | None = Query(None), plan_id: uuid.UUID | None = None,
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                today: date = Depends(ledger_today)) -> MonthsRead:
    if source_ids is not None and len(source_ids) > 50:
        fail("Choose at most 50 accounts.", 422, "VALIDATION_ERROR")
    currency = "USD"
    if plan_id is not None:
        plan = get_plan_or_404(plan_id, current_user.id, db)
        ensure_plan_openable(plan, current_user)
        currency = plan.currency
        feed = feed_for_plan(db, plan.id)
        if source_ids is None and feed is not None:
            source_ids = [uuid.UUID(value) for value in feed.source_ids]
    result = month_summaries(db, current_user.id, source_ids, currency, today)

    def money(values: dict) -> dict[str, float]:
        return {key: float(value) for key, value in values.items()}

    return MonthsRead(
        currency=result.currency,
        months=[MonthRead(
            month=m.month, complete=m.complete, reasons=[MonthReason(**reason) for reason in m.reasons],
            essential=float(m.essential), discretionary=float(m.discretionary), income=float(m.income),
            income_wages=float(m.income_wages), by_category=money(m.by_category),
            income_by_category=money(m.income_by_category), excluded=money(m.excluded), one_time=float(m.one_time),
            one_time_count=m.one_time_count, uncategorized_outflow=float(m.uncategorized_outflow),
            transaction_count=m.transaction_count, pending_count=m.pending_count) for m in result.months],
        sources=[MonthSourceRead(id=uuid.UUID(c.source_id), provider=c.provider, name=c.name,
                                 coverage=[DateRange(start=s, end=e) for s, e in c.seen],
                                 settled=[DateRange(start=s, end=e) for s, e in c.settled], waiting=c.waiting)
                 for c in result.sources],
        duplicates=[DuplicateRead(source_ids=[uuid.UUID(value) for value in d.source_ids], matched=d.matched,
                                  compared=d.compared) for d in result.duplicates])

