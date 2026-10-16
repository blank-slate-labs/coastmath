"""Plaid sync adapter: ``accounts/get`` and ``transactions/sync`` into ledger rows.

API: https://plaid.com/docs/api/products/transactions/#transactionssync and
https://plaid.com/docs/api/accounts/. One Plaid Item is one connection
(``provider_connection_id`` = item ID); each Item account becomes a
``financial_sources`` row with ``provider='plaid'`` in the ``PLAID_ENV``
environment.

- A read follows ``transactions/sync`` from the stored cursor through every
  page, then reads the Item's accounts. ``store`` upserts added and modified
  rows first (a posted row naming ``pending_transaction_id`` replaces that
  pending row and keeps its corrections), then deletes ``removed`` IDs, and
  saves ``next_cursor`` last, in the same transaction: a failure anywhere
  leaves the old cursor, so the next read repeats the whole pass.
- Plaid reports account types, and credit and loan balances as the amount
  owed, which is already the ledger convention. ``balances.last_updated_datetime``
  is often null; the read time stands in so the seven-day freshness rule holds.
- Coverage: while Plaid is still loading history, each account covers from
  its earliest transaction. Once Plaid reports ``HISTORICAL_UPDATE_COMPLETE``,
  every account of the Item covers from the Item's earliest transaction (the
  depth the institution actually provided), never earlier than the requested
  days. Coverage only moves earlier.
- Schedule: webhooks wake the connection; otherwise it is read daily, hourly
  while history is still loading.

Nothing here logs; callers log connection IDs and counts only.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ledger.balances import save_source, signed_balance
from app.ledger.providers.base import SyncOutcome
from app.ledger.providers.errors import ProviderError
from app.ledger.providers.plaid_client import (
    DAYS_REQUESTED,
    PlaidAccounts,
    PlaidClient,
    SyncResult,
)
from app.ledger.store import remove_transactions, upsert_transactions
from app.ledger.types import NormalizedAccount
from app.models.financial_connection import (
    FinancialConnection,
    FinancialSource,
    FinancialTransaction,
)

PROVIDER = "plaid"
DEFAULT_INSTITUTION = "Linked institution"
HISTORICAL_COMPLETE = "HISTORICAL_UPDATE_COMPLETE"
DAILY = timedelta(hours=24)
HISTORY_LOADING = timedelta(hours=1)


def make_client() -> PlaidClient:
    """The client every Plaid call uses; tests replace it with a mock transport."""
    return PlaidClient()


@dataclass
class PlaidSync:
    accounts: PlaidAccounts
    changes: SyncResult


def plaid_balance(account: NormalizedAccount):
    """Plaid's ``current`` balance is already held (assets) or owed (debts); only bounds apply."""
    return signed_balance(account.balance, None)


