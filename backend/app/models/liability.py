import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.milestone import Milestone
    from app.models.plan import Plan
    from app.models.real_asset import RealAsset


class Liability(Base):
    __tablename__ = "liabilities"
    __table_args__ = (
        CheckConstraint(
            "payment_type IN ('fixed', 'percent_of_balance', 'custom')",
            name="ck_liabilities_payment_type",
        ),
        CheckConstraint(
            "interest_method IN ('monthly', 'simple', 'daily')",
            name="ck_liabilities_interest_method",
        ),
        CheckConstraint(
            "recurrence_years IS NULL OR recurrence_years BETWEEN 1 AND 100",
            name="ck_liabilities_recurrence_years",
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
    principal_balance: Mapped[float] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    interest_rate: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False
    )
    term_months: Mapped[int | None] = mapped_column(Integer)
    monthly_payment: Mapped[float | None] = mapped_column(Numeric(15, 2))
    payment_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'fixed'")
    )
    extra_payment: Mapped[float] = mapped_column(
        Numeric(15, 2), server_default=text("0")
    )
    payoff_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )
    offset_account_id: Mapped[uuid.UUID | None] = mapped_column()
    linked_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("real_assets.id", ondelete="SET NULL")
    )
    # One-time cancellation of the loan (app/schemas/liability.py
    # ``LiabilityForgiveness``); NULL means the loan is never forgiven.
    forgiveness: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # How interest accrues (app.schemas.liability.InterestMethod).
    interest_method: Mapped[str] = mapped_column(
        String(10), nullable=False, default="monthly", server_default=text("'monthly'")
    )
    # Take the loan again every N years on its original terms
    # (app.schemas.liability.LiabilityRecurrenceFields); NULL never repeats.
    recurrence_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_end_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence_end_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="liabilities")
    payoff_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[payoff_milestone_id]
    )
    linked_asset: Mapped["RealAsset | None"] = relationship(
        back_populates="linked_liabilities", foreign_keys=[linked_asset_id]
    )
