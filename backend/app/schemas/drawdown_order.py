import uuid

from pydantic import BaseModel, ConfigDict, Field


class DrawdownOrderCreate(BaseModel):
    rank: int
    source_account_id: uuid.UUID | None = None


class DrawdownOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    rank: int
    source_account_id: uuid.UUID | None = None


class DrawdownOrderBulkUpdate(BaseModel):
    items: list[DrawdownOrderCreate] = Field(max_length=200)
