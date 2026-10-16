"""Explicit medical budgets; no proprietary estimator or Medicaid eligibility."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LongTermCareBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    monthly_cost: float = Field(ge=0)
    duration_months: int = Field(ge=1, le=600)
    start_year: int | None = Field(default=None, ge=1900, le=2300)
    start_month: int = Field(default=1, ge=1, le=12)
    months_before_longevity: int | None = Field(default=None, ge=1, le=600)
    covered_fraction: float = Field(default=0, ge=0, le=1)
    inflation_rate: float | None = Field(default=None, ge=-0.5, le=0.5)
    amount_reference_year: int | None = Field(default=None, ge=1900, le=2300)

    @model_validator(mode="after")
    def one_start(self):
        if (self.start_year is None) == (self.months_before_longevity is None):
            raise ValueError("Specify a start year or months before longevity, exclusively")
        if self.months_before_longevity is not None and self.start_month != 1:
            raise ValueError("Start month applies only to a calendar start year")
        return self


class PersonHealthcareSettings(BaseModel):
    """An override for one person; unlisted people retain shared settings.

    Itemized replaces this person's medical premiums and out-of-pocket costs.
    Coverage calculates premiums, with an optional explicit out-of-pocket
    budget. LTC is a separate net budget; covered_fraction is an assumption,
    never an assertion of insurance or Medicaid eligibility.
    """
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    owner: Literal["self", "spouse"]
    mode: Literal["off", "itemized", "coverage"]
    itemized_annual_amount: float | None = Field(default=None, ge=0)
    itemized_start_age: int = Field(default=0, ge=0, le=120)
    itemized_end_age: int | None = Field(default=None, ge=0, le=130)
    medical_inflation_rate: float | None = Field(default=None, ge=-0.5, le=0.5)
    aca_enabled: bool = True
    medicare_enabled: bool = True
    medicare_start_age: int = Field(default=65, ge=65, le=120)
    medicare_part_b: bool = True
    medicare_part_d: bool = True
    medicare_apply_irmaa: bool = True
    medicare_part_a_premium_monthly: float = Field(default=0, ge=0)
    # Medicare-covered quarters (own or a qualifying spouse's) for the
    # statutory Part A premium: 40 or more pay none, 30-39 the reduced
    # premium, fewer than 30 the full premium. None adds no Part A premium.
    medicare_part_a_quarters: int | None = Field(default=None, ge=0, le=200,
                                                 exclude_if=lambda value: value is None)
    medicare_part_d_plan_premium_monthly: float = Field(default=0, ge=0)
    medicare_supplement_premium_monthly: float = Field(default=0, ge=0)
    out_of_pocket_annual: float | None = Field(default=None, ge=0)
    long_term_care: LongTermCareBudget | None = None

    @model_validator(mode="after")
    def coherent_mode(self):
        if self.mode == "itemized" and self.itemized_annual_amount is None:
            raise ValueError("Itemized medical costs require an explicit amount, including zero")
        if self.mode != "itemized" and self.itemized_annual_amount is not None:
            raise ValueError("Itemized amount applies only to itemized mode")
        if self.itemized_end_age is not None and self.itemized_end_age < self.itemized_start_age:
            raise ValueError("Itemized end age must not precede start age")
        if self.mode != "coverage" and self.out_of_pocket_annual is not None:
            raise ValueError("Out-of-pocket budget applies only to coverage mode")
        return self
