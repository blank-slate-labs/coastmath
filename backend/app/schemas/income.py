"""Request and response models for saved income records.

Shared income types are in ``coastmath.schemas.income``.
"""
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coastmath.schemas.amount_frequency import (
    MAX_ANNUAL_AMOUNT,
    IncomeAmountFrequency,
    check_hourly_fields,
    hourly_annual_amount,
)
from coastmath.schemas.income import (
    ExSpouseRecord,
    GrowthSchedule,
    GrowthSegment,
    IncomeCategoryFields,
    IncomeTaxCategory,
    PensionFormula,
    SsBenefitBasis,
    validate_growth_schedule,
    validate_income_extensions,
    validate_ss_benefit_basis,
)


class IncomeCreate(IncomeCategoryFields):
    frequency: Literal["recurring", "once"] = "recurring"
    recurrence_years: int | None = Field(default=None, ge=1, le=100)
    pension_formula: PensionFormula | None = None
    tax_category: IncomeTaxCategory | None = None
    name: str = Field(..., max_length=255)
    # The clients' money-field cap: a yearly amount past $1 trillion is a typo.
    annual_amount: float = Field(default=0, le=MAX_ANNUAL_AMOUNT)
    # Entry unit for display; annual_amount stays the stored and simulated value.
    amount_frequency: IncomeAmountFrequency | None = None
    # Hourly pay: annual_amount is set from these (amount_frequency.py).
    hourly_rate: float | None = Field(default=None, gt=0, le=1e6)
    hours_per_week: float | None = Field(default=None, gt=0, le=168)
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    growth_rate: float | None = Field(default=None, ge=-100, le=100)  # percent per year
    growth_cap: float | None = Field(default=None, ge=0)
    growth_cap_inflation_linked: bool = False
    withholding_percent: float | None = Field(default=None, ge=0, le=100)  # percent of gross
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    is_active: bool = True
    is_social_security: bool = False
    is_earned_income: bool = True
    is_self_employed: bool = False
    owner: Literal["self", "spouse"] = "self"
    # Social Security only: benefits begin the year the recipient reaches this
    # age unless a start milestone is set, which takes precedence.
    claiming_age: int | None = Field(default=None, ge=62, le=70)
    # Social Security only: "pia" sizes the benefit from pia_monthly (monthly
    # PIA at full retirement age, plan-start dollars) and the claim date;
    # null or "amount" pays annual_amount. expected_benefit_percent (null =
    # 100) scales every PIA-basis payment.
    pia_reflects: Literal["current_record", "continued_work"] = "continued_work"
    covered_years_to_date: int = Field(default=35, ge=1, le=35)
    ss_benefit_basis: SsBenefitBasis | None = None
    pia_monthly: float | None = Field(default=None, ge=0)
    expected_benefit_percent: float | None = Field(default=None, ge=0, le=100)
    # Optional year-segment growth (non-Social-Security streams) and a former
    # spouse's record (PIA-basis Social Security). Null keeps prior behavior.
    growth_schedule: GrowthSchedule | None = None
    ex_spouse: ExSpouseRecord | None = None

    @model_validator(mode="after")
    def check_hourly_pay(self):
        check_hourly_fields(self.amount_frequency, self.hourly_rate, self.hours_per_week)
        # Assign only on a change so unset fields stay out of exclude_unset dumps.
        if self.amount_frequency == "hourly":
            annual = hourly_annual_amount(self.hourly_rate, self.hours_per_week)
            if self.annual_amount != annual:
                self.annual_amount = annual
        else:
            if self.hourly_rate is not None:
                self.hourly_rate = None
            if self.hours_per_week is not None:
                self.hours_per_week = None
        return self

    @model_validator(mode="after")
    def check_ss_benefit_basis(self):
        validate_ss_benefit_basis(self.ss_benefit_basis, self.pia_monthly, self.claiming_age, self.tax_category)
        validate_growth_schedule(self.growth_schedule)
        validate_income_extensions(
            growth_schedule=self.growth_schedule, ex_spouse=self.ex_spouse,
            ss_benefit_basis=self.ss_benefit_basis, tax_category=self.tax_category,
            is_social_security=self.is_social_security, pension_formula=self.pension_formula,
        )
        return self


