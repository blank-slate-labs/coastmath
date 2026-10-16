"""Connection provenance and reviewed links into existing planning records."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.clock import utcnow
from app.db import Base


class FinancialConnection(Base):
    __tablename__ = "financial_connections"
    __table_args__ = (UniqueConstraint("provider", "environment", "provider_connection_id",
                                       name="uq_financial_connection_provider"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # plaid, simplefin or a plug-in provider's key (app/ledger/environments.py).
    provider: Mapped[str] = mapped_column(String(40))
    environment: Mapped[str] = mapped_column(String(20))
    provider_connection_id: Mapped[str] = mapped_column(String(255))
    # Provider customer identities, for providers that have them.
    customer_id: Mapped[str | None] = mapped_column(String(255))
    external_customer_id: Mapped[str | None] = mapped_column(String(255))
    # Encrypted per-connection secret (SimpleFIN access URL, Plaid access token).
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    sync_cursor: Mapped[str | None] = mapped_column(Text)
    institution_name: Mapped[str] = mapped_column(String(255), default="New connection")
    status: Mapped[str] = mapped_column(String(40), default="IN_PROGRESS")
    disconnected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Whether the provider agreed to load transactions (an optional product).
    transactions_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    transactions_error: Mapped[str | None] = mapped_column(String(500))
    # The plan the customer chose to receive this institution's accounts, with
    # the acknowledgements they gave before connecting. Null means review only.
    placement_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id", ondelete="SET NULL"))
    placement_duplicate_ack: Mapped[bool] = mapped_column(Boolean, default=False)
    placement_shared_ack: Mapped[bool] = mapped_column(Boolean, default=False)


class FinancialSource(Base):
    __tablename__ = "financial_sources"
    __table_args__ = (UniqueConstraint("user_id", "provider", "environment", "provider_account_id",
                                       name="uq_financial_source_provider"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # plaid, simplefin, file or a plug-in provider's key (app/ledger/environments.py).
    provider: Mapped[str] = mapped_column(String(40))
    environment: Mapped[str] = mapped_column(String(20))
    provider_account_id: Mapped[str] = mapped_column(String(255))
    connection_ids: Mapped[list] = mapped_column(JSONB, default=list)
    institution_id: Mapped[str | None] = mapped_column(String(255))
    institution_name: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    mask: Mapped[str | None] = mapped_column(String(4))
    account_type: Mapped[str] = mapped_column(String(40))
    subtype: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(40))
    balance: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    currency: Mapped[str | None] = mapped_column(String(10))
    balance_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    transactions_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transactions_history_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    # First calendar day with complete transaction history. Months before it are
    # never averaged, so a short initial load cannot understate spending.
    transactions_coverage_start: Mapped[date | None] = mapped_column(Date)
    placement_note: Mapped[str | None] = mapped_column(String(500))
    # The customer's choice to count (or not) this account's spending; null
    # keeps the default (checking-like cash and credit cards).
    include_in_spending: Mapped[bool | None] = mapped_column(Boolean)


class FinancialBalanceLink(Base):
    __tablename__ = "financial_balance_links"
    __table_args__ = (
        UniqueConstraint("source_id", "plan_id", name="uq_financial_link_source_plan"),
        UniqueConstraint("account_id", name="uq_financial_link_account"),
        UniqueConstraint("liability_id", name="uq_financial_link_liability"),
        CheckConstraint("(account_id IS NOT NULL AND liability_id IS NULL) OR (account_id IS NULL AND liability_id IS NOT NULL)", name="ck_financial_link_one_target"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_sources.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("current_accounts.id", ondelete="CASCADE"))
    liability_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("liabilities.id", ondelete="CASCADE"))
    last_applied_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    source_revision: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(40))
    source_subtype: Mapped[str | None] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FinancialSyncEvent(Base):
    __tablename__ = "financial_sync_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    link_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_balance_links.id", ondelete="SET NULL"))
    target_id: Mapped[uuid.UUID] = mapped_column()
    target_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_sources.id", ondelete="CASCADE"))
    source_revision: Mapped[int] = mapped_column(Integer)
    old_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    new_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FinancialTransaction(Base):
    """A provider-normalized transaction; no raw provider details are retained.

    `amount` is positive when money leaves the account and negative when it
    arrives (app/ledger/types.py). `category_override` (a canonical category ID
    from app/ledger/categories.py), `excluded` and `one_time` are the customer's
    corrections and survive every provider update of the same transaction.
    """
    __tablename__ = "financial_transactions"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "environment", "provider_transaction_id",
                         name="uq_financial_transaction_provider"),
        Index("ix_financial_transactions_source_date", "source_id", "transaction_date"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_sources.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    environment: Mapped[str] = mapped_column(String(20))
    provider_transaction_id: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    currency: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(255))
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    provider_category: Mapped[str | None] = mapped_column(String(100))
    category_override: Mapped[str | None] = mapped_column(String(40))
    llm_category: Mapped[str | None] = mapped_column(String(40))
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    # Shown in its month but never extrapolated into a spending model.
    one_time: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("financial_imports.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    transaction_date: Mapped[date] = mapped_column(Date)
    posted_date: Mapped[date | None] = mapped_column(Date)
    recurring_status: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FinancialSpendingFeed(Base):
    """Connected spending that keeps one plan's two spending expenses current.

    Mirrors a balance link: the last applied amounts detect outside edits, and
    the feed pauses instead of overwriting them.
    """
    __tablename__ = "financial_spending_feeds"
    __table_args__ = (UniqueConstraint("plan_id", name="uq_financial_spending_feed_plan"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    source_ids: Mapped[list] = mapped_column(JSONB, default=list)
    essential_expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id", ondelete="SET NULL"))
    discretionary_expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id", ondelete="SET NULL"))
    last_essential: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    last_discretionary: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    months_used: Mapped[int] = mapped_column(Integer, default=0)
    # trailing: the most recent complete months; months: the chosen basis_months (YYYY-MM).
    basis: Mapped[str] = mapped_column(String(10), default="trailing", server_default=text("'trailing'"))
    basis_months: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'"))
    error: Mapped[str | None] = mapped_column(String(500))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FinancialWebhookProfile(Base):
    __tablename__ = "financial_webhook_profiles"
    environment: Mapped[str] = mapped_column(String(20), primary_key=True)
    provider_id: Mapped[str | None] = mapped_column(String(255))
    account_id: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(2048))
    encrypted_secret: Mapped[str | None] = mapped_column(String(4096))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(500))


class FinancialWebhookReceipt(Base):
    __tablename__ = "financial_webhook_receipts"
    environment: Mapped[str] = mapped_column(String(20), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_connections.id", ondelete="CASCADE"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
