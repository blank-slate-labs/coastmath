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
    from app.models.milestone import Milestone
    from app.models.plan import Plan


class IncomeStream(Base):
    __tablename__ = "income_streams"
    __table_args__ = (
        CheckConstraint("frequency IN ('recurring', 'once')", name="ck_income_streams_frequency"),
        CheckConstraint("recurrence_years IS NULL OR recurrence_years BETWEEN 1 AND 100", name="ck_income_streams_recurrence_years"),
        CheckConstraint("pia_reflects IN ('current_record', 'continued_work')", name="ck_income_streams_pia_reflects"),
        CheckConstraint("covered_years_to_date BETWEEN 1 AND 35", name="ck_income_streams_covered_years"),
        CheckConstraint("owner IN ('self', 'spouse')", name="ck_income_streams_owner"),
        CheckConstraint(
            "tax_category IN ('employment', 'self_employment', 'qualified_pension', 'investment', "
            "'nonqualified_annuity', 'other_ordinary', 'social_security', 'nontaxable')",
            name="ck_income_tax_category",
        ),
        CheckConstraint(
            "start_month BETWEEN 1 AND 12",
            name="ck_income_streams_start_month",
        ),
        CheckConstraint(
            "end_month BETWEEN 1 AND 12",
            name="ck_income_streams_end_month",
        ),
        CheckConstraint(
            "growth_cap IS NULL OR growth_cap >= 0",
            name="ck_income_streams_growth_cap_nonnegative",
        ),
        CheckConstraint(
            "claiming_age IS NULL OR claiming_age BETWEEN 62 AND 70",
            name="ck_income_streams_claiming_age_range",
        ),
        CheckConstraint(
            "amount_frequency IS NULL OR amount_frequency IN "
            "('annual', 'quarterly', 'monthly', 'semimonthly', 'biweekly', 'weekly', 'hourly')",
            name="ck_income_streams_amount_frequency",
        ),
        CheckConstraint(
            "hourly_rate IS NULL OR hourly_rate > 0",
            name="ck_income_streams_hourly_rate_positive",
        ),
        CheckConstraint(
            "hours_per_week IS NULL OR (hours_per_week > 0 AND hours_per_week <= 168)",
            name="ck_income_streams_hours_per_week_range",
        ),
        CheckConstraint(
            "ss_benefit_basis IS NULL OR ss_benefit_basis IN ('amount', 'pia')",
            name="ck_income_streams_ss_benefit_basis",
        ),
        CheckConstraint(
            "pia_monthly IS NULL OR pia_monthly >= 0",
            name="ck_income_streams_pia_monthly_nonnegative",
        ),
        CheckConstraint(
            "expected_benefit_percent IS NULL OR expected_benefit_percent BETWEEN 0 AND 100",
            name="ck_income_streams_expected_benefit_percent_range",
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
    # Hourly pay (amount_frequency 'hourly'): annual_amount is the rate x
    # weekly hours x 52, set by the server. NULL for every other unit.
    hourly_rate: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    hours_per_week: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    start_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )
    end_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("milestones.id", ondelete="SET NULL")
    )
    growth_rate: Mapped[float | None] = mapped_column(Numeric(7, 4))
    growth_cap: Mapped[float | None] = mapped_column(Numeric(15, 2))
    growth_cap_inflation_linked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    withholding_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))
    start_month: Mapped[int | None] = mapped_column()
    end_month: Mapped[int | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_social_security: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_earned_income: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_self_employed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    tax_category: Mapped[str | None] = mapped_column(String(32))
    owner: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'self'"))
    # Social Security only: the age benefits begin when no start milestone is set.
    claiming_age: Mapped[int | None] = mapped_column(Integer)
    # Social Security only: NULL/"amount" pays annual_amount; "pia" sizes the
    # benefit from pia_monthly (plan-start dollars) and the claim date.
    ss_benefit_basis: Mapped[str | None] = mapped_column(String(8))
    pia_reflects: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'continued_work'"))
    covered_years_to_date: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("35"))
    pia_monthly: Mapped[float | None] = mapped_column(Numeric(12, 2))
    # Percent (0-100) of PIA-basis benefits expected to be paid; NULL = 100.
    expected_benefit_percent: Mapped[float | None] = mapped_column(Numeric(5, 2))

    frequency: Mapped[str] = mapped_column(String(12), nullable=False, server_default=text("'recurring'"))
    recurrence_years: Mapped[int | None] = mapped_column(Integer)
    pension_formula: Mapped[dict | None] = mapped_column(JSONB)
    # Ordered growth segments (app/schemas/income.py GrowthSegment); NULL keeps
    # growth_rate or curve growth in every year.
    growth_schedule: Mapped[list | None] = mapped_column(JSONB)
    # PIA-basis Social Security only: a former spouse's record (ExSpouseRecord).
    ex_spouse: Mapped[dict | None] = mapped_column(JSONB)

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="income_streams")
    start_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[start_milestone_id]
    )
    end_milestone: Mapped["Milestone | None"] = relationship(
        foreign_keys=[end_milestone_id]
    )