class IncomeUpdate(IncomeCategoryFields):
    frequency: Literal["recurring", "once"] = "recurring"
    recurrence_years: int | None = Field(default=None, ge=1, le=100)
    pension_formula: PensionFormula | None = None
    tax_category: IncomeTaxCategory | None = None
    name: str | None = Field(default=None, max_length=255)
    annual_amount: float | None = Field(default=None, le=MAX_ANNUAL_AMOUNT)
    # Omitted keeps the saved unit; null clears it to the legacy default.
    amount_frequency: IncomeAmountFrequency | None = None
    # Merged with the saved row in the incomes router (hourly pay).
    hourly_rate: float | None = Field(default=None, gt=0, le=1e6)
    hours_per_week: float | None = Field(default=None, gt=0, le=168)
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    growth_rate: float | None = Field(default=None, ge=-100, le=100)  # percent per year
    growth_cap: float | None = Field(default=None, ge=0)
    growth_cap_inflation_linked: bool | None = None
    withholding_percent: float | None = Field(default=None, ge=0, le=100)  # percent of gross
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    is_active: bool | None = None
    is_social_security: bool | None = None
    is_earned_income: bool | None = None
    is_self_employed: bool | None = None
    owner: Literal["self", "spouse"] | None = None
    claiming_age: int | None = Field(default=None, ge=62, le=70)
    # Validated against the merged saved row in the incomes router.
    pia_reflects: Literal["current_record", "continued_work"] = "continued_work"
    covered_years_to_date: int = Field(default=35, ge=1, le=35)
    ss_benefit_basis: SsBenefitBasis | None = None
    pia_monthly: float | None = Field(default=None, ge=0)
    expected_benefit_percent: float | None = Field(default=None, ge=0, le=100)
    # Validated against the merged saved row in the incomes router.
    growth_schedule: GrowthSchedule | None = None
    ex_spouse: ExSpouseRecord | None = None

    @model_validator(mode="after")
    def check_growth_schedule(self):
        validate_growth_schedule(self.growth_schedule)
        return self


class IncomeRead(BaseModel):
    frequency: Literal["recurring", "once"] = "recurring"
    recurrence_years: int | None = Field(default=None, ge=1, le=100)
    pension_formula: PensionFormula | None = None
    tax_category: IncomeTaxCategory | None = None
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    name: str = Field(max_length=255)
    annual_amount: float
    amount_frequency: IncomeAmountFrequency | None = None
    # Hourly pay only; omitted otherwise so other income reads keep their shape.
    hourly_rate: float | None = Field(default=None, exclude_if=lambda value: value is None)
    hours_per_week: float | None = Field(default=None, exclude_if=lambda value: value is None)
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    growth_rate: float | None = Field(default=None, ge=-100, le=100)  # percent per year
    growth_cap: float | None = None
    growth_cap_inflation_linked: bool = False
    withholding_percent: float | None = Field(default=None, ge=0, le=100)  # percent of gross
    start_month: int | None = None
    end_month: int | None = None
    is_active: bool
    is_social_security: bool = False
    is_earned_income: bool = True
    is_self_employed: bool = False
    owner: Literal["self", "spouse"] = "self"
    claiming_age: int | None = None
    pia_reflects: Literal["current_record", "continued_work"] = "continued_work"
    covered_years_to_date: int = Field(default=35, ge=1, le=35)
    ss_benefit_basis: SsBenefitBasis | None = None
    pia_monthly: float | None = None
    expected_benefit_percent: float | None = None
    growth_schedule: list[GrowthSegment] | None = None
    ex_spouse: ExSpouseRecord | None = None
