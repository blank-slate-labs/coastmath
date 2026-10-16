"""Request and response models for saved milestone records.

Shared milestone types are in ``coastmath.schemas.milestone``.
"""
import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from coastmath.schemas.milestone import (  # noqa: F401 - re-exported for private callers
    MilestoneConditions,
    MilestoneMetric,
    MilestoneTriggerType,
    condition_references,
)


class MilestoneCreate(BaseModel):
    name: str = Field(..., max_length=255)
    trigger_type: MilestoneTriggerType
    conditions: MilestoneConditions | None = None
    trigger_value: float | None = None
    trigger_date: date | None = None
    metric: MilestoneMetric | None = None
    expense_multiple: float | None = Field(default=None, gt=0)
    relative_to_id: uuid.UUID | None = None
    offset_years: int = 0
    sort_order: int = 0
    # Switched off: kept with its details and references but never fires.
    is_active: bool = True


class MilestoneUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    trigger_type: MilestoneTriggerType | None = None
    conditions: MilestoneConditions | None = None
    trigger_value: float | None = None
    trigger_date: date | None = None
    metric: MilestoneMetric | None = None
    expense_multiple: float | None = Field(default=None, gt=0)
    relative_to_id: uuid.UUID | None = None
    offset_years: int | None = None
    sort_order: int | None = None
    # Not nullable: only an explicit true or false changes it.
    is_active: bool = True


class MilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    name: str = Field(max_length=255)
    trigger_type: MilestoneTriggerType
    conditions: MilestoneConditions | None = None
    trigger_value: float | None = None
    trigger_date: date | None = None
    metric: MilestoneMetric | None = None
    expense_multiple: float | None = None
    relative_to_id: uuid.UUID | None = None
    offset_years: int = 0
    sort_order: int
    is_active: bool = True
