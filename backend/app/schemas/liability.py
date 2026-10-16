"""Request and response models for saved liability records.

Shared liability types are in ``coastmath.schemas.liability``.
"""
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coastmath.schemas.item_name import ItemName
from coastmath.schemas.liability import (
    InterestMethod,
    LiabilityForgiveness,
    LiabilityRecurrenceFields,
    PaymentType,
)


class LiabilityCreate(LiabilityRecurrenceFields):
    name: ItemName
    principal_balance: float = Field(..., gt=0)
    #: Annual rate in percent: 5.5 means 5.5%. The engine converts to a decimal.
    interest_rate: float = Field(..., ge=0, le=100, description="Annual interest rate in percent (5.5 = 5.5%)")
    term_months: int | None = Field(default=None, gt=0)
    monthly_payment: float | None = Field(default=None, gt=0)
    payment_type: PaymentType = "fixed"
    extra_payment: float = Field(default=0, ge=0)
    payoff_milestone_id: uuid.UUID | None = None
    offset_account_id: uuid.UUID | None = None
    linked_asset_id: uuid.UUID | None = None
    forgiveness: LiabilityForgiveness | None = None
    interest_method: InterestMethod = "monthly"

    @model_validator(mode="after")
    def check_payment_rules(self) -> "LiabilityCreate":
        if self.payment_type == "fixed":
            if self.monthly_payment is None and self.term_months is None:
                raise ValueError(
                    "Either monthly_payment or term_months is required when payment_type is 'fixed'"
                )
        if self.payment_type == "percent_of_balance":
            if self.monthly_payment is not None and not (0 <= self.monthly_payment <= 1):
                raise ValueError(
                    "monthly_payment must be between 0 and 1 when payment_type is 'percent_of_balance'"
                )
        return self


class LiabilityUpdate(BaseModel):
    name: ItemName | None = None
    principal_balance: float | None = Field(default=None, gt=0)
    interest_rate: float | None = Field(default=None, ge=0, le=100, description="Annual interest rate in percent (5.5 = 5.5%)")
    term_months: int | None = Field(default=None, gt=0)
    monthly_payment: float | None = Field(default=None, gt=0)
    payment_type: PaymentType | None = None
    extra_payment: float | None = Field(default=None, ge=0)
    payoff_milestone_id: uuid.UUID | None = None
    offset_account_id: uuid.UUID | None = None
    linked_asset_id: uuid.UUID | None = None
    forgiveness: LiabilityForgiveness | None = None
    interest_method: InterestMethod | None = None
    #: Merged with the saved row and checked in the liabilities router.
    recurrence_years: int | None = Field(default=None, ge=1, le=100)
    recurrence_end_year: int | None = Field(default=None, ge=1900, le=2200)
    recurrence_end_milestone_id: uuid.UUID | None = None


class LiabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    name: str
    principal_balance: float
    #: Annual rate in percent (5.5 = 5.5%).
    interest_rate: float
    term_months: int | None = None
    monthly_payment: float | None = None
    payment_type: PaymentType
    extra_payment: float
    payoff_milestone_id: uuid.UUID | None = None
    offset_account_id: uuid.UUID | None = None
    linked_asset_id: uuid.UUID | None = None
    forgiveness: LiabilityForgiveness | None = None
    # Omitted at their defaults so existing liability reads keep their shape.
    interest_method: InterestMethod = Field(default="monthly", exclude_if=lambda value: value == "monthly")
    recurrence_years: int | None = Field(default=None, exclude_if=lambda value: value is None)
    recurrence_end_year: int | None = Field(default=None, exclude_if=lambda value: value is None)
    recurrence_end_milestone_id: uuid.UUID | None = Field(default=None, exclude_if=lambda value: value is None)
