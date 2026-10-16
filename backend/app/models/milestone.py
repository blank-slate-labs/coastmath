import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.plan import Plan


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('age', 'date', 'net_worth', 'expense_multiple', 'relative', 'conditions')",
            name="ck_milestones_trigger_type",
        ),
        CheckConstraint(
            "expense_multiple IS NULL OR expense_multiple > 0",
            name="ck_milestones_expense_multiple_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    conditions: Mapped[dict | None] = mapped_column(JSONB)
    trigger_value: Mapped[float | None] = mapped_column(Numeric(15, 2))
    trigger_date: Mapped[date | None] = mapped_column()
    metric: Mapped[str | None] = mapped_column(String(30))
    expense_multiple: Mapped[float | None] = mapped_column(Numeric(7, 2))
    relative_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )
    offset_years: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # A switched-off milestone keeps its details and references but never fires.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="milestones")
