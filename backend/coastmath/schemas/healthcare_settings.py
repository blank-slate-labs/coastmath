from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from coastmath.schemas.person_healthcare import PersonHealthcareSettings

StateGroup = Literal["contiguous", "alaska", "hawaii"]


class HealthcareSettings(BaseModel):
    """Health coverage assumptions stored as JSONB (see engine/healthcare.py).

    Premiums are annual (ACA) or monthly (Medicare) in today's dollars; rates
    are decimals. Milestone ids are stored as strings.
    """

    enabled: bool = False
    medical_inflation_rate: float | None = Field(default=None, ge=-0.5, le=0.5)
    aca_enabled: bool = False
    aca_start_milestone_id: UUID | None = None
    aca_end_milestone_id: UUID | None = None
    aca_benchmark_premium_annual: float = Field(default=0, ge=0)
    aca_plan_premium_annual: float = Field(default=0, ge=0)
    aca_advance_credit_fraction: float = Field(
        default=1.0, ge=0, le=1,
        description="Fraction of the estimated ACA credit received in advance during coverage.",
    )
    aca_cover_spouse: bool = True
    aca_dependents: int = Field(default=0, ge=0, le=20)
    aca_apply_age_curve: bool = True
    aca_state_group: StateGroup = "contiguous"
    medicare_enabled: bool = True
    medicare_part_b: bool = True
    medicare_part_d: bool = True
    medicare_part_d_plan_premium_monthly: float = Field(default=0, ge=0)
    medicare_supplement_premium_monthly: float = Field(default=0, ge=0)
    medicare_apply_irmaa: bool = True
    magi_prior_year: float | None = Field(default=None, ge=0)
    magi_two_years_prior: float | None = Field(default=None, ge=0)
    magi_prior_year_filing_status: Literal["single", "head_of_household", "married_filing_jointly", "married_filing_separately"] | None = None
    magi_two_years_prior_filing_status: Literal["single", "head_of_household", "married_filing_jointly", "married_filing_separately"] | None = None
    persons: list[PersonHealthcareSettings] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def aca_requires_premiums(self) -> "HealthcareSettings":
        if len({person.owner for person in self.persons}) != len(self.persons):
            raise ValueError("Health coverage overrides must have unique owners")
        if self.enabled and self.aca_enabled:
            if self.aca_plan_premium_annual <= 0 or self.aca_benchmark_premium_annual <= 0:
                raise ValueError("ACA coverage needs both the benchmark (second-lowest-cost silver) and chosen plan annual premiums")
        return self
