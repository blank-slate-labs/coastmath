"""Request and response models for saved cash flow priority records.

Shared cash flow priority types are in ``coastmath.schemas.cash_flow_priority``.
"""
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coastmath.schemas.cash_flow_priority import (
    AllocationFields,
    AllocationMode,
    ContributionFormulaFields,
    ConversionMode,
    EmployerMatch,
    FundingModeFields,
    LimitMode,
    PriorityType,
    TransferFrequency,
)


class CashFlowPriorityCreate(ContributionFormulaFields, AllocationFields, FundingModeFields):
    priority_rank: int
    target_account_id: uuid.UUID | None = None
    #: debt_payment rules only: the loan that receives the allocation.
    target_liability_id: uuid.UUID | None = None
    max_annual_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    priority_type: PriorityType | None = None
    source_account_id: uuid.UUID | None = None
    source_income_id: uuid.UUID | None = None
    employee_rate: float = Field(default=0, ge=0, le=100)
    employer_match_rate: float = Field(default=0, ge=0, le=100)
    target_balance: float | None = Field(default=None, ge=0)
    conversion_mode: ConversionMode = "fixed"
    bracket_ceiling_rate: float | None = Field(default=None, ge=0, le=1)  # decimal, e.g. 0.22
    magi_cap: float | None = Field(default=None, ge=0)
    # Roth IRA contribution rules: nondeductible traditional IRA contribution
    # converted immediately, so the income phaseout does not apply.
    backdoor_roth: bool = False
    # Roth conversion / gain harvest "fill_bracket" rules: size the year's
    # amount from the plan's tax target instead of the rule's own ceiling.
    use_plan_tax_target: bool = False
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    #: Omitted at "annual" so dumps (and preserved-rule matching) keep their shape.
    transfer_frequency: TransferFrequency = Field(default="annual", exclude_if=lambda value: value == "annual")

    @model_validator(mode="after")
    def source_account_required_for_transfer_types(self) -> "CashFlowPriorityCreate":
        if self.transfer_frequency != "annual" and self.priority_type != "transfer":
            raise ValueError("A monthly frequency applies only to transfer rules")
        if self.priority_type in ("transfer", "roth_conversion", "gain_harvest") and self.source_account_id is None:
            raise ValueError(
                f"source_account_id is required when priority_type is '{self.priority_type}'"
            )
        if self.use_plan_tax_target:
            if self.priority_type not in ("roth_conversion", "gain_harvest"):
                raise ValueError("use_plan_tax_target applies only to roth_conversion or gain_harvest priorities")
            if self.conversion_mode != "fill_bracket":
                raise ValueError("use_plan_tax_target requires conversion_mode 'fill_bracket'")
        if self.conversion_mode == "fill_bracket":
            if self.priority_type not in ("roth_conversion", "gain_harvest"):
                raise ValueError("conversion_mode 'fill_bracket' applies only to roth_conversion or gain_harvest priorities")
            if self.bracket_ceiling_rate is None and not self.use_plan_tax_target:
                raise ValueError("bracket_ceiling_rate is required when conversion_mode is 'fill_bracket'")
        if self.priority_type == "gain_harvest" and self.conversion_mode != "fill_bracket":
            raise ValueError("gain_harvest priorities must use conversion_mode 'fill_bracket' with a capital-gains bracket rate")
        if self.priority_type in ("income_percent", "after_tax_401k") and self.source_income_id is None:
            raise ValueError(
                f"source_income_id is required when priority_type is '{self.priority_type}'"
            )
        if self.priority_type == "debt_payment":
            if self.target_liability_id is None:
                raise ValueError("target_liability_id is required when priority_type is 'debt_payment'")
            if (self.target_account_id is not None or self.source_account_id is not None
                    or self.source_income_id is not None or self.target_balance is not None
                    or self.backdoor_roth):
                raise ValueError("A debt payment rule names only a loan, not an account, income or target balance")
        elif self.target_liability_id is not None:
            raise ValueError("target_liability_id applies only to debt_payment rules")
        return self


class CashFlowPriorityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    priority_rank: int
    allocation_mode: AllocationMode = "remaining"
    allocation_value: float | None = None
    target_account_id: uuid.UUID | None = None
    target_liability_id: uuid.UUID | None = None
    max_annual_amount: float | None = None
    priority_type: PriorityType | None = None
    source_account_id: uuid.UUID | None = None
    source_income_id: uuid.UUID | None = None
    employee_rate: float = 0
    employer_match_rate: float = 0
    target_balance: float | None = None
    conversion_mode: ConversionMode = "fixed"
    bracket_ceiling_rate: float | None = None
    magi_cap: float | None = None
    backdoor_roth: bool = False
    use_plan_tax_target: bool = False
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    employer_match: EmployerMatch | None = None
    limit_mode: LimitMode = "irs"
    custom_annual_limit: float | None = None
    withdraw_if_short: bool = False
    reduce_employer_contribution: bool = False
    transfer_frequency: TransferFrequency = Field(default="annual", exclude_if=lambda value: value == "annual")


class CashFlowPriorityBulkUpdate(BaseModel):
    items: list[CashFlowPriorityCreate] = Field(max_length=200)
    expected_revision: int = Field(ge=0)


class PrioritySet(BaseModel):
    items: list[CashFlowPriorityRead]
    revision: int
