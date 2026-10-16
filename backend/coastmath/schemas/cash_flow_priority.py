from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ConversionMode = Literal["fixed", "fill_bracket"]
#: How often a transfer rule moves money: once a year after the year's growth,
#: or in equal monthly parts over the rule's active months.
TransferFrequency = Literal["annual", "monthly"]
AllocationMode = Literal["remaining", "percentage", "amount"]
LimitMode = Literal["irs", "custom"]

#: Rule types whose contributions a custom annual limit can lower.
CUSTOM_LIMIT_PRIORITY_TYPES = (None, "contribution", "income_percent", "pre_tax_contribution")


class EmployerMatchTier(BaseModel):
    """``match_percent`` of deferrals on the next ``up_to_percent_of_pay`` of pay (0..100 scale)."""

    model_config = ConfigDict(extra="forbid")

    match_percent: float = Field(ge=0, le=500, allow_inf_nan=False)
    up_to_percent_of_pay: float = Field(gt=0, le=100, allow_inf_nan=False)


class EmployerMatch(BaseModel):
    """Employer contribution formula for an ``income_percent`` payroll rule.

    Tiers stack in order on the employee's actual deferral as a percent of
    pay; ``nonelective_percent`` of pay is added regardless of deferrals and
    ``cap_amount`` (today's dollars, indexed with inflation) caps the year's
    total. ``true_up`` false matches each pay period, so deferrals that stop
    at the annual limit stop the match. ``roth`` deposits the employer money
    in the owner's Roth account of the same plan type, which must exist.
    """

    model_config = ConfigDict(extra="forbid")

    tiers: list[EmployerMatchTier] = Field(default_factory=list, max_length=10)
    cap_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    nonelective_percent: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    true_up: bool = True
    roth: bool = False

    @model_validator(mode="after")
    def _tiers_fit_in_pay(self) -> "EmployerMatch":
        if sum(tier.up_to_percent_of_pay for tier in self.tiers) > 100 + 1e-9:
            raise ValueError("Match tiers cannot cover more than 100% of pay")
        return self


class ContributionFormulaFields(BaseModel):
    """Employer formula and plan limit shared by persisted and stateless rules."""

    employer_match: EmployerMatch | None = None
    limit_mode: LimitMode = "irs"
    custom_annual_limit: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_contribution_formula(self) -> "ContributionFormulaFields":
        priority_type = getattr(self, "priority_type", None)
        if self.employer_match is not None:
            if priority_type != "income_percent":
                raise ValueError("An employer match formula applies only to income_percent payroll rules")
            if getattr(self, "employer_match_rate", 0):
                raise ValueError("Use either employer_match_rate or an employer match formula, not both")
        if self.limit_mode == "custom":
            if self.custom_annual_limit is None:
                raise ValueError("A custom contribution limit needs custom_annual_limit")
            if priority_type not in CUSTOM_LIMIT_PRIORITY_TYPES:
                raise ValueError("A custom contribution limit applies only to contribution and payroll contribution rules")
        elif self.custom_annual_limit is not None:
            raise ValueError("custom_annual_limit requires limit_mode 'custom'")
        return self


#: Rule types that can withdraw when the surplus is short. Conversions, gain
#: harvests and transfers already move money from their own source account.
WITHDRAW_IF_SHORT_PRIORITY_TYPES = (None, "contribution", "income_percent", "pre_tax_contribution",
                                    "after_tax_401k", "debt_payment")


class FundingModeFields(BaseModel):
    """How a rule is funded, shared by persisted and stateless rules.

    ``withdraw_if_short`` false funds the rule from the year's income only
    (the default). True runs it ahead of every other surplus rule and, when
    the surplus is short, draws the rest from the withdrawal order. It never
    raises a contribution limit. ``reduce_employer_contribution`` lets an
    income-funded payroll rule cut a flat employer contribution in
    proportion when pay cannot cover the employee's elected deferral.
    """

    withdraw_if_short: bool = False
    reduce_employer_contribution: bool = False

    @model_validator(mode="after")
    def validate_funding_mode(self) -> "FundingModeFields":
        priority_type = getattr(self, "priority_type", None)
        if self.withdraw_if_short and priority_type not in WITHDRAW_IF_SHORT_PRIORITY_TYPES:
            raise ValueError(
                "Withdraw if surplus is short applies only to contribution, payroll contribution and debt payment rules")
        if self.reduce_employer_contribution:
            if priority_type != "income_percent":
                raise ValueError("Reducing the employer contribution applies only to income_percent payroll rules")
            if self.withdraw_if_short:
                raise ValueError("Reducing the employer contribution applies only to rules funded with income")
        return self


class AllocationFields(BaseModel):
    """Shared contract for persisted and stateless allocation rules.

    Percentages use 0..100 and refer to the initial annual surplus. Older
    rules default to remaining, preserving their existing capped behavior.
    """
    allocation_mode: AllocationMode = "remaining"
    allocation_value: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_allocation(self) -> "AllocationFields":
        if getattr(self, "priority_type", None) not in (None, "contribution", "debt_payment") and self.allocation_mode != "remaining":
            raise ValueError("Allocation modes apply only to surplus contribution and debt payment rules")
        if self.allocation_mode != "remaining" and self.allocation_value is None:
            raise ValueError("An allocation value is required for percentage or amount")
        if self.allocation_mode == "percentage" and self.allocation_value > 100:
            raise ValueError("Allocation percentage must be between 0 and 100")
        if self.allocation_mode == "remaining" and self.allocation_value is not None:
            raise ValueError("Remaining allocation must not specify a value")
        return self

PriorityType = Literal[
    "contribution",
    "transfer",
    "roth_conversion",
    "income_percent",
    "pre_tax_contribution",
    "gain_harvest",
    # After-tax 401(k) money converted at once to the Roth 401(k) (mega backdoor).
    "after_tax_401k",
    # Surplus applied to a same-plan loan's principal.
    "debt_payment",
]
