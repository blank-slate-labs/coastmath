from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

SEPPMethod = Literal["fixed_amortization", "fixed_annuitization", "rmd_method"]


class SEPPSettings(BaseModel):
    enabled: bool = False
    source_account_id: UUID | None = None
    method: SEPPMethod = "fixed_amortization"
    start_age: float
    interest_rate: float = 0.05
    #: Custom yearly payment in dollars. Only the amount an IRS-approved method
    #: yields keeps the 72(t) exemption; any other amount is an ordinary early
    #: withdrawal with the 10% additional tax.
    annual_amount: float | None = Field(default=None, gt=0, le=1e9, exclude_if=lambda v: v is None)

    @field_validator("start_age")
    @classmethod
    def start_age_must_be_under_59_5(cls, v: float) -> float:
        if v >= 59.5:
            raise ValueError("start_age must be less than 59.5")
        return v

    @field_validator("interest_rate")
    @classmethod
    def interest_rate_in_range(cls, v: float) -> float:
        if v < 0 or v > 0.15:
            raise ValueError("interest_rate must be between 0 and 0.15")
        return v

    @model_validator(mode="after")
    def source_account_required_when_enabled(self) -> "SEPPSettings":
        if self.enabled and self.source_account_id is None:
            raise ValueError("source_account_id is required when enabled is True")
        if self.enabled and self.method == "fixed_annuitization":
            # The bundled mortality table is an approximation that overstates
            # the IRS annuity payment materially (Notice 2022-6 example), so
            # the method cannot be enabled until the Treas. Reg. 1.401(a)(9)-9(e)
            # table is transcribed. Fixed amortization yields nearly identical
            # payments in the IRS example.
            raise ValueError(
                "fixed_annuitization is not supported for projections; use fixed_amortization or rmd_method"
            )
        return self
