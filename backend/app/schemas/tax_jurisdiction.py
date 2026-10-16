import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

JurisdictionLevel = Literal["federal", "state", "local"]


class TaxBracket(BaseModel):
    min: float = Field(ge=0)
    max: float | None = None
    rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_width(self) -> "TaxBracket":
        if self.max is not None and self.max <= self.min:
            raise ValueError("max must be greater than min")
        return self


def _validate_brackets_no_overlap(brackets: list[TaxBracket] | None) -> list[TaxBracket] | None:
    if not brackets:
        return brackets
    sorted_brackets = sorted(brackets, key=lambda b: b.min)
    for i in range(len(sorted_brackets) - 1):
        current = sorted_brackets[i]
        nxt = sorted_brackets[i + 1]
        if current.max is None:
            raise ValueError(
                f"Bracket starting at {current.min} has no upper limit but is not the last bracket"
            )
        if current.max > nxt.min:
            raise ValueError(
                f"Brackets overlap: [{current.min}, {current.max}] and [{nxt.min}, {nxt.max}]"
            )
    return brackets


class TaxJurisdictionCreate(BaseModel):
    level: JurisdictionLevel
    jurisdiction_code: str | None = None
    custom_brackets: list[TaxBracket] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_jurisdiction_code_for_state(self) -> "TaxJurisdictionCreate":
        if self.level == "state" and self.jurisdiction_code is not None:
            code = self.jurisdiction_code.upper()
            if code not in US_STATE_CODES:
                raise ValueError(
                    f"Invalid state code '{self.jurisdiction_code}': must be a 2-letter US state code"
                )
            self.jurisdiction_code = code
        return self

    @field_validator("custom_brackets")
    @classmethod
    def validate_brackets(cls, v: list[TaxBracket] | None) -> list[TaxBracket] | None:
        return _validate_brackets_no_overlap(v)


class TaxJurisdictionUpdate(BaseModel):
    level: JurisdictionLevel | None = None
    jurisdiction_code: str | None = None
    custom_brackets: list[TaxBracket] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_jurisdiction_code_for_state(self) -> "TaxJurisdictionUpdate":
        if self.level == "state" and self.jurisdiction_code is not None:
            code = self.jurisdiction_code.upper()
            if code not in US_STATE_CODES:
                raise ValueError(
                    f"Invalid state code '{self.jurisdiction_code}': must be a 2-letter US state code"
                )
            self.jurisdiction_code = code
        return self

    @field_validator("custom_brackets")
    @classmethod
    def validate_brackets(cls, v: list[TaxBracket] | None) -> list[TaxBracket] | None:
        return _validate_brackets_no_overlap(v)


class TaxJurisdictionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    level: JurisdictionLevel
    jurisdiction_code: str | None = None
    custom_brackets: list[TaxBracket] | None = None
