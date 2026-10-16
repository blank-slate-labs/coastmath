"""Lifecycle of provider-neutral connections (SimpleFIN now, Plaid next).

A connection row holds one encrypted credential and its schedule. Its
accounts are ``financial_sources`` rows of the same provider whose
``connection_ids`` name the connection's ``provider_connection_id``.

``status`` vocabulary for neutral providers:
- ``NEW``: waiting for its first sync;
- ``SYNCING``: a worker holds its lease;
- ``ACTIVE``: the last sync succeeded (``error`` may carry a provider notice);
- ``RETRYING``: a transient failure; ``next_check_at`` backs off;
- ``PAYMENT_REQUIRED``: the provider wants payment; retried daily;
- ``RECONNECT_REQUIRED``: the credential no longer works; never retried;
- ``DISCONNECTED``: the customer disconnected; the credential is gone.

``last_checked_at`` is the last successful sync. A plug-in provider that
runs its own connections (``app.ledger.provider_traits``) never passes
through this module.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.clock import aware, utcnow
from app.ledger import provider_traits, secrets
from app.ledger.balances import apply_links
from app.ledger.environments import environment_for
from app.ledger.providers.errors import ProviderError
from app.ledger.providers.registry import descriptor
from app.models.financial_connection import (
    FinancialBalanceLink,
    FinancialConnection,
    FinancialSource,
    FinancialTransaction,
)

NEW, SYNCING, ACTIVE, RETRYING = "NEW", "SYNCING", "ACTIVE", "RETRYING"
PAYMENT_REQUIRED, RECONNECT_REQUIRED, DISCONNECTED = "PAYMENT_REQUIRED", "RECONNECT_REQUIRED", "DISCONNECTED"
LEASE = timedelta(minutes=15)
RATE_LIMITED = timedelta(hours=6)
PAYMENT_RETRY = timedelta(hours=24)
BACKOFF_MIN = timedelta(minutes=15)
BACKOFF_MAX = timedelta(hours=12)
#: How often a connection whose account may not link (``app.access.BANK_LINKING``)
#: is looked at again; it syncs on the first check after access returns.
LINKING_PAUSED_RECHECK = timedelta(hours=1)
MESSAGE_LENGTH = 500


def self_managed() -> frozenset[str]:
    """Providers whose plug-in runs their connections; this module leaves them alone."""
    return provider_traits.own_lifecycle()


def is_neutral(connection: FinancialConnection) -> bool:
    return connection.provider not in self_managed()


def create_connection(db: Session, user_id: uuid.UUID, provider: str, secret: str, *,
                      provider_connection_id: str | None = None, institution_name: str | None = None,
                      now: datetime | None = None) -> FinancialConnection:
    """A new connection scheduled for an immediate first sync."""
    now = now or utcnow()
    connection = FinancialConnection(
        user_id=user_id, provider=provider, environment=environment_for(provider),
        provider_connection_id=provider_connection_id or str(uuid.uuid4()),
        credentials_encrypted=secrets.encrypt(secret), institution_name=(institution_name or "New connection")[:255],
        status=NEW, disconnected=False, next_check_at=now, transactions_enabled=True, created_at=now)
    db.add(connection)
    db.flush()
    return connection


def replace_credentials(connection: FinancialConnection, secret: str, now: datetime | None = None) -> None:
    """Reconnect: store the new credential and sync now. Accounts and history stay."""
    connection.credentials_encrypted = secrets.encrypt(secret)
    connection.status, connection.error = NEW, None
    connection.next_check_at = now or utcnow()


def schedule_now(connection: FinancialConnection, now: datetime | None = None) -> None:
    connection.next_check_at = now or utcnow()


def pause_for_access(connection: FinancialConnection, now: datetime) -> None:
    """Skip a due sync the account may not run now. Status, error and saved
    data stay as they are: the connection is neither failed nor in need of
    reconnecting, and it syncs once access returns."""
    connection.next_check_at = now + LINKING_PAUSED_RECHECK


def is_syncing(connection: FinancialConnection, now: datetime) -> bool:
    return connection.status == SYNCING and connection.next_check_at is not None and aware(connection.next_check_at) > now


def backoff(connection: FinancialConnection, now: datetime) -> timedelta:
    """Grows with the time since the last success (or creation): 15 min, then roughly doubling, at most 12 h."""
    since = connection.last_checked_at or connection.created_at or now
    return min(BACKOFF_MAX, max(BACKOFF_MIN, now - aware(since)))


def record_success(connection: FinancialConnection, now: datetime, notice: str | None, interval: timedelta) -> None:
    connection.status, connection.error = ACTIVE, (notice or None) and notice[:MESSAGE_LENGTH]
    connection.last_checked_at = now
    connection.next_check_at = now + interval
    connection.transactions_error = None


def record_failure(connection: FinancialConnection, error: Exception, now: datetime) -> None:
    """Schedule the next attempt from a failed sync. Messages are user-safe."""
    if isinstance(error, secrets.CredentialError):
        connection.status, connection.error, connection.next_check_at = RECONNECT_REQUIRED, error.message, None
        return
    if isinstance(error, ProviderError):
        message = error.message[:MESSAGE_LENGTH]
        if error.reconnect_required or error.code == "PROVIDER_URL_REJECTED":
            connection.status, connection.error, connection.next_check_at = RECONNECT_REQUIRED, message, None
        elif error.code == "PROVIDER_PAYMENT_REQUIRED":
            connection.status, connection.error = PAYMENT_REQUIRED, message
            connection.next_check_at = now + PAYMENT_RETRY
        elif error.code == "PROVIDER_RATE_LIMIT":
            connection.status, connection.error = RETRYING, message
            connection.next_check_at = now + RATE_LIMITED
        else:
            connection.status, connection.error = RETRYING, message
            connection.next_check_at = now + backoff(connection, now)
        return
    connection.status, connection.error = RETRYING, "Sync failed. It will retry automatically."
    connection.next_check_at = now + backoff(connection, now)


def sources_of(db: Session, connection: FinancialConnection) -> list[FinancialSource]:
    rows = db.query(FinancialSource).filter_by(user_id=connection.user_id, provider=connection.provider,
                                               environment=connection.environment).all()
    return [row for row in rows if connection.provider_connection_id in (row.connection_ids or [])]


def live_connection_ids(db: Session, user_id: uuid.UUID, provider: str, environment: str) -> set[str]:
    """``provider_connection_id`` of this user's connections that can still refresh accounts."""
    return {value for (value,) in db.query(FinancialConnection.provider_connection_id).filter(
        FinancialConnection.user_id == user_id, FinancialConnection.provider == provider,
        FinancialConnection.environment == environment, FinancialConnection.disconnected.is_(False),
        FinancialConnection.status.notin_([RECONNECT_REQUIRED, DISCONNECTED]))}


