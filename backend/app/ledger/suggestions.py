"""Store LLM category suggestions for transactions nothing else categorized.

A transaction is pending when it is posted, not excluded, has no customer
override, matches no rule, has no suggestion yet, and its provider map leaves
it ``other`` or ``uncategorized``. A run sends a capped number of pending rows
to the operator's model (app/ledger/llm.py), stores valid answers in
``llm_category`` and re-applies spending feeds that read the affected
accounts. Classification precedence is unchanged: overrides and rules still
win over a suggestion.

A provider error leaves the failed batch untouched and is reported with a
user-safe message. Run outcomes, rows the model left unanswered and retry
backoff are kept in process memory: they are hints, not records, and a restart
simply retries.
"""
import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.clock import utcnow
from app.ledger.categories import UNCATEGORIZED
from app.ledger.classify import effective_category, from_row
from app.ledger.environments import active_filter
from app.ledger.feeds import refresh_feeds
from app.ledger.llm import LedgerLlmClient, LlmError, LlmSettings, SuggestionInput
from app.ledger.months import load_rules
from app.ledger.rules import order
from app.ledger.store import RETENTION_DAYS
from app.models.financial_connection import FinancialTransaction

logger = logging.getLogger(__name__)

UNCLEAR = ("other", UNCATEGORIZED)
MAX_PER_RUN = 200
BATCH_SIZE = 40
WORKER_INTERVAL_SECONDS = 600
FAILURE_BACKOFF_SECONDS = 3600
# Bound per-user memory of rows the model declined to categorize.
UNANSWERED_LIMIT = 5000


@dataclass(frozen=True)
class Outcome:
    """``status``: suggested, nothing_pending, failed, running or not_offered."""
    status: str
    suggested: int = 0
    sent: int = 0
    message: str | None = None
    finished_at: datetime | None = None


_lock = threading.Lock()
_running: set[str] = set()
_outcomes: dict[str, Outcome] = {}
_unanswered: dict[str, set[str]] = {}
_backoff_until: dict[str, float] = {}


def reset_state() -> None:
    """Forget every in-memory outcome, unanswered row and backoff (tests)."""
    with _lock:
        _running.clear()
        _outcomes.clear()
        _unanswered.clear()
        _backoff_until.clear()


def last_outcome(user_id: uuid.UUID) -> Outcome | None:
    return _outcomes.get(str(user_id))


def is_running(user_id: uuid.UUID) -> bool:
    return str(user_id) in _running


def since(today: date | None = None) -> date:
    return (today or utcnow().date()) - timedelta(days=RETENTION_DAYS)


def candidate_query(db: Session, today: date | None = None):
    """Rows that could be pending; rules and provider maps are checked in Python."""
    return db.query(FinancialTransaction).filter(
        active_filter(FinancialTransaction), FinancialTransaction.status == "POSTED",
        FinancialTransaction.excluded.is_(False), FinancialTransaction.category_override.is_(None),
        FinancialTransaction.llm_category.is_(None), FinancialTransaction.transaction_date >= since(today))


def pending_rows(db: Session, user_id: uuid.UUID, today: date | None = None) -> list[FinancialTransaction]:
    """Pending rows for one user, newest first."""
    rows = candidate_query(db, today).filter(FinancialTransaction.user_id == user_id).order_by(
        FinancialTransaction.transaction_date.desc(), FinancialTransaction.id).all()
    if not rows:
        return []
    rules = order(load_rules(db, user_id))
    skipped = _unanswered.get(str(user_id), set())
    pending = []
    for row in rows:
        if str(row.id) in skipped:
            continue
        category, source, _ = effective_category(from_row(row), rules)
        if source in ("provider", "none") and category in UNCLEAR:
            pending.append(row)
    return pending


def users_with_candidates(db: Session, today: date | None = None) -> list[uuid.UUID]:
    query = candidate_query(db, today).with_entities(FinancialTransaction.user_id).distinct()
    return sorted((row[0] for row in query.all()), key=str)


