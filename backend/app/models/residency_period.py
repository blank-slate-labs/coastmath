import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.milestone import Milestone
    from app.models.plan import Plan


class ResidencyPeriod(Base):
    __tablename__ = "residency_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    # Required when the period's country is the US; ignored abroad.
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # Null means the plan's tax_country and tax_region.
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    region: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Local income tax selection for this residence (coastmath.schemas.local_tax).
    local_tax: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    start_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True
    )
    end_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True
    )
    start_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    plan: Mapped["Plan"] = relationship(back_populates="residency_periods")
    start_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[start_milestone_id]
    )
    end_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[end_milestone_id]
    )
