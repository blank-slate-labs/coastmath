import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.plan import Plan


class AssumptionCurve(Base):
    __tablename__ = "assumption_curves"
    __table_args__ = (
        CheckConstraint(
            "curve_type IN ('inflation', 'market_return', 'bond_return', "
            "'bond_allocation', 'dividend_yield', 'wage_growth', "
            "'social_security_cola', 'cash_yield')",
            name="ck_assumption_curves_curve_type",
        ),
        CheckConstraint(
            "mode IN ('fixed', 'curve')",
            name="ck_assumption_curves_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    curve_type: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'fixed'")
    )
    fixed_rate: Mapped[float | None] = mapped_column(Numeric(7, 4))
    control_points: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'")
    )

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="assumption_curves")
