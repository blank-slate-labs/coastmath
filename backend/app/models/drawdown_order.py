import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.plan import Plan


class DrawdownOrder(Base):
    __tablename__ = "drawdown_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source_account_id: Mapped[uuid.UUID | None] = mapped_column()

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="drawdown_order")
