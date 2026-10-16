import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.milestone import Milestone
    from app.models.plan import Plan


class Spouse(Base):
    __tablename__ = "spouses"
    __table_args__ = (
        UniqueConstraint("plan_id", name="uq_spouses_plan_id"),
        CheckConstraint("birth_month BETWEEN 1 AND 12", name="ck_spouses_birth_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(255))
    birth_year: Mapped[int | None] = mapped_column(Integer)
    birth_month: Mapped[int | None] = mapped_column(Integer)
    life_expectancy: Mapped[int | None] = mapped_column(Integer)
    income_streams: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'")
    )
    retirement_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="spouse")
    retirement_milestone: Mapped["Milestone | None"] = relationship()
