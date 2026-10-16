"""Spending feeds: keep a plan's two spending expenses equal to its accounts' spending.

A feed reads any provider's accounts in active environments. It mirrors a
balance link: the last applied amounts detect outside edits, and the feed
pauses instead of overwriting them. A plug-in provider may turn a feed on
when an institution connects.

Two bases set the amounts:

- ``trailing``: 12 × the average of the most recent complete months (up to 12);
- ``months``: 12 × the average of the chosen ``basis_months``, the same model
  a month comparison previews. A chosen month that stops being complete keeps
  the last amounts and reports an error instead of guessing.

Both judge completeness with ``app.ledger.months`` coverage, so file accounts
count their imported statement periods.
"""
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.errors import api_error
from app.feature_flags import transactions_enabled
from app.ledger.accounts import source_label
from app.ledger.classify import DEFAULT_CURRENCY
from app.ledger.environments import active_filter
from app.ledger.month_models import month_model
from app.ledger.months import (
    MonthSelectionError,
    Summary,
    annual_amounts,
    load_ledger,
    load_rules,
    model_amounts,
    month_frame,
    month_summaries,
    trailing_summary,
)
from app.models.expense import Expense
from app.models.financial_connection import (
    FinancialSource,
    FinancialSpendingFeed,
    utcnow,
)
from app.models.plan import Plan
from app.routers.helpers import get_plan_or_404

FEED_EXPENSES = (
    ("essential_expense_id", "last_essential", "Everyday spending (connected)", "essential"),
    ("discretionary_expense_id", "last_discretionary", "Discretionary spending (connected)", "discretionary"),
)
# Twelve complete months plus the current month and transfer-pairing margin.
LOOKBACK_DAYS = 400
BASES = ("trailing", "months")
MONTHS_UNAVAILABLE = ("A chosen month is no longer complete. The last amounts are kept until you choose "
                      "other months or switch to recent months.")


def _fail(message: str, status: int = 409, code: str = "CONFLICT") -> None:
    raise api_error(status, code, message)


def feed_for_plan(db: Session, plan_id: uuid.UUID) -> FinancialSpendingFeed | None:
    return db.query(FinancialSpendingFeed).filter_by(plan_id=plan_id).first()


def spending_summary(db: Session, user_id: uuid.UUID, environment: str | None, source_ids: list[str],
                     today: date, currency: str = DEFAULT_CURRENCY) -> Summary:
    """The trailing average over the chosen accounts in active environments.

    Months are complete by ``app.ledger.months`` coverage: synced accounts
    from their coverage start to the last read less the settle days, file
    accounts by their committed import periods. ``environment`` is accepted
    for older callers and ignored: ledger reads cover every provider's active
    environment.
    """
    wanted = {uuid.UUID(value) for value in source_ids}
    sources = db.query(FinancialSource).filter(
        FinancialSource.user_id == user_id, active_filter(FinancialSource), FinancialSource.id.in_(wanted)).all()
    coverages, frame = month_frame(db, user_id, list(wanted), today)
    seen = {coverage.source_id: coverage.seen for coverage in coverages}
    coverage = {}
    for source in sources:
        if source.provider == "file":
            intervals = seen.get(str(source.id)) or []
            coverage[str(source.id)] = (intervals[0][0], intervals[-1][1]) if intervals else (None, None)
        else:
            coverage[str(source.id)] = (source.transactions_coverage_start,
                                        source.transactions_synced_at.date() if source.transactions_synced_at else None)
    names = {str(source.id): source_label(source) for source in sources}
    return trailing_summary(load_ledger(db, user_id, today - timedelta(days=LOOKBACK_DAYS)), coverage, names, today,
                            rules=load_rules(db, user_id), currency=currency,
                            complete=[month.month for month in frame if month.complete])


def apply_feed(db: Session, feed: FinancialSpendingFeed, environment: str | None = None,
               today: date | None = None) -> bool:
    """Write the feed's spending model into the plan's two connected expenses."""
    today = today or utcnow().date()
    plan = get_plan_or_404(feed.plan_id, feed.user_id, db, for_update=True)
    if plan.plan_type != "NOW":
        feed.error = "Connected spending is paused for this fixed-date plan. Its saved expenses are preserved."
        return False
    if feed.basis == "months":
        result = month_summaries(db, feed.user_id, [uuid.UUID(value) for value in feed.source_ids], plan.currency, today)
        try:
            model = model_amounts(result.months, list(feed.basis_months or []))
        except MonthSelectionError:
            feed.error = MONTHS_UNAVAILABLE
            return False
        feed.months_used = len(model.months)
        amounts = (model.annual_essential, model.annual_discretionary)
    else:
        summary = spending_summary(db, feed.user_id, environment, feed.source_ids, today, plan.currency)
        feed.months_used = len(summary.months)
        if not summary.months:
            # Still loading: keep the last applied amounts until a full month exists.
            feed.error = None
            return False
        amounts = annual_amounts(summary)
    return _write_amounts(db, feed, plan, amounts)


