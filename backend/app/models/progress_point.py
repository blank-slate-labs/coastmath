import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class ProgressPoint(Base):
    __tablename__ = "progress_points"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recorded_date: Mapped[date] = mapped_column(nullable=False)
    net_worth: Mapped[float] = mapped_column(
        Numeric(15, 2), nullable=False, server_default=text("0")
    )
    assets_breakdown: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    liabilities_breakdown: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    auto_logged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="progress_points")
