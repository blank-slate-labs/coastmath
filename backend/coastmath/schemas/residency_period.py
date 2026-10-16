
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from coastmath.schemas.intl_settings import (
    normalize_region,
    normalize_supported_country,
)
from coastmath.schemas.local_tax import LocalTaxSelection, check_local_tax_state


def normalize_state_code(v: str | None) -> str | None:
    """Trim and upper-case a two-letter US state code; None passes through."""
    if v is None:
        return v
    v = v.strip().upper()
    if len(v) != 2:
        raise ValueError("state_code must be exactly 2 characters")
    return v


def settle_abroad(period) -> None:
    """Clear the state and local tax of a period outside the US; require a state in the US.

    A period without a country inherits the plan's, which only the plan
    knows; the plan-level check requires a state when that country is the US.
    Fields are assigned only when they change, so exclude_unset dumps keep
    their shape.
    """
    if period.country is not None and period.country != "US":
        if period.state_code is not None:
            period.state_code = None
        if period.local_tax is not None:
            period.local_tax = None
    elif period.country == "US" and period.state_code is None:
        raise ValueError("A residency period in the US needs a state")


class ResidencyPeriodRequest(BaseModel):
    """Stateless-mode request variant. Milestone IDs are strings
    (matching MilestoneRequest / IncomeRequest pattern)."""

    model_config = ConfigDict(extra="ignore")

    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    # Omitted while unset, so existing request dumps are unchanged.
    country: str | None = Field(default=None, min_length=2, max_length=2, exclude_if=lambda value: value is None)
    region: str | None = Field(default=None, max_length=8, exclude_if=lambda value: value is None)
    start_milestone_id: str | None = None
    end_milestone_id: str | None = None
    start_year: int | None = Field(default=None, ge=1900, le=2200)
    end_year: int | None = Field(default=None, ge=1900, le=2200)
    rank: int = 0
    local_tax: LocalTaxSelection | None = None

    _normalize_state = field_validator("state_code")(
        classmethod(lambda cls, v: normalize_state_code(v))
    )
    _normalize_country = field_validator("country")(classmethod(lambda cls, v: normalize_supported_country(v, "country")))
    _normalize_region = field_validator("region")(classmethod(lambda cls, v: normalize_region(v)))

    @model_validator(mode="after")
    def _local_tax_in_state(self) -> "ResidencyPeriodRequest":
        settle_abroad(self)
        if self.state_code is not None:
            check_local_tax_state(self.local_tax, self.state_code)
        return self

    @model_validator(mode="after")
    def _xor_start_end(self) -> "ResidencyPeriodRequest":
        if self.start_milestone_id is not None and self.start_year is not None:
            raise ValueError(
                "set only one of start_milestone_id or start_year, not both"
            )
        if self.end_milestone_id is not None and self.end_year is not None:
            raise ValueError(
                "set only one of end_milestone_id or end_year, not both"
            )
        return self