def remember_unanswered(user_id: str, keys: set[str]) -> None:
    if not keys:
        return
    with _lock:
        known = _unanswered.setdefault(user_id, set())
        if len(known) + len(keys) > UNANSWERED_LIMIT:
            known.clear()
        known.update(keys)


def store_suggestions(db: Session, user_id: uuid.UUID, suggested: dict[str, str]) -> int:
    """Write answers to rows that are still unclaimed; re-apply affected feeds."""
    if not suggested:
        return 0
    ids = [uuid.UUID(key) for key in suggested]
    rows = db.query(FinancialTransaction).filter(
        FinancialTransaction.user_id == user_id, FinancialTransaction.id.in_(ids),
        FinancialTransaction.category_override.is_(None), FinancialTransaction.llm_category.is_(None)).all()
    for row in rows:
        row.llm_category = suggested[str(row.id)]
    if rows:
        db.flush()
        refresh_feeds(db, user_id, {str(row.source_id) for row in rows})
    db.commit()
    return len(rows)


def run_for_user(db: Session, user_id: uuid.UUID, client: LedgerLlmClient | None = None,
                 limit: int = MAX_PER_RUN, today: date | None = None) -> Outcome:
    """Suggest categories for up to ``limit`` pending rows of one user."""
    if client is None:
        settings = LlmSettings.load()
        if settings is None:
            return Outcome("not_offered")
        client = LedgerLlmClient(settings)
    key = str(user_id)
    with _lock:
        if key in _running:
            return Outcome("running")
        _running.add(key)
    try:
        outcome = _run(db, user_id, client, limit, today)
    finally:
        with _lock:
            _running.discard(key)
    _outcomes[key] = outcome
    return outcome


def _run(db: Session, user_id: uuid.UUID, client: LedgerLlmClient, limit: int, today: date | None) -> Outcome:
    rows = pending_rows(db, user_id, today)[:limit]
    if not rows:
        return Outcome("nothing_pending", finished_at=utcnow())
    items = [SuggestionInput(str(row.id), row.description, row.merchant_name, row.amount, row.provider_category)
             for row in rows]
    # End the read transaction before waiting on the network.
    db.commit()
    suggested: dict[str, str] = {}
    failure: LlmError | None = None
    sent = 0
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        try:
            answers = client.suggest(batch)
        except LlmError as error:
            failure = error
            break
        sent += len(batch)
        suggested.update(answers)
        remember_unanswered(str(user_id), {item.key for item in batch} - set(answers))
    stored = store_suggestions(db, user_id, suggested)
    logger.info("Ledger suggestions run: user=%s sent=%s stored=%s failed=%s", user_id, sent, stored,
                failure.code if failure else None)
    if failure is not None:
        return Outcome("failed", stored, sent, failure.message, utcnow())
    return Outcome("suggested", stored, sent, None, utcnow())


def process_pending(factory: sessionmaker, client: LedgerLlmClient, today: date | None = None) -> int:
    """One background pass over every user with possible pending rows; returns rows suggested."""
    with factory() as db:
        users = users_with_candidates(db, today)
    total = 0
    for user_id in users:
        if _backoff_until.get(str(user_id), 0) > time.monotonic():
            continue
        with factory() as db:
            outcome = run_for_user(db, user_id, client, today=today)
        total += outcome.suggested
        if outcome.status == "failed":
            _backoff_until[str(user_id)] = time.monotonic() + FAILURE_BACKOFF_SECONDS
    return total


async def run_suggestion_worker(factory: sessionmaker, interval: float = WORKER_INTERVAL_SECONDS) -> None:
    while (settings := LlmSettings.load()) is not None:
        try:
            await asyncio.to_thread(process_pending, factory, LedgerLlmClient(settings))
        except Exception:
            # Exception text can carry SQL values; never log financial data.
            logger.error("Ledger suggestion pass failed; the next pass retries.")
        await asyncio.sleep(interval)


def start_suggestion_worker(factory: sessionmaker | None) -> asyncio.Task | None:
    """Start the background loop only when suggestions are offered and a database exists."""
    if factory is None or LlmSettings.load() is None:
        return None
    return asyncio.create_task(run_suggestion_worker(factory))
