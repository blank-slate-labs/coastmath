import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.income import IncomeStream
    from app.models.milestone import Milestone
    from app.models.plan import Plan


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint(
            "start_month BETWEEN 1 AND 12",
            name="ck_expenses_start_month",
        ),
        CheckConstraint(
            "end_month BETWEEN 1 AND 12",
            name="ck_expenses_end_month",
        ),
        CheckConstraint(
            "growth_cap IS NULL OR growth_cap >= 0",
            name="ck_expenses_growth_cap_nonnegative",
        ),
        CheckConstraint(
            "recurrence_years IS NULL OR recurrence_years > 0",
            name="ck_expenses_recurrence_years_positive",
        ),
        CheckConstraint(
            "payroll_tax_treatment IN ('pre_tax', 'after_tax')",
            name="ck_expenses_payroll_tax_treatment",
        ),
        CheckConstraint(
            "amount_frequency IS NULL OR amount_frequency IN "
            "('annual', 'quarterly', 'monthly', 'semimonthly', 'biweekly', 'weekly')",
            name="ck_expenses_amount_frequency",
        ),
        CheckConstraint(
            "discretionary_percent IS NULL OR discretionary_percent BETWEEN 0 AND 100",
            name="ck_expenses_discretionary_percent_range",
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
    annual_amount: Mapped[float] = mapped_column(
        Numeric(15, 2), nullable=False, server_default=text("0")
    )
    # Entry unit for display only (coastmath/schemas/amount_frequency.py); the
    # engine reads annual_amount. NULL is a record saved before units were stored.
    amount_frequency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    start_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )
    end_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )
    inflation_linked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    growth_rate: Mapped[float | None] = mapped_column(Numeric(7, 4))
    growth_cap: Mapped[float | None] = mapped_column(Numeric(15, 2))
    growth_cap_inflation_linked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    recurrence_years: Mapped[int | None] = mapped_column()
    recurrence_growth_rate: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False, server_default=text("0")
    )
    is_payroll_deduction: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Legacy payroll expenses were treated as pre-tax. Keep that behavior for
    # existing rows while allowing an explicit after-tax cash-only treatment.
    payroll_tax_treatment: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pre_tax'")
    )
    # Which wage bases (federal, state, local, fica) the deduction reduces.
    # NULL or a missing key keeps the payroll_tax_treatment default
    # (coastmath/engine/payroll_elections.py).
    payroll_tax_elections: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tied_income_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("income_streams.id", ondelete="SET NULL")
    )
    specific_funding_source_id: Mapped[uuid.UUID | None] = mapped_column()
    # Ordered primary/backup accounts. Keep the scalar above for legacy clients.
    specific_funding_source_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    start_month: Mapped[int | None] = mapped_column()
    end_month: Mapped[int | None] = mapped_column()
    category: Mapped[str | None] = mapped_column(String(100))
    # Percent (0-100) that flexible spending may cut. NULL keeps the category's
    # all-or-nothing meaning; when set it wins and category mirrors it
    # (app/schemas/expense.py sync_expense_category).
    discretionary_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Qualified higher education expense: 529 withdrawals up to it are tax
    # free (coastmath/engine/education_savings.py).
    qualified_education: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="expenses")
    start_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[start_milestone_id]
    )
    end_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[end_milestone_id]
    )
    tied_income: Mapped["IncomeStream | None"] = relationship(
        foreign_keys=[tied_income_id]
    )
