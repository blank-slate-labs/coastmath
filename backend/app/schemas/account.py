"""Request and response models for saved account records.

Shared account types are in ``coastmath.schemas.account``.
"""
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from coastmath.engine import intl_bridge
from coastmath.engine.account_types import (
    TRADITIONAL_RETIREMENT_TYPES,
)
from coastmath.schemas.account import (  # noqa: F401 - re-exported for private callers
    BASIS_ACCOUNT_TYPES,
    INDIVIDUAL_ONLY_ACCOUNT_TYPES,
    JOINT_OWNER_REASON,
    AccountCreate,
    AccountDistributionSettings,
    AccountInvestmentSettings,
    AccountType,
    BeneficiaryType,
    WithdrawalLock,
    coerce_intl_account_type,
    inherited_year_not_future,
    joint_owner_not_allowed,
)
from coastmath.schemas.amount_frequency import MAX_ANNUAL_AMOUNT
from coastmath.schemas.inheritance_settings import InheritanceSettings
from coastmath.schemas.roth_settings import RothSettings


class AccountUpdate(BaseModel):
    #: Omit to keep the saved lock; an explicit null removes it.
    withdrawal_lock: WithdrawalLock | None = None
    #: Omit to keep the saved settings; an explicit null removes them.
    distribution_settings: AccountDistributionSettings | None = None
    investment_settings: AccountInvestmentSettings | None = None
    inheritance_settings: InheritanceSettings | None = None
    roth_settings: RothSettings | None = None
    inherited_year: int | None = Field(default=None, ge=1900, le=2200)
    name: str | None = Field(default=None, max_length=255)
    account_type: AccountType | None = None
    balance: float | None = Field(default=None, ge=0, le=MAX_ANNUAL_AMOUNT, description="Current balance; cannot be negative")
    owner: str | None = None
    beneficiary_type: BeneficiaryType | None = None
    cost_basis: float | None = Field(default=None, ge=0, le=MAX_ANNUAL_AMOUNT)
    state_taxed_basis: float | None = Field(default=None, ge=0, lt=1e13)
    #: Omit to keep the saved kind; an explicit null removes it.
    intl_account_kind: str | None = Field(default=None, max_length=40, pattern=intl_bridge.KIND_PATTERN.pattern)
    #: Omit to keep the saved override; an explicit null restores the default.
    include_in_liquid: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _intl_account_type(cls, data: Any) -> Any:
        return coerce_intl_account_type(data)

    _inherited_year_not_future = field_validator("inherited_year")(inherited_year_not_future)

    @model_validator(mode="after")
    def _null_cost_basis_for_non_taxable(self) -> "AccountUpdate":
        if (
            self.account_type is not None
            and self.account_type not in BASIS_ACCOUNT_TYPES
        ):
            self.cost_basis = None
        if self.account_type is not None and self.account_type not in TRADITIONAL_RETIREMENT_TYPES:
            self.state_taxed_basis = None
        return self


class AccountRead(BaseModel):
    withdrawal_lock: WithdrawalLock | None = None
    distribution_settings: AccountDistributionSettings | None = None
    investment_settings: AccountInvestmentSettings | None = None
    inheritance_settings: InheritanceSettings | None = None
    roth_settings: RothSettings | None = None
    inherited_year: int | None = None
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    plan_id: uuid.UUID | None = None
    name: str = Field(max_length=255)
    account_type: AccountType
    balance: float
    owner: str
    beneficiary_type: BeneficiaryType
    cost_basis: float | None = None
    state_taxed_basis: float | None = None
    # Omitted while unset, so existing account reads keep their shape.
    intl_account_kind: str | None = Field(default=None, exclude_if=lambda value: value is None)
    # Liquid net worth override; omitted while unset like intl_account_kind.
    include_in_liquid: bool | None = Field(default=None, exclude_if=lambda value: value is None)
