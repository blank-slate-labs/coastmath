"""Wire models for a scenario's inheritance from its Main plan (app.scenarios)."""
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class InheritedField(BaseModel):
    """An overridden field: the scenario's value and Main's, in the scenario's IDs."""
    field: str
    value: Any = None
    parent_value: Any = None


class InheritanceItem(BaseModel):
    kind: str
    row_id: uuid.UUID | None = None
    parent_row_id: uuid.UUID | None = None
    name: str
    state: Literal["inherited", "changed", "removed", "scenario_only"]
    fields: list[InheritedField] = []


class SkippedItem(BaseModel):
    kind: str
    parent_row_id: uuid.UUID | None = None
    name: str
    field: str | None = None
    reason: str


class InheritanceRead(BaseModel):
    plan_id: uuid.UUID
    parent_plan_id: uuid.UUID | None = None
    parent_name: str | None = None
    status: Literal["ok", "needs_review"] = "ok"
    synced_at: datetime | None = None
    plan_fields: list[InheritedField] = []
    items: list[InheritanceItem] = []
    skipped: list[SkippedItem] = []


class InheritanceReset(BaseModel):
    """Make values follow Main again: one row (``row_id``), the plan (``kind: plan``) or a whole list."""
    kind: str = Field(min_length=1, max_length=20)
    row_id: uuid.UUID | None = None
    # Omitted or null: every overridden field.
    fields: list[str] | None = Field(default=None, max_length=100)
    # Required for ``priorities``, checked like PUT /plans/{id}/priorities.
    expected_revision: int | None = None


class InheritanceRestore(BaseModel):
    kind: str = Field(min_length=1, max_length=20)
    parent_row_id: uuid.UUID