class PlaidAdapter:
    provider = PROVIDER

    def read(self, connection: FinancialConnection, secret: str, today: date) -> PlaidSync:
        client = make_client()
        changes = client.sync_transactions(secret, connection.sync_cursor)
        # Accounts after transactions, so every account a transaction names is listed.
        accounts = client.accounts(secret)
        if accounts.item_id != connection.provider_connection_id:
            raise ProviderError("PROVIDER_DATA_INVALID", "Plaid returned accounts for a different connection.")
        return PlaidSync(accounts, changes)

    def store(self, db: Session, connection: FinancialConnection, data: PlaidSync, now: datetime) -> SyncOutcome:
        today = now.date()
        changes = data.changes
        listed = [upsert_account(db, connection, account, now) for account in data.accounts.accounts]
        by_external = {source.provider_account_id: source for source in listed}
        touched = {str(source.id) for source in listed}
        # Accounts the Item no longer lists (deselected in Link, closed) stop refreshing.
        for source in connection_sources(db, connection):
            by_external.setdefault(source.provider_account_id, source)
            if str(source.id) not in touched and source.status != "INACTIVE":
                source.status = "INACTIVE"
                source.revision += 1
                touched.add(str(source.id))
        rows = defaultdict(list)
        for row in [*changes.added, *changes.modified]:
            rows[row.account_external_id].append(row)
        for external_id, account_rows in rows.items():
            # A row for an account Plaid did not list is dropped; the next pass after a re-link restores it.
            if source := by_external.get(external_id):
                upsert_transactions(db, source, account_rows, today=today)
        # Removals last: a posted row has already taken over the pending row it replaces.
        removed = defaultdict(list)
        for row in changes.removed:
            removed[row.account_external_id].append(row.external_id)
        for external_id, ids in removed.items():
            targets = [by_external[external_id]] if external_id in by_external else list(by_external.values())
            for source in targets:
                remove_transactions(db, source, ids)
        db.flush()
        update_coverage(db, list(by_external.values()), changes.update_status == HISTORICAL_COMPLETE, today, now)
        connection.sync_cursor = changes.next_cursor
        db.flush()
        names = [account.institution_name for account in data.accounts.accounts if account.institution_name]
        return SyncOutcome(
            source_ids=touched, notice=None,
            next_check=DAILY if changes.update_status == HISTORICAL_COMPLETE else HISTORY_LOADING,
            institution_name=names[0][:255] if names else None)

    def revoke(self, secret: str) -> None:
        """``item/remove`` invalidates the access token and ends Plaid billing for the Item."""
        make_client().remove_item(secret)


def connection_sources(db: Session, connection: FinancialConnection) -> list[FinancialSource]:
    rows = db.query(FinancialSource).filter_by(user_id=connection.user_id, provider=PROVIDER,
                                               environment=connection.environment).all()
    return [row for row in rows if connection.provider_connection_id in (row.connection_ids or [])]


def update_coverage(db: Session, sources: list[FinancialSource], history_complete: bool, today: date,
                    now: datetime) -> None:
    earliest = {source.id: db.query(func.min(FinancialTransaction.transaction_date)).filter(
        FinancialTransaction.source_id == source.id).scalar() for source in sources}
    floor = today - timedelta(days=DAYS_REQUESTED)
    known = [value for value in earliest.values() if value is not None]
    item_start = max(floor, min(known)) if history_complete and known else (floor if history_complete else None)
    for source in sources:
        start = item_start or earliest[source.id] or today
        previous = source.transactions_coverage_start
        source.transactions_coverage_start = min(previous, start) if previous else start
        source.transactions_synced_at = now
        source.transactions_history_complete = source.transactions_history_complete or history_complete


def upsert_account(db: Session, connection: FinancialConnection, account: NormalizedAccount,
                   now: datetime) -> FinancialSource:
    source = db.query(FinancialSource).filter_by(user_id=connection.user_id, provider=PROVIDER,
                                                 environment=connection.environment,
                                                 provider_account_id=account.external_id).first()
    if source is None:
        source = FinancialSource(user_id=connection.user_id, provider=PROVIDER, environment=connection.environment,
                                 provider_account_id=account.external_id, connection_ids=[],
                                 name=(account.name or "Account")[:255], account_type=account.account_type or "OTHER",
                                 subtype=account.subtype, revision=0, institution_name=DEFAULT_INSTITUTION,
                                 status="ACTIVE")
        db.add(source)
    institution = account.institution_name or connection.institution_name or DEFAULT_INSTITUTION
    values = dict(name=(account.name or "Account")[:255], account_type=account.account_type or "OTHER",
                  subtype=account.subtype, mask=(account.mask or None) and account.mask[-4:],
                  institution_name=institution[:255],
                  institution_id=(account.institution_id or None) and account.institution_id[:255],
                  currency=account.currency, status="ACTIVE")
    # Plaid often omits the balance time; the read time keeps the freshness rule meaningful.
    return save_source(db, source, connection, values, account.balance_date or now, plaid_balance(account), now)
