"""SimpleFIN sync adapter: bridge reads into ledger accounts and transactions.

Protocol: https://www.simplefin.org/protocol.html. One access URL can cover
several institutions; each bridge account becomes a ``financial_sources`` row
with ``provider='simplefin'`` (always ``production``).

- First sync walks back from today in 45-day windows (bridges' recommended
  limit per request), up to a year, and stops after two windows without any
  transaction.
- Later syncs read the last 30 days, or back to five days before the last
  success when that is longer (a reconnect after an outage), with window
  reconciliation: a stored row the bridge no longer returns was removed.
  Reconciliation is skipped for a read with bridge errors or undatable rows,
  and for accounts the read did not include.
- SimpleFIN reports no account type. New accounts are ``UNCONFIRMED`` until
  the customer confirms one; the name and type are the customer's afterwards.
- Balances are stored with the ledger convention: amount owed for CREDIT and
  LOAN, the bridge's raw value otherwise (``app.ledger.balances.signed_balance``).
- Coverage starts at the earliest stored transaction (today for an account
  without any) and only ever moves earlier.

Nothing here logs; callers log connection IDs and counts only.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.clock import aware
from app.ledger.accounts import UNCONFIRMED_TYPE
from app.ledger.balances import save_source, signed_balance
from app.ledger.providers.base import SyncOutcome
from app.ledger.providers.simplefin_client import (
    MAX_WINDOW_DAYS,
    SimpleFINClient,
    SimpleFINRead,
)
from app.ledger.store import upsert_transactions
from app.ledger.types import NormalizedAccount
from app.models.financial_connection import (
    FinancialConnection,
    FinancialSource,
    FinancialTransaction,
)

PROVIDER = "simplefin"
HISTORY_DAYS = 365
UPDATE_DAYS = 30
OVERLAP_DAYS = 5
EMPTY_WINDOWS_TO_STOP = 2
DEFAULT_INSTITUTION = "SimpleFIN"


def make_client() -> SimpleFINClient:
    """The client every SimpleFIN call uses; tests replace it with a mock transport."""
    return SimpleFINClient()


@dataclass
class SimpleFINSync:
    read: SimpleFINRead
    #: Inclusive dates the read covers, reconciled when ``reconcile`` is True.
    window: tuple[date, date]
    reconcile: bool


def walk_back(client: SimpleFINClient, secret: str, today: date) -> SimpleFINSync:
    earliest = today - timedelta(days=HISTORY_DAYS - 1)
    accounts: dict[str, NormalizedAccount] = {}
    transactions: dict[tuple[str, str], object] = {}
    messages: list[str] = []
    skipped = empty = 0
    end = today
    start = today
    while end >= earliest and empty < EMPTY_WINDOWS_TO_STOP:
        start = max(earliest, end - timedelta(days=MAX_WINDOW_DAYS - 1))
        read = client.accounts(secret, start, end, pending=True)
        # Walking backwards, the first (newest) read has the current balances.
        for account in read.accounts:
            accounts.setdefault(account.external_id, account)
        for row in read.transactions:
            transactions.setdefault((row.account_external_id, row.external_id), row)
        messages += [message for message in read.messages if message not in messages]
        skipped += read.skipped
        empty = empty + 1 if not read.transactions else 0
        end = start - timedelta(days=1)
    combined = SimpleFINRead(list(accounts.values()), list(transactions.values()), messages, skipped)
    return SimpleFINSync(combined, (start, today), reconcile=False)


def update_start(connection: FinancialConnection, today: date) -> date:
    start = today - timedelta(days=UPDATE_DAYS - 1)
    if connection.last_checked_at is not None:
        start = min(start, aware(connection.last_checked_at).date() - timedelta(days=OVERLAP_DAYS))
    return max(start, today - timedelta(days=HISTORY_DAYS - 1))


class SimpleFINAdapter:
    provider = PROVIDER

    def read(self, connection: FinancialConnection, secret: str, today: date) -> SimpleFINSync:
        client = make_client()
        if connection.last_checked_at is None:
            return walk_back(client, secret, today)
        start = update_start(connection, today)
        read = client.accounts_range(secret, start, today, pending=True)
        return SimpleFINSync(read, (start, today), reconcile=not read.messages and not read.skipped)

    def store(self, db: Session, connection: FinancialConnection, data: SimpleFINSync, now: datetime) -> SyncOutcome:
        read = data.read
        rows = defaultdict(list)
        for row in read.transactions:
            rows[row.account_external_id].append(row)
        sources = [upsert_account(db, connection, account, now) for account in read.accounts]
        today = now.date()
        for source, account in zip(sources, read.accounts, strict=True):
            upsert_transactions(db, source, rows.get(account.external_id, []),
                                window=data.window if data.reconcile else None, today=today)
            earliest = db.query(func.min(FinancialTransaction.transaction_date)).filter(
                FinancialTransaction.source_id == source.id).scalar() or today
            previous = source.transactions_coverage_start
            source.transactions_coverage_start = min(previous, earliest) if previous else earliest
            source.transactions_synced_at = now
        db.flush()
        names = list(dict.fromkeys(source.institution_name for source in sources))
        return SyncOutcome(source_ids={str(source.id) for source in sources}, notice="; ".join(read.messages) or None,
                           institution_name=", ".join(names)[:255] if names else None)

    def revoke(self, secret: str) -> None:
        """SimpleFIN access ends when the access URL is dropped; customers can also revoke it at their bridge."""
        return


def upsert_account(db: Session, connection: FinancialConnection, account: NormalizedAccount,
                   now: datetime) -> FinancialSource:
    source = db.query(FinancialSource).filter_by(user_id=connection.user_id, provider=PROVIDER,
                                                 environment=connection.environment,
                                                 provider_account_id=account.external_id).first()
    if source is None:
        source = FinancialSource(user_id=connection.user_id, provider=PROVIDER, environment=connection.environment,
                                 provider_account_id=account.external_id, connection_ids=[],
                                 name=(account.name or "Account")[:255], account_type=UNCONFIRMED_TYPE,
                                 subtype=None, revision=0, institution_name=DEFAULT_INSTITUTION, status="ACTIVE")
        db.add(source)
    values = dict(institution_name=(account.institution_name or DEFAULT_INSTITUTION)[:255],
                  institution_id=(account.institution_id or None) and account.institution_id[:255],
                  currency=account.currency, status="ACTIVE" if account.active else "INACTIVE")
    return save_source(db, source, connection, values, account.balance_date or now,
                       signed_balance(account.balance, source.account_type), now)
