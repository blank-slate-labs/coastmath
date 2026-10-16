"""Wire models for /api/ledger/spending-feeds: a plan's spending from any provider's accounts."""
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_FEED_MONTHS = 12


class LedgerFeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    # Required when the plan already has expenses the feed could repeat.
    acknowledge_existing_expenses: bool = False
    basis: Literal["trailing", "months"] = "trailing"
    months: list[str] = Field(default_factory=list, max_length=MAX_FEED_MONTHS)

    @field_validator("months")
    @classmethod
    def _months(cls, value: list[str]) -> list[str]:
        if any(not MONTH_PATTERN.fullmatch(key) for key in value):
            raise ValueError("months are YYYY-MM")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _basis_months(self) -> "LedgerFeedRequest":
        if self.basis == "months" and not self.months:
            raise ValueError("choose at least one month for the months basis")
        if self.basis == "trailing" and self.months:
            raise ValueError("months apply only to the months basis")
        return self


class LedgerFeedRead(BaseModel):
    plan_id: uuid.UUID
    active: bool
    source_ids: list[uuid.UUID] = []
    basis: Literal["trailing", "months"] = "trailing"
    basis_months: list[str] = []
    essential_expense_id: uuid.UUID | None = None
    discretionary_expense_id: uuid.UUID | None = None
    annual_essential: float | None = None
    annual_discretionary: float | None = None
    months_used: int = 0
    error: str | None = None
    applied_at: datetime | None = None
