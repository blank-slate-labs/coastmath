"""Store normalized transactions from every provider in one table.

A read covers a date window. Every transaction in it is upserted, and a saved
transaction of the same account that the read no longer returns inside the
window (away from its start edge) was cancelled or removed, so it is deleted.
The customer's category, exclusion and one-time choices survive every update.
Only normalized fields are kept; raw provider payloads are never stored.

Stored IDs: every provider stores ``<provider_account_id>:<id>``, so two
accounts can never collide, hashed when longer than the column. A plug-in
provider may keep raw IDs instead (``app.ledger.provider_traits``).
"""
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ledger import provider_traits
from app.ledger.types import NormalizedTransaction
from app.models.financial_connection import (
    FinancialSource,
    FinancialTransaction,
    utcnow,
)

RETENTION_DAYS = 760
# Providers may filter windows by posted or transaction date. Never treat a
# transaction near the window's start as removed.
EDGE_DAYS = 5
MAX_AMOUNT = Decimal("9999999999999.99")
CHUNK = 500
CENT = Decimal("0.01")
ID_LENGTH = 255


@dataclass
class StoreResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    removed: int = 0
    duplicates: int = 0
    #: Stored IDs of the rows inserted by this call, in input order.
    inserted_ids: list[str] = field(default_factory=list)


def chunks(values: list, size: int = CHUNK):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def stored_id(source: FinancialSource, external_id: str) -> str:
    traits = provider_traits.traits(source.provider)
    if traits is not None and traits.raw_transaction_ids:
        return external_id
    value = f"{source.provider_account_id}:{external_id}"
    return value if len(value) <= ID_LENGTH else "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def usable(row: NormalizedTransaction) -> bool:
    amount = row.amount
    return isinstance(amount, Decimal) and amount.is_finite() and abs(amount) <= MAX_AMOUNT


def _text(value: str | None, length: int) -> str | None:
    collapsed = " ".join((value or "").split())[:length]
    return collapsed or None


def row_values(source: FinancialSource, row: NormalizedTransaction) -> dict:
    return dict(
        source_id=source.id, amount=row.amount.quantize(CENT), currency=(row.currency or "")[:10] or None,
        description=_text(row.description, 255) or "Transaction", merchant_name=_text(row.merchant_name, 255),
        provider_category=(row.provider_category or None) and row.provider_category[:100], status=row.status,
        transaction_date=row.transaction_date, posted_date=row.posted_date,
        recurring_status=(row.recurring_status or None) and row.recurring_status[:20],
    )


def _existing(db: Session, source: FinancialSource, ids: list[str]) -> dict[str, FinancialTransaction]:
    found: dict[str, FinancialTransaction] = {}
    for part in chunks(ids):
        for saved in db.query(FinancialTransaction).filter(
                FinancialTransaction.user_id == source.user_id, FinancialTransaction.provider == source.provider,
                FinancialTransaction.environment == source.environment,
                FinancialTransaction.provider_transaction_id.in_(part)):
            found[saved.provider_transaction_id] = saved
    return found


def upsert_transactions(db: Session, source: FinancialSource, rows: list[NormalizedTransaction], *,
                        window: tuple[date, date] | None = None, import_id=None,
                        unusable_ids: Iterable[str] = (), today: date | None = None) -> StoreResult:
    """Upsert one account's rows; optionally reconcile ``window`` (inclusive dates).

    ``unusable_ids`` names rows the adapter received but could not normalize
    (no date, say): they count as skipped and, like rows with an invalid
    amount, keep any earlier valid copy instead of being treated as removed.
    ``import_id`` is stamped on inserted rows only.
    """
    now = utcnow()
    unusable = list(unusable_ids)
    result = StoreResult(skipped=len(unusable))
    received = {stored_id(source, external) for external in unusable}
    keyed: list[tuple[str, NormalizedTransaction]] = []
    seen: set[str] = set()
    for row in rows:
        key = stored_id(source, row.external_id)
        received.add(key)
        if key in seen:
            result.duplicates += 1
        elif not usable(row):
            # Keep any earlier valid copy rather than guessing an amount.
            result.skipped += 1
        else:
            seen.add(key)
            keyed.append((key, row))
    pending_keys = {stored_id(source, row.pending_external_id): key for key, row in keyed if row.pending_external_id}
    existing = _existing(db, source, [key for key, _ in keyed] + list(pending_keys))
    for key, row in keyed:
        values = row_values(source, row)
        saved = existing.get(key)
        pending_key = stored_id(source, row.pending_external_id) if row.pending_external_id else None
        pending = existing.get(pending_key) if pending_key and pending_key != key else None
        if pending is not None:
            # The posted transaction replaces its pending row and keeps its corrections.
            if saved is None:
                pending.provider_transaction_id = key
                saved, existing[key] = pending, pending
            else:
                for attr in ("category_override", "excluded", "one_time"):
                    if getattr(pending, attr) and not getattr(saved, attr):
                        setattr(saved, attr, getattr(pending, attr))
                db.delete(pending)
            existing.pop(pending_key, None)
            for name, value in values.items():
                setattr(saved, name, value)
            saved.updated_at = now
            result.updated += 1
        elif saved is None:
            created = FinancialTransaction(user_id=source.user_id, provider=source.provider,
                                           environment=source.environment, provider_transaction_id=key,
                                           import_id=import_id, updated_at=now, **values)
            db.add(created)
            existing[key] = created
            result.inserted += 1
            result.inserted_ids.append(key)
        elif any(getattr(saved, name) != value for name, value in values.items()):
            for name, value in values.items():
                setattr(saved, name, value)
            saved.updated_at = now
            result.updated += 1
        else:
            result.unchanged += 1
    db.flush()
    if window is not None:
        start, end = window
        inside = db.query(FinancialTransaction.id, FinancialTransaction.provider_transaction_id).filter(
            FinancialTransaction.source_id == source.id,
            FinancialTransaction.transaction_date >= start + timedelta(days=EDGE_DAYS),
            FinancialTransaction.transaction_date <= end).all()
        removed = [row_id for row_id, provider_id in inside if provider_id not in received]
        for part in chunks(removed):
            db.query(FinancialTransaction).filter(FinancialTransaction.id.in_(part)).delete(synchronize_session=False)
        result.removed = len(removed)
    prune(db, source, today or now.date())
    return result


def prune(db: Session, source: FinancialSource, today: date) -> None:
    db.query(FinancialTransaction).filter(
        FinancialTransaction.source_id == source.id,
        FinancialTransaction.transaction_date < today - timedelta(days=RETENTION_DAYS),
    ).delete(synchronize_session=False)


def remove_transactions(db: Session, source: FinancialSource, external_ids: Iterable[str]) -> int:
    """Delete this account's rows the provider reported removed; returns the count."""
    keys = [stored_id(source, external) for external in dict.fromkeys(external_ids)]
    count = 0
    for part in chunks(keys):
        count += db.query(FinancialTransaction).filter(
            FinancialTransaction.source_id == source.id,
            FinancialTransaction.provider_transaction_id.in_(part)).delete(synchronize_session=False)
    return count
