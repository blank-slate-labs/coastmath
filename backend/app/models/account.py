import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class CurrentAccount(Base):
    __tablename__ = "current_accounts"
    __table_args__ = (
        ForeignKeyConstraint(["plan_id", "user_id"], ["plans.id", "plans.user_id"], name="fk_current_accounts_plan_owner", ondelete="CASCADE"),
        CheckConstraint(
            "account_type IN ('checking', 'savings', 'traditional_401k', "
            "'roth_401k', 'traditional_403b', 'roth_403b', 'traditional_457b', "
            "'roth_457b', 'traditional_401a', 'traditional_ira', 'roth_ira', "
            "'taxable_brokerage', 'hsa', 'five_twenty_nine', 'other')",
            name="ck_current_accounts_account_type",
        ),
        CheckConstraint(
            "cost_basis IS NULL OR cost_basis >= 0",
            name="ck_current_accounts_cost_basis_nonnegative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    inherited_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inheritance_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    roth_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Nullable values inside this object inherit the plan's investment
    # assumptions.  Keep the settings together so the schema remains additive.
    investment_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # When voluntary withdrawals may start (schemas.account.WithdrawalLock).
    # Null: any time. Kept apart from investment_settings, which holds rates.
    withdrawal_lock: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Rule of 55 separation year and spouse-sole-beneficiary election
    # (schemas.account.AccountDistributionSettings). Null: neither.
    distribution_settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Country account kind "<CC>:<kind_id>" (coastmath.engine.intl_accounts); its
    # rules replace the US account rules. account_type follows its category.
    intl_account_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    balance: Mapped[float] = mapped_column(
        Numeric(15, 2), nullable=False, server_default=text("0")
    )
    owner: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'self'")
    )
    beneficiary_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'non_edb'")
    )
    cost_basis: Mapped[float | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    # Employee contributions in a traditional retirement account that the
    # state of residence at plan start already taxed (Pennsylvania, New
    # Jersey, Massachusetts); recovered on withdrawal. Null means none.
    state_taxed_basis: Mapped[float | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    # Liquid net worth override: NULL counts the account as liquid unless it
    # is withdrawal-locked that year; true always counts it; false never does.
    include_in_liquid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="accounts")
