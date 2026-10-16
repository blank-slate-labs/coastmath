import uuid
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# The clients' money-field range: each recorded total is $0 to $1 trillion.
MAX_TOTAL = 1e12

# A breakdown is labeled dollar totals only, so every point stays small.
Breakdown = dict[Annotated[str, StringConstraints(max_length=64)], Annotated[float, Field(strict=True, allow_inf_nan=False)]]


class ProgressPointCreate(BaseModel):
    recorded_date: date
    # Assets of up to two totals less up to one debt total.
    net_worth: float = Field(default=0, ge=-MAX_TOTAL, le=2 * MAX_TOTAL)
    assets_breakdown: Breakdown = Field(default_factory=dict, max_length=50)
    liabilities_breakdown: Breakdown = Field(default_factory=dict, max_length=50)
    auto_logged: bool = False

    @field_validator("assets_breakdown", "liabilities_breakdown")
    @classmethod
    def _totals_in_range(cls, breakdown: dict[str, float]) -> dict[str, float]:
        # A total out of range would rescale the history chart past every real record.
        for key, value in breakdown.items():
            if not 0 <= value <= MAX_TOTAL:
                raise ValueError(f"{key} must be from 0 to 1,000,000,000,000")
        return breakdown


class ProgressPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    recorded_date: date
    net_worth: float
    assets_breakdown: dict
    liabilities_breakdown: dict
    auto_logged: bool
