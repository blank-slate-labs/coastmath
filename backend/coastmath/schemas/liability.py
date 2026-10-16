import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

PaymentType = Literal["fixed", "percent_of_balance", "custom"]
#: How interest accrues (coastmath.engine.amortization.INTEREST_METHODS): monthly
#: amortization, simple interest on principal only, or daily compounding on
#: actual days (actual/365).
InterestMethod = Literal["monthly", "simple", "daily"]

#: IRC 108(a)(1) grounds a taxpayer may declare. The plan records the user's
#: declaration only; whether it applies is for the taxpayer and Form 982.
ExclusionBasis = Literal[
    "bankruptcy",
    "insolvency",
    "qualified_farm_debt",
    "qualified_real_property_business_debt",
    "qualified_principal_residence",
    "other_declared",
]


class LiabilityForgiveness(BaseModel):
    """One-time cancellation of the loan, fired by a calendar year or a milestone.

    Forgiven debt is cancellation-of-debt income (IRC 61(a)(11)) unless the plan
    declares an excluded amount under IRC 108. The exclusion is never inferred.
    """

    model_config = ConfigDict(extra="forbid")

    year: int | None = Field(default=None, ge=1900, le=2200)
    milestone_id: uuid.UUID | None = None
    #: Amount cancelled; omitted cancels the whole remaining balance.
    amount: float | None = Field(default=None, gt=0)
    tax_treatment: Literal["taxable", "declared_exclusion"] = "taxable"
    #: Declared excluded part of the cancelled amount; omitted declares all of it.
    excluded_amount: float | None = Field(default=None, ge=0)
    exclusion_basis: ExclusionBasis | None = None

    @model_validator(mode="after")
    def check_forgiveness(self) -> "LiabilityForgiveness":
        if (self.year is None) == (self.milestone_id is None):
            raise ValueError("Choose either a year or a milestone for the forgiveness")
        if self.tax_treatment == "taxable":
            if self.excluded_amount is not None or self.exclusion_basis is not None:
                raise ValueError("An excluded amount and basis require the declared exclusion treatment")
        else:
            if self.exclusion_basis is None:
                raise ValueError("A declared exclusion needs its IRC 108 basis")
            if (self.amount is not None and self.excluded_amount is not None
                    and self.excluded_amount > self.amount):
                raise ValueError("The excluded amount cannot exceed the forgiven amount")
        return self

    @field_serializer("milestone_id")
    def _milestone_id_as_text(self, value: uuid.UUID | None) -> str | None:
        return None if value is None else str(value)


class LiabilityRecurrenceFields(BaseModel):
    """Take the loan again every ``recurrence_years`` years on its original terms.

    Each occurrence starts in January, ``recurrence_years`` apart from the plan
    start, with the entered balance, payment and extra payment in the plan's
    start-year dollars (grown with inflation to that year). Occurrences stop
    after ``recurrence_end_year`` or once ``recurrence_end_milestone_id`` is
    reached. The end fields need a recurrence.
    """

    recurrence_years: int | None = Field(default=None, ge=1, le=100)
    recurrence_end_year: int | None = Field(default=None, ge=1900, le=2200)
    recurrence_end_milestone_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def check_recurrence(self):
        if self.recurrence_years is None and (
                self.recurrence_end_year is not None or self.recurrence_end_milestone_id is not None):
            raise ValueError("A repeat end needs a repeat interval (recurrence_years)")
        return self
