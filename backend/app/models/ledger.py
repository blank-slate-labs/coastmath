"""Provider-neutral ledger records: file imports and categorization rules.

The provider-neutral transaction, source and connection rows themselves stay in
``app/models/financial_connection.py``.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.clock import utcnow
from app.db import Base


class FinancialImport(Base):
    """One committed file import into a ``file`` source.

    The statement period (``date_from`` to ``date_to``, inclusive) is the
    coverage the import proves: months are complete only where committed
    imports cover every day.
    """
    __tablename__ = "financial_imports"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_sources.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(10))  # csv | ofx
    mapping: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'"))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="committed")  # committed | reverted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinancialRule(Base):
    """A customer's categorization rule, evaluated on read; it never rewrites rows.

    ``pattern`` is stored normalized (casefolded, whitespace collapsed) by
    ``app.ledger.rules.normalize``.
    """
    __tablename__ = "financial_rules"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    match_field: Mapped[str] = mapped_column(String(20))  # description | merchant | provider_category
    match_type: Mapped[str] = mapped_column(String(20))  # contains | equals | starts_with
    pattern: Mapped[str] = mapped_column(String(100))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_sources.id", ondelete="CASCADE"))
    direction: Mapped[str] = mapped_column(String(10), default="any", server_default=text("'any'"))
    category: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