def is_connected(db: Session, source: FinancialSource) -> bool:
    live = live_connection_ids(db, source.user_id, source.provider, source.environment)
    return bool(live & set(source.connection_ids or []))


def revoke(connection: FinancialConnection) -> None:
    """Remove remote access through the provider's adapter (raises ``ProviderError``).

    An unreadable credential cannot be used by anyone, so there is nothing to revoke.
    """
    item = descriptor(connection.provider)
    if item is None or item.adapter is None or not connection.credentials_encrypted:
        return
    try:
        secret = secrets.decrypt(connection.credentials_encrypted)
    except secrets.CredentialError:
        return
    item.adapter.revoke(secret)


def drop(connection: FinancialConnection) -> None:
    connection.credentials_encrypted = None
    connection.sync_cursor = None
    connection.disconnected = True
    connection.status, connection.error, connection.next_check_at = DISCONNECTED, None, None


def disconnect(db: Session, connection: FinancialConnection, *, remove_data: bool = False,
               now: datetime | None = None) -> set[str]:
    """Revoke and drop the credential, detach its accounts; returns affected account IDs.

    Without ``remove_data`` the accounts and transactions stay; accounts no
    other live connection refreshes become inactive, which pauses their
    balance links. With it, those accounts, their transactions and links are
    deleted. Raises ``ProviderError`` (nothing changed) when revocation fails.
    """
    if not connection.disconnected:
        revoke(connection)
    drop(connection)
    db.flush()
    live = live_connection_ids(db, connection.user_id, connection.provider, connection.environment)
    affected: set[str] = set()
    for source in sources_of(db, connection):
        source.connection_ids = [value for value in source.connection_ids if value != connection.provider_connection_id]
        if live & set(source.connection_ids):
            continue
        affected.add(str(source.id))
        if remove_data:
            delete_source(db, source)
        elif source.status != "INACTIVE":
            source.status = "INACTIVE"
            source.revision += 1
            apply_links(db, source, now)
    db.flush()
    return affected


def delete_source(db: Session, source: FinancialSource) -> None:
    db.query(FinancialTransaction).filter_by(source_id=source.id).delete(synchronize_session=False)
    db.query(FinancialBalanceLink).filter_by(source_id=source.id).delete(synchronize_session=False)
    db.delete(source)


def disconnect_all(db: Session, user_id: uuid.UUID) -> None:
    """Account deletion: revoke and drop every neutral credential of the user.

    Raises ``ProviderError`` on the first failed revocation; connections
    already dropped stay dropped. Rows themselves cascade with the user.
    """
    connections = db.query(FinancialConnection).filter(
        FinancialConnection.user_id == user_id, FinancialConnection.disconnected.is_(False),
        FinancialConnection.provider.notin_(self_managed())).all()
    for connection in connections:
        revoke(connection)
        drop(connection)
        db.flush()
