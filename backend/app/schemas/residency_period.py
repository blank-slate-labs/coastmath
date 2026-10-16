"""Request and response models for saved residency period records.

Shared residency period types are in ``coastmath.schemas.residency_period``.
"""
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from coastmath.schemas.intl_settings import (
    normalize_region,
    normalize_supported_country,
)
from coastmath.schemas.local_tax import (
    LocalTaxSelection,
    LocalTaxSelectionRead,
    check_local_tax_state,
)
from coastmath.schemas.residency_period import (  # noqa: F401 - re-exported for private callers
    ResidencyPeriodRequest,
    normalize_state_code,
    settle_abroad,
)


class ResidencyPeriodCreate(BaseModel):
    # Required in the US; ignored (cleared) for a period in another country.
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    # Null: the plan's country (and region). Never a US state.
    country: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=8)
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
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
    def _local_tax_in_state(self) -> "ResidencyPeriodCreate":
        settle_abroad(self)
        if self.state_code is not None:
            check_local_tax_state(self.local_tax, self.state_code)
        return self

    @model_validator(mode="after")
    def _xor_start_end(self) -> "ResidencyPeriodCreate":
        if self.start_milestone_id is not None and self.start_year is not None:
            raise ValueError(
                "set only one of start_milestone_id or start_year, not both"
            )
        if self.end_milestone_id is not None and self.end_year is not None:
            raise ValueError(
                "set only one of end_milestone_id or end_year, not both"
            )
        return self


class ResidencyPeriodUpdate(BaseModel):
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=8)
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    start_year: int | None = Field(default=None, ge=1900, le=2200)
    end_year: int | None = Field(default=None, ge=1900, le=2200)
    rank: int | None = None
    local_tax: LocalTaxSelection | None = None

    _normalize_state = field_validator("state_code")(
        classmethod(lambda cls, v: normalize_state_code(v))
    )
    _normalize_country = field_validator("country")(classmethod(lambda cls, v: normalize_supported_country(v, "country")))
    _normalize_region = field_validator("region")(classmethod(lambda cls, v: normalize_region(v)))

    @model_validator(mode="after")
    def _local_tax_in_state(self) -> "ResidencyPeriodUpdate":
        if self.state_code is not None:
            check_local_tax_state(self.local_tax, self.state_code)
        return self

    @model_validator(mode="after")
    def _xor_start_end(self) -> "ResidencyPeriodUpdate":
        if self.start_milestone_id is not None and self.start_year is not None:
            raise ValueError(
                "set only one of start_milestone_id or start_year, not both"
            )
        if self.end_milestone_id is not None and self.end_year is not None:
            raise ValueError(
                "set only one of end_milestone_id or end_year, not both"
            )
        return self


class ResidencyPeriodRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    # Omitted while unset, so existing reads keep their shape.
    country: str | None = Field(default=None, exclude_if=lambda value: value is None)
    region: str | None = Field(default=None, exclude_if=lambda value: value is None)
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    start_year: int | None = None
    end_year: int | None = None
    rank: int
    local_tax: LocalTaxSelectionRead | None = None
