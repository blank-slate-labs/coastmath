import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.milestone import Milestone
    from app.models.plan import Plan


class CharityEntity(Base):
    __tablename__ = "charity_entities"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('qcd', 'daf', 'direct')",
            name="ck_charity_entities_entity_type",
        ),
        CheckConstraint(
            "funding IN ('cash', 'appreciated_shares')",
            name="ck_charity_entities_funding",
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
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    annual_amount: Mapped[float] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    start_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id"), nullable=True
    )
    end_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id"), nullable=True
    )
    # May identify an immutable FIXED_DATE snapshot account rather than a live
    # CurrentAccount row. Validate scope and IRA type through the owning plan.
    source_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # DAF/direct gifts: "cash", or "appreciated_shares" given from the taxable
    # brokerage account in source_account_id.
    funding: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'cash'"))

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="charity_entities")
    start_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[start_milestone_id]
    )
    end_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[end_milestone_id]
    )
