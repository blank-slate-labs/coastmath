import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class TaxJurisdiction(Base):
    __tablename__ = "tax_jurisdictions"
    __table_args__ = (
        CheckConstraint(
            "level IN ('federal', 'state', 'local')",
            name="ck_tax_jurisdictions_level",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    jurisdiction_code: Mapped[str | None] = mapped_column(String(10))
    custom_brackets: Mapped[dict | None] = mapped_column(JSONB)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="tax_jurisdictions")
