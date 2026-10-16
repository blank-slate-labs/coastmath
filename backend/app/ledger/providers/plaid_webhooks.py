"""Plaid webhooks: verified wake-ups for the matching Item's connection.

Per https://plaid.com/docs/api/webhooks/ a webhook names an Item and an
event; its body is never treated as financial data. A transactions event moves
the connection's next check forward (debounced, so a burst of webhooks starts
one sync); an Item event that needs the customer marks the connection for
reconnection (https://plaid.com/docs/api/items/#webhooks). Everything else is
acknowledged and ignored, as are unknown Items, so Plaid does not retry.

Callers verify the ``Plaid-Verification`` JWT before calling ``handle``.
"""
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.clock import aware, utcnow
from app.ledger import connections as lifecycle
from app.ledger.balances import lock_user
from app.ledger.environments import environment_for
from app.models.financial_connection import FinancialConnection

logger = logging.getLogger(__name__)
#: Webhooks arriving within this delay share one sync.
DEBOUNCE = timedelta(seconds=30)
WAKE_TYPES = frozenset({"TRANSACTIONS"})
#: ITEM codes that need the customer to sign in again or re-consent through update mode.
RECONNECT_CODES = frozenset({"PENDING_EXPIRATION", "PENDING_DISCONNECT", "USER_PERMISSION_REVOKED",
                             "USER_ACCOUNT_REVOKED"})
RECONNECT_ERRORS = frozenset({"ITEM_LOGIN_REQUIRED"})
RECONNECT_MESSAGE = "This bank connection needs you to sign in again."


def parse(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def needs_reconnect(kind: str, code: str, payload: dict) -> bool:
    if kind != "ITEM":
        return False
    error = payload.get("error")
    error_code = error.get("error_code") if isinstance(error, dict) else None
    return code in RECONNECT_CODES or (code == "ERROR" and error_code in RECONNECT_ERRORS)


def wake(connection: FinancialConnection, now: datetime) -> None:
    """Sync soon unless a sync is already due sooner or running."""
    if lifecycle.is_syncing(connection, now) or connection.status == lifecycle.RECONNECT_REQUIRED:
        return
    due = now + DEBOUNCE
    if connection.next_check_at is None or aware(connection.next_check_at) > due:
        connection.next_check_at = due


def handle(db: Session, body: bytes, now: datetime | None = None) -> str:
    """Apply a verified webhook; returns what happened (``ignored``, ``woken``, ``reconnect``, ``repaired``)."""
    now = now or utcnow()
    payload = parse(body)
    kind, code, item_id = (payload.get(name) for name in ("webhook_type", "webhook_code", "item_id"))
    if not all(isinstance(value, str) and value for value in (kind, code, item_id)):
        return "ignored"
    connection = db.query(FinancialConnection).filter_by(
        provider="plaid", environment=environment_for("plaid"), provider_connection_id=item_id,
        disconnected=False).first()
    if connection is None:
        logger.info("Plaid webhook %s.%s for an unknown item ignored.", kind, code)
        return "ignored"
    # Same lock order as the sync worker and the routes: user first.
    lock_user(db, connection.user_id)
    db.refresh(connection)
    outcome = "ignored"
    if needs_reconnect(kind, code, payload):
        connection.status, connection.error, connection.next_check_at = (
            lifecycle.RECONNECT_REQUIRED, RECONNECT_MESSAGE, None)
        outcome = "reconnect"
    elif kind == "ITEM" and code == "LOGIN_REPAIRED" and connection.status == lifecycle.RECONNECT_REQUIRED:
        connection.status, connection.error = lifecycle.NEW, None
        lifecycle.schedule_now(connection, now)
        outcome = "repaired"
    elif kind in WAKE_TYPES or (kind == "ITEM" and code == "NEW_ACCOUNTS_AVAILABLE"):
        wake(connection, now)
        outcome = "woken"
    db.commit()
    logger.info("Plaid webhook %s.%s for connection %s: %s.", kind, code, connection.id, outcome)
    return outcome