def _write_amounts(db: Session, feed: FinancialSpendingFeed, plan: Plan, amounts: tuple[Decimal, Decimal]) -> bool:
    targets = []
    for (id_attr, last_attr, name, category), amount in zip(FEED_EXPENSES, amounts, strict=True):
        expense_id, last = getattr(feed, id_attr), getattr(feed, last_attr)
        expense = db.query(Expense).filter_by(id=expense_id, plan_id=plan.id).with_for_update().populate_existing().first() \
            if expense_id else None
        if expense is None and (expense_id is not None or last is not None):
            feed.error = "A connected spending expense was removed. Turn connected spending off and on again to recreate it."
            return False
        if expense is not None and Decimal(str(expense.annual_amount)) != last:
            feed.error = ("A connected spending expense was edited outside sync. Turn connected spending off, "
                          "review the expense, then turn it on again.")
            return False
        targets.append((id_attr, last_attr, name, category, amount, expense))
    changed = False
    for id_attr, last_attr, name, category, amount, expense in targets:
        if expense is None:
            expense = Expense(id=uuid.uuid4(), plan_id=plan.id, name=name, annual_amount=amount,
                              category=category, inflation_linked=True)
            db.add(expense)
            db.flush()
            setattr(feed, id_attr, expense.id)
            changed = True
        elif Decimal(str(expense.annual_amount)) != amount:
            expense.annual_amount = amount
            changed = True
        setattr(feed, last_attr, amount)
    feed.error = None
    feed.applied_at = utcnow()
    return changed


def apply_feeds(db: Session, feeds: list[FinancialSpendingFeed], environment: str | None = None) -> int:
    changed = 0
    for feed in sorted(feeds, key=lambda item: str(item.plan_id)):
        try:
            with db.begin_nested():
                changed += apply_feed(db, feed, environment)
        except HTTPException as error:
            feed.error = error.detail["error"]["message"]
    return changed


def feeds_using(db: Session, user_id: uuid.UUID, source_ids: set[str]) -> list[FinancialSpendingFeed]:
    return [feed for feed in db.query(FinancialSpendingFeed).filter_by(user_id=user_id).all()
            if source_ids & set(feed.source_ids)]


def refresh_feeds(db: Session, user_id: uuid.UUID, source_ids: set[str] | list[str]) -> int:
    """Re-apply every feed of this user that reads any of these accounts.

    Call it after anything that changes those accounts' transactions or their
    classification: an import, a sync, a correction, a rule or a suggestion.
    """
    wanted = {str(value) for value in source_ids}
    return apply_feeds(db, feeds_using(db, user_id, wanted)) if wanted else 0


# --- turning a feed on, changing its basis, turning it off --------------------

def set_feed(db: Session, user_id: uuid.UUID, plan: Plan, source_ids: list[uuid.UUID], *,
             acknowledge_existing_expenses: bool, scope, eligible: Callable[[FinancialSource], bool],
             basis: str | None = None, months: list[str] | None = None,
             environment: str | None = None) -> FinancialSpendingFeed:
    """Create or update a plan's feed and apply it; the caller locks the user and plan and commits.

    ``scope`` is the SQL condition on ``FinancialSource`` a caller allows (the
    ledger route: every active environment; a plug-in's routes: its own accounts).
    ``basis`` None keeps the feed's basis. The ``months`` basis is refused
    with 422 unless every chosen month is complete over these accounts.
    """
    if plan.plan_type != "NOW":
        _fail("Use a Now plan for connected spending. Fixed-date snapshots stay unchanged.")
    ids = list(dict.fromkeys(str(value) for value in source_ids))
    sources = db.query(FinancialSource).filter(FinancialSource.user_id == user_id, scope,
                                               FinancialSource.id.in_(source_ids)).all()
    if len(sources) != len(ids):
        _fail("Account not found.", 404, "NOT_FOUND")
    if not all(eligible(source) for source in sources):
        _fail("Connected spending uses checking and credit card accounts.", 422, "VALIDATION_ERROR")
    chosen: list[str] | None = None
    if basis == "months":
        chosen = month_model(db, user_id, [uuid.UUID(value) for value in ids], months or [], plan.currency).amounts.months
    feed = feed_for_plan(db, plan.id)
    if feed is None:
        if db.query(Expense.id).filter(Expense.plan_id == plan.id).first() and not acknowledge_existing_expenses:
            _fail("Review this plan's existing expenses first. Confirm connected spending will not count the same spending twice.")
        feed = FinancialSpendingFeed(id=uuid.uuid4(), user_id=user_id, plan_id=plan.id, source_ids=ids)
        db.add(feed)
    else:
        feed.source_ids = ids
    if basis is not None:
        feed.basis = basis
        feed.basis_months = chosen or []
    db.flush()
    apply_feeds(db, [feed], environment)
    return feed


def stop_feed(db: Session, plan: Plan) -> None:
    """Stop updates; the connected expenses keep their last amounts and become editable."""
    feed = feed_for_plan(db, plan.id)
    if feed is None:
        _fail("Connected spending is not on for this plan.", 404, "NOT_FOUND")
    db.delete(feed)


def guard_connected_expense(db: Session, expense: Expense, values: dict | None = None) -> None:
    """Keep connected expenses from being overwritten or deleted by hand.

    Editors send full records, so an unchanged amount is allowed; names,
    categories and timing remain the customer's to edit.
    """
    feed = db.query(FinancialSpendingFeed.id).filter(or_(
        FinancialSpendingFeed.essential_expense_id == expense.id,
        FinancialSpendingFeed.discretionary_expense_id == expense.id)).first()
    if feed is None:
        return
    if values is not None and (values.get("annual_amount") is None
                               or Decimal(str(values["annual_amount"])) == Decimal(str(expense.annual_amount))):
        return
    # Its own code: a revision conflict (CONFLICT) asks the client to review newer saved
    # values and retry, which cannot succeed here while the feed is on.
    raise api_error(409, "CONNECTED_EXPENSE", connected_expense_message())


def connected_expense_message() -> str:
    """Name where the feed turns off: Transactions, or a plug-in provider's Connections without it."""
    if transactions_enabled():
        return ("This expense follows your transactions. Turn off Plan spending in Transactions "
                "before changing its amount or deleting it.")
    return ("This expense is updated from connected accounts. Turn off connected spending in Connections "
            "before changing its amount or deleting it.")
