"""In-process scheduler for provider-neutral pull syncs (SimpleFIN; Plaid next).

The database is the queue: a connection is due when ``next_check_at`` has
passed. A worker claims one with a lease (``FOR UPDATE SKIP LOCKED``, which
SQLite ignores safely, then ``next_check_at`` moved past the lease), so several
web processes never sync the same connection at once and a stopped process
leaves a lease that simply expires. A connection whose account the access
policy no longer lets link (``app.access.BANK_LINKING``) is not leased: its
check moves out and it keeps its status until access returns. Provider calls
run without database locks; results are stored under the user lock, then
balance links and spending feeds of the updated accounts are re-applied.

Logs carry connection IDs, counts and error types only: never amounts,
descriptions, URLs or credentials.
"""
import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, sessionmaker

from app.access import BANK_LINKING, allows
from app.clock import utcnow
from app.ledger import connections as lifecycle
from app.ledger import secrets
from app.ledger.balances import apply_links, lock_user
from app.ledger.environments import environment_for
from app.ledger.feeds import refresh_feeds
from app.ledger.providers.errors import ProviderError
from app.ledger.providers.registry import pull_providers
from app.models.financial_connection import FinancialConnection, FinancialSource
from app.models.user import User

logger = logging.getLogger(__name__)
IDLE_SECONDS = 15
BUSY_SECONDS = 1
#: Paused connections passed over in one claim before the worker rests.
PAUSED_PER_CLAIM = 50


def claim_due(factory: sessionmaker, now: datetime | None = None) -> uuid.UUID | None:
    """Lease the most overdue connection of an offered pull provider; its ID or None."""
    providers = pull_providers()
    if not providers:
        return None
    now = now or utcnow()
    with factory() as db:
        query = db.query(FinancialConnection).filter(
            FinancialConnection.disconnected.is_(False), FinancialConnection.next_check_at.is_not(None),
            FinancialConnection.next_check_at <= now, FinancialConnection.credentials_encrypted.is_not(None))
        pairs = [(key, environment_for(key)) for key in providers]
        query = query.filter(or_(*(and_(FinancialConnection.provider == key, FinancialConnection.environment == env)
                                   for key, env in pairs)))
        for _ in range(PAUSED_PER_CLAIM):
            connection = query.order_by(FinancialConnection.next_check_at).with_for_update(skip_locked=True).first()
            if connection is None:
                return None
            user = db.get(User, connection.user_id)
            if user is not None and not allows(user, BANK_LINKING):
                lifecycle.pause_for_access(connection, now)
                db.commit()
                logger.info("Ledger sync paused for connection %s: the account may not link.", connection.id)
                continue
            connection.status = lifecycle.SYNCING
            connection.next_check_at = now + lifecycle.LEASE
            db.commit()
            return connection.id
        return None


def run_connection(db: Session, connection_id: uuid.UUID, now: datetime | None = None) -> bool:
    """Sync one leased connection and schedule its next check. True when it succeeded."""
    now = now or utcnow()
    connection = db.get(FinancialConnection, connection_id)
    item = pull_providers().get(connection.provider) if connection else None
    if connection is None or item is None or connection.disconnected:
        return False
    ciphertext = connection.credentials_encrypted
    try:
        secret = secrets.decrypt(ciphertext)
        read = item.adapter.read(connection, secret, now.date())
    except (secrets.CredentialError, ProviderError) as error:
        return finish_failure(db, connection_id, error, now)
    except Exception as error:  # noqa: BLE001 - any adapter failure must reschedule, never stall
        logger.error("Ledger sync read failed for connection %s (%s).", connection_id, type(error).__name__)
        return finish_failure(db, connection_id, error, now)
    try:
        user_id = connection.user_id
        lock_user(db, user_id)
        db.refresh(connection)
        if connection.disconnected or connection.credentials_encrypted != ciphertext:
            # Disconnected or reconnected while reading: this read is stale.
            db.rollback()
            return False
        outcome = item.adapter.store(db, connection, read, now)
        if fresh := secrets.rotated(ciphertext):
            connection.credentials_encrypted = fresh
        if outcome.institution_name:
            connection.institution_name = outcome.institution_name
        lifecycle.record_success(connection, now, outcome.notice, outcome.next_check)
        db.flush()
        for source in db.query(FinancialSource).filter(
                FinancialSource.id.in_([uuid.UUID(value) for value in outcome.source_ids])).all():
            apply_links(db, source, now)
        refresh_feeds(db, user_id, outcome.source_ids)
        db.commit()
    except Exception as error:  # noqa: BLE001
        db.rollback()
        logger.error("Ledger sync store failed for connection %s (%s).", connection_id, type(error).__name__)
        return finish_failure(db, connection_id, error, now)
    logger.info("Ledger sync stored %d accounts for connection %s.", len(outcome.source_ids), connection_id)
    return True


def finish_failure(db: Session, connection_id: uuid.UUID, error: Exception, now: datetime) -> bool:
    db.rollback()
    connection = db.get(FinancialConnection, connection_id)
    if connection is not None and not connection.disconnected:
        lifecycle.record_failure(connection, error, now)
        db.commit()
        code = getattr(error, "code", type(error).__name__)
        logger.warning("Ledger sync for connection %s failed: %s; status %s.", connection_id, code, connection.status)
    return False


def sync_one_due(factory: sessionmaker, now: datetime | None = None) -> bool:
    """Claim and run one due connection. True when one was claimed."""
    connection_id = claim_due(factory, now)
    if connection_id is None:
        return False
    with factory() as db:
        run_connection(db, connection_id, now)
    return True


def worker_wanted() -> bool:
    return bool(pull_providers())


async def run_sync_worker(factory: sessionmaker) -> None:
    while worker_wanted():
        try:
            worked = await asyncio.to_thread(sync_one_due, factory)
        except Exception as error:  # noqa: BLE001
            logger.error("Ledger sync worker iteration failed (%s); the lease allows retry.", type(error).__name__)
            worked = False
        await asyncio.sleep(BUSY_SECONDS if worked else IDLE_SECONDS)
