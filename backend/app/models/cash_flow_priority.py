import uuid
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


class CashFlowPriority(Base):
    __tablename__ = "cash_flow_priorities"
    __table_args__ = (
        CheckConstraint(
            "(allocation_mode = 'remaining' AND allocation_value IS NULL) OR "
            "(allocation_mode = 'amount' AND allocation_value >= 0 AND allocation_value IS NOT NULL) OR "
            "(allocation_mode = 'percentage' AND allocation_value BETWEEN 0 AND 100 AND allocation_value IS NOT NULL)",
            name="ck_allocation_mode_value",
        ),
        CheckConstraint(
            "target_balance IS NULL OR target_balance >= 0",
            name="ck_cash_flow_priorities_target_balance_nonnegative",
        ),
        CheckConstraint(
            "employee_rate BETWEEN 0 AND 100",
            name="ck_cash_flow_priorities_employee_rate_range",
        ),
        CheckConstraint(
            "employer_match_rate BETWEEN 0 AND 100",
            name="ck_cash_flow_priorities_employer_match_rate_range",
        ),
        CheckConstraint(
            "limit_mode IN ('irs', 'custom')",
            name="ck_cash_flow_priorities_limit_mode",
        ),
        CheckConstraint(
            "custom_annual_limit IS NULL OR custom_annual_limit >= 0",
            name="ck_cash_flow_priorities_custom_annual_limit_nonnegative",
        ),
        CheckConstraint(
            "transfer_frequency IN ('annual', 'monthly')",
            name="ck_cash_flow_priorities_transfer_frequency",
        ),
        CheckConstraint(
            "priority_type IN ('contribution', 'transfer', 'roth_conversion', 'income_percent', "
            "'pre_tax_contribution', 'gain_harvest', 'after_tax_401k', 'debt_payment')",
            name="ck_cash_flow_priorities_priority_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'remaining'")
    )
    allocation_value: Mapped[float | None] = mapped_column(Numeric(15, 2))
    target_account_id: Mapped[uuid.UUID | None] = mapped_column()
    # debt_payment rules: the same-plan liability paid down (no FK, like
    # target_account_id; deleting a referenced loan is refused).
    target_liability_id: Mapped[uuid.UUID | None] = mapped_column()
    max_annual_amount: Mapped[float | None] = mapped_column(Numeric(15, 2))
    priority_type: Mapped[str | None] = mapped_column(String(50))
    source_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("current_accounts.id"), nullable=True
    )
    source_income_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("income_streams.id", ondelete="SET NULL"), nullable=True
    )
    employee_rate: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    employer_match_rate: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("0")
    )
    target_balance: Mapped[float | None] = mapped_column(Numeric(15, 2))
    conversion_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'fixed'")
    )
    bracket_ceiling_rate: Mapped[float | None] = mapped_column(Numeric(5, 4))
    magi_cap: Mapped[float | None] = mapped_column(Numeric(15, 2))
    # Roth IRA contribution rules only: fund through a nondeductible traditional
    # IRA contribution converted at once, bypassing the income phaseout.
    backdoor_roth: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Roth conversion / gain harvest rules: size from the plan's tax target
    # (plans.tax_settings.tax_target) instead of bracket_ceiling_rate/magi_cap.
    use_plan_tax_target: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Employer formula for income_percent rules (app.schemas.cash_flow_priority
    # .EmployerMatch). NULL keeps employer_match_rate as a percent of pay.
    employer_match: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # "custom" lowers the rule's account limit to custom_annual_limit
    # (today's dollars); it never raises the IRS limit.
    limit_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'irs'")
    )
    custom_annual_limit: Mapped[float | None] = mapped_column(Numeric(15, 2))
    # True runs the rule ahead of other surplus rules and draws any surplus
    # shortfall from the withdrawal order; false funds it from income only.
    withdraw_if_short: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # income_percent rules funded from income: cut a flat employer
    # contribution in proportion when pay cannot cover the deferral.
    reduce_employer_contribution: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # transfer rules: "monthly" spreads the year's amount over the rule's
    # active months (coastmath.engine.waterfall.execute_transfers).
    transfer_frequency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="annual", server_default=text("'annual'")
    )
    start_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )
    end_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="priorities")
