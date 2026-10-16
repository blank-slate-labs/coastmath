"""Response models for /api/ledger/suggestions: suggested categories for imported transactions."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SuggestionRunRead(BaseModel):
    status: Literal["suggested", "nothing_pending", "failed"]
    suggested: int
    sent: int
    message: str | None
    finished_at: datetime | None


class SuggestionStatusRead(BaseModel):
    """``pending``: posted rows only a suggestion could categorize; null when not offered."""
    offered: bool
    running: bool
    pending: int | None
    last_run: SuggestionRunRead | None
