"""Calendar-year filing status elections; year-end marital status controls."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FilingStatusChange(BaseModel):
    year: int | None = Field(default=None, ge=1900, le=2300)
    milestone_id: str | None = None
    filing_status: Literal["single", "married_filing_jointly", "married_filing_separately", "head_of_household"]

    @model_validator(mode="after")
    def one_date(self):
        if (self.year is None) == (self.milestone_id is None):
            raise ValueError("Choose either a year or a milestone for a filing status change")
        return self
