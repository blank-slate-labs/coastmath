import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CharityType = Literal["qcd", "daf", "direct"]
#: How a DAF or direct gift is paid: cash, or appreciated shares from the
#: taxable brokerage account in ``source_account_id``.
CharityFunding = Literal["cash", "appreciated_shares"]


class CharityEntityCreate(BaseModel):
    name: str = Field(..., max_length=255)
    entity_type: CharityType
    annual_amount: float
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    source_account_id: uuid.UUID | None = None
    funding: CharityFunding = "cash"


class CharityEntityUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    entity_type: CharityType | None = None
    annual_amount: float | None = None
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    source_account_id: uuid.UUID | None = None
    funding: CharityFunding | None = None


class CharityEntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    name: str = Field(max_length=255)
    entity_type: CharityType
    annual_amount: float
    start_milestone_id: uuid.UUID | None = None
    end_milestone_id: uuid.UUID | None = None
    source_account_id: uuid.UUID | None = None
    funding: CharityFunding = "cash"
