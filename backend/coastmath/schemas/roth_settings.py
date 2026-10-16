"""Opening Roth tax history, separate from taxable-account cost basis."""
from pydantic import BaseModel, Field, model_validator


class RothConversionBasis(BaseModel):
    year: int = Field(ge=1998, le=2200)
    taxable_basis: float = Field(default=0, ge=0, allow_inf_nan=False)
    nontaxable_basis: float = Field(default=0, ge=0, allow_inf_nan=False)


class RothSettings(BaseModel):
    contribution_basis: float = Field(default=0, ge=0, allow_inf_nan=False)
    first_contribution_year: int | None = Field(default=None, ge=1998, le=2200)
    conversions: list[RothConversionBasis] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def check_first_year(self):
        if self.first_contribution_year is not None and any(c.year < self.first_contribution_year for c in self.conversions):
            raise ValueError("First Roth contribution year cannot be later than a recorded conversion year.")
        return self
