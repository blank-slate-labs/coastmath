"""Request and response models for saved expense records.

Shared expense types are in ``coastmath.schemas.expense``.
"""
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coastmath.schemas.amount_frequency import MAX_ANNUAL_AMOUNT, AmountFrequency
from coastmath.schemas.expense import (  # noqa: F401 - re-exported for private callers
    ExpenseCategory,
    PayrollTaxElections,
    PayrollTaxTreatment,
    category_for_discretionary_percent,
    omit_none,
    sync_expense_category,
    validate_funding_order,
)


class ExpenseCreate(BaseModel):
    name: str = Field(..., max_length=255)
    # The clients' money-field cap: a yearly amount past $1 trillion is a typo.
    annual_amount: float = Field(default=0, le=MAX_ANNUAL_AMOUNT)
    # Entry unit for display; annual_amount stays the stored and simulated value.
    amount_frequency: AmountFrequency | None = None
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    inflation_linked: bool = True
    growth_rate: float | None = Field(default=None, ge=-100, le=100)  # percent per year; None = inflation setting
    growth_cap: float | None = Field(default=None, ge=0)
    growth_cap_inflation_linked: bool = False
    recurrence_years: int | None = Field(default=None, gt=0)
    recurrence_growth_rate: float = Field(default=0, ge=-100, le=100)  # percent per occurrence
    is_payroll_deduction: bool = False
    payroll_tax_treatment: PayrollTaxTreatment = "pre_tax"
    # Explicit wage-base elections; None keeps the treatment's defaults.
    payroll_tax_elections: PayrollTaxElections | None = Field(default=None, exclude_if=omit_none)
    tied_income_id: uuid.UUID | None = None
    specific_funding_source_id: uuid.UUID | None = None
    specific_funding_source_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    category: ExpenseCategory | None = None
    # Share of the amount that flexible spending may cut, 0-100. None keeps
    # the category's all-or-nothing meaning. When set it wins, and category
    # is rewritten to match (sync_expense_category).
    discretionary_percent: float | None = Field(default=None, ge=0, le=100)
    # Qualified higher education expense: 529 withdrawals up to the year's
    # marked amounts are tax free.
    qualified_education: bool = False

    @model_validator(mode="after")
    def _check_funding_order(self):
        validate_funding_order(self.specific_funding_source_ids, self.specific_funding_source_id)
        if self.discretionary_percent is not None:
            self.category = category_for_discretionary_percent(self.discretionary_percent)
        return self


class ExpenseEditValues(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    annual_amount: float | None = Field(default=None, le=MAX_ANNUAL_AMOUNT)
    # Omitted keeps the saved unit; null clears it to the legacy default.
    amount_frequency: AmountFrequency | None = None
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    inflation_linked: bool | None = None
    growth_rate: float | None = Field(default=None, ge=-100, le=100)  # percent per year; None = inflation setting
    growth_cap: float | None = Field(default=None, ge=0)
    growth_cap_inflation_linked: bool | None = None
    recurrence_years: int | None = Field(default=None, gt=0)
    recurrence_growth_rate: float | None = Field(default=None, ge=-100, le=100)
    is_payroll_deduction: bool | None = None
    payroll_tax_treatment: PayrollTaxTreatment = "pre_tax"
    # Explicit wage-base elections; None keeps the treatment's defaults.
    payroll_tax_elections: PayrollTaxElections | None = None
    tied_income_id: uuid.UUID | None = None
    specific_funding_source_id: uuid.UUID | None = None
    specific_funding_source_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    category: ExpenseCategory | None = None
    # Omitted keeps the saved percent; null returns to the category's meaning.
    # The router keeps category in step (sync_expense_category).
    discretionary_percent: float | None = Field(default=None, ge=0, le=100)
    qualified_education: bool | None = None

    @model_validator(mode="after")
    def _check_funding_order(self):
        validate_funding_order(self.specific_funding_source_ids, self.specific_funding_source_id)
        return self


class ExpenseExpectedValues(ExpenseEditValues):
    model_config = ConfigDict(extra="forbid")


class ExpenseUpdate(ExpenseEditValues):
    # Optional for older clients. Participating editors send the opening value
    # of every changed field; unrelated fields can still merge independently.
    expected_values: ExpenseExpectedValues | None = None


class ExpenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    name: str = Field(max_length=255)
    annual_amount: float
    amount_frequency: AmountFrequency | None = None
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    inflation_linked: bool
    growth_rate: float | None = Field(default=None, ge=-100, le=100)  # percent per year; None = inflation setting
    growth_cap: float | None = None
    growth_cap_inflation_linked: bool = False
    recurrence_years: int | None = None
    recurrence_growth_rate: float = Field(default=0, ge=-100, le=100)  # percent per occurrence
    is_payroll_deduction: bool
    payroll_tax_treatment: PayrollTaxTreatment = "pre_tax"
    # Explicit wage-base elections; None keeps the treatment's defaults.
    payroll_tax_elections: PayrollTaxElections | None = Field(default=None, exclude_if=omit_none)
    tied_income_id: uuid.UUID | None = None
    specific_funding_source_id: uuid.UUID | None = None
    specific_funding_source_ids: list[uuid.UUID] | None = None
    start_month: int | None = None
    end_month: int | None = None
    category: ExpenseCategory | None = None
    discretionary_percent: float | None = Field(default=None, ge=0, le=100)
    qualified_education: bool = False
