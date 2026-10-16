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
    from app.models.liability import Liability
    from app.models.plan import Plan


class RealAsset(Base):
    __tablename__ = "real_assets"
    __table_args__ = (
        CheckConstraint(
            "tax_treatment IN ('unspecified', 'personal_use', 'investment', 'rental')",
            name="ck_real_assets_tax_treatment",
        ),
        CheckConstraint("adjusted_basis IS NULL OR adjusted_basis >= 0", name="ck_real_assets_adjusted_basis"),
        CheckConstraint(
            "property_tax_rate IS NULL OR property_tax_rate BETWEEN 0 AND 1",
            name="ck_real_assets_property_tax_rate_range",
        ),
        CheckConstraint(
            "maintenance_rate IS NULL OR maintenance_rate BETWEEN 0 AND 1",
            name="ck_real_assets_maintenance_rate_range",
        ),
        CheckConstraint(
            "insurance_rate IS NULL OR insurance_rate BETWEEN 0 AND 1",
            name="ck_real_assets_insurance_rate_range",
        ),
        CheckConstraint(
            "sale_month BETWEEN 1 AND 12",
            name="ck_real_assets_sale_month_range",
        ),
        CheckConstraint(
            "rental_property_class IS NULL OR rental_property_class IN ('residential', 'nonresidential')",
            name="ck_real_assets_rental_property_class",
        ),
        CheckConstraint(
            "rental_use_rate IS NULL OR rental_use_rate BETWEEN 0 AND 1",
            name="ck_real_assets_rental_use_rate_range",
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
    current_value: Mapped[float] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    adjusted_basis: Mapped[float | None] = mapped_column(Numeric(15, 2))
    tax_treatment: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'unspecified'")
    )
    annual_appreciation_rate: Mapped[float] = mapped_column(
        Numeric(7, 4), server_default=text("0.03")
    )
    is_primary_residence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    auto_liquidate_on_depletion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    liquidation_target_account_id: Mapped[uuid.UUID | None] = mapped_column()
    annual_property_tax: Mapped[float] = mapped_column(
        Numeric(15, 2), server_default=text("0")
    )
    annual_maintenance: Mapped[float] = mapped_column(
        Numeric(15, 2), server_default=text("0")
    )
    property_tax_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    maintenance_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    insurance_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    sale_year: Mapped[int | None] = mapped_column(Integer)
    sale_month: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    # Planned purchase (coastmath.engine.real_estate). Amounts are plan-start
    # (today's) dollars; the loan rate is an annual percent like liabilities.
    purchase_year: Mapped[int | None] = mapped_column(Integer)
    purchase_month: Mapped[int | None] = mapped_column(Integer)
    purchase_price: Mapped[float | None] = mapped_column(Numeric(15, 2))
    down_payment_amount: Mapped[float | None] = mapped_column(Numeric(15, 2))
    down_payment_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    closing_costs: Mapped[float | None] = mapped_column(Numeric(15, 2))
    purchase_funding_account_id: Mapped[uuid.UUID | None] = mapped_column()
    purchase_loan_rate: Mapped[float | None] = mapped_column(Numeric(7, 4))
    purchase_loan_term_months: Mapped[int | None] = mapped_column(Integer)
    selling_cost_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    # Rental property settings (tax_treatment "rental").
    rental_income: Mapped[float | None] = mapped_column(Numeric(15, 2))
    rental_income_growth_rate: Mapped[float | None] = mapped_column(Numeric(7, 4))
    rental_expenses: Mapped[float | None] = mapped_column(Numeric(15, 2))
    rental_expense_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    vacancy_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    rental_property_class: Mapped[str | None] = mapped_column(String(20))
    land_value_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    building_basis: Mapped[float | None] = mapped_column(Numeric(15, 2))
    prior_depreciation: Mapped[float | None] = mapped_column(Numeric(15, 2))
    qbi_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    rental_active_participation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    suspended_passive_loss: Mapped[float | None] = mapped_column(Numeric(15, 2))
    # Home sale exclusion ownership and use start dates (IRC 121).
    owned_since_year: Mapped[int | None] = mapped_column(Integer)
    owned_since_month: Mapped[int | None] = mapped_column(Integer)
    primary_residence_since_year: Mapped[int | None] = mapped_column(Integer)
    primary_residence_since_month: Mapped[int | None] = mapped_column(Integer)
    # Mixed use (rentals): share rented out as a decimal (blank = fully
    # rented) and optional [{"year", "rate"}] steps that change it by year.
    rental_use_rate: Mapped[float | None] = mapped_column(Numeric(7, 6))
    rental_use_schedule: Mapped[list | None] = mapped_column(JSONB)

    # Relationships
    plan: Mapped["Plan"] = relationship(back_populates="real_assets")
    linked_liabilities: Mapped[list["Liability"]] = relationship(
        back_populates="linked_asset"
    )
