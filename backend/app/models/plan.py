import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.assumption_curve import AssumptionCurve
    from app.models.cash_flow_priority import CashFlowPriority
    from app.models.charity import CharityEntity
    from app.models.drawdown_order import DrawdownOrder
    from app.models.expense import Expense
    from app.models.income import IncomeStream
    from app.models.liability import Liability
    from app.models.milestone import Milestone
    from app.models.real_asset import RealAsset
    from app.models.residency_period import ResidencyPeriod
    from app.models.spouse import Spouse
    from app.models.user import User


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_plans_id_user"),
        ForeignKeyConstraint(["client_id", "user_id"], ["planning_clients.id", "planning_clients.user_id"], name="fk_plans_client_owner"),
        CheckConstraint(
            "plan_type IN ('NOW', 'FIXED_DATE')",
            name="ck_plans_plan_type",
        ),
        CheckConstraint(
            "filing_status IN ('single', 'married_filing_jointly', "
            "'married_filing_separately', 'head_of_household')",
            name="ck_plans_filing_status",
        ),
        CheckConstraint(
            "birth_month IS NULL OR (birth_month BETWEEN 1 AND 12)",
            name="ck_plans_birth_month",
        ),
        CheckConstraint(
            "parent_plan_id IS NULL OR parent_plan_id <> id",
            name="ck_plans_not_own_parent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # NULL is the explicitly retained legacy shared-account model. Client
    # plans always use their own CurrentAccount rows, including NOW plans.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("planning_clients.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priorities_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    plan_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'NOW'")
    )
    start_date: Mapped[date | None] = mapped_column()
    snapshot_conditions: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    birth_year: Mapped[int] = mapped_column(Integer, nullable=False)
    birth_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filing_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'single'")
    )
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # Local income tax selection for state_code (see coastmath.schemas.local_tax);
    # residency periods carry their own selection.
    local_tax: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Country tax regime (ISO 3166-1 alpha-2, "XX" = custom). Never stored in
    # state_code: country and state codes collide (CA, DE, IL).
    tax_country: Mapped[str] = mapped_column(String(2), nullable=False, server_default=text("'US'"))
    tax_region: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # ISO 4217 display currency; the engine has no foreign exchange.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'USD'"))
    # Country benefits, custom regime and wealth/transaction tax overrides
    # (coastmath.schemas.intl_settings.IntlSettings); NULL = none.
    intl_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    life_expectancy: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("95")
    )
    filing_status_changes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    sepp_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    spending_rules: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    tax_settings: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    baseline_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id"), nullable=True
    )
    estate_settings: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    # Free-text assumptions record; plain text only, rendered as text.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    healthcare_settings: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    # Saved withdrawal strategy (coastmath.schemas.withdrawal_strategy); NULL = none.
    withdrawal_strategy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Opt-in cash-reserve withdrawal policy (app.schemas.cash_reserve); NULL = none.
    cash_reserve_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # A scenario's Main plan (app.scenarios): Main's saves flow into this plan
    # except the values it changed itself. Same owner and client as Main,
    # enforced by the API; NULL for every ordinary plan.
    parent_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL", name="fk_plans_parent_plan_id"), nullable=True, index=True
    )
    # A scenario's last sync from Main: status, time and skipped items.
    scenario_sync: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    # An archived plan is kept but inactive until it is restored.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Editing-window state for an access policy that limits editing
    # (app.access): when a client first showed the closing notice, and a
    # one-time grace given when no notice was seen.
    edit_notice_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edit_grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def edit_window_ends_at(self) -> datetime | None:
        """When the access policy stops editing this plan; None when it never does."""
        from app.access import policy  # noqa: PLC0415 - app.access imports this module
        return policy().edit_window_ends_at(self)

    # Relationships
    baseline_plan: Mapped["Plan | None"] = relationship(
        "Plan", remote_side=[id], foreign_keys=[baseline_plan_id]
    )
    user: Mapped["User"] = relationship(back_populates="plans")
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    income_streams: Mapped[list["IncomeStream"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    priorities: Mapped[list["CashFlowPriority"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    drawdown_order: Mapped[list["DrawdownOrder"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    assumption_curves: Mapped[list["AssumptionCurve"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    real_assets: Mapped[list["RealAsset"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    liabilities: Mapped[list["Liability"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    spouse: Mapped["Spouse | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan"
    )
    charity_entities: Mapped[list["CharityEntity"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    residency_periods: Mapped[list["ResidencyPeriod"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
