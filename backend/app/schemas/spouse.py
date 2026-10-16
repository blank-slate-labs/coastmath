import uuid

from pydantic import BaseModel, ConfigDict, Field

from coastmath.schemas.birth_year import BirthYear


class SpouseCreate(BaseModel):
    name: str | None = None
    birth_year: BirthYear | None = None
    birth_month: int | None = Field(default=None, ge=1, le=12)
    life_expectancy: int | None = None
    income_streams: list = []
    retirement_milestone_id: uuid.UUID | None = None


class SpouseUpdate(BaseModel):
    """Household partner profile edited from the plan builder.

    ``birth_year`` and ``life_expectancy`` drive spouse-age milestones, the
    partner-death event and the estate marital deduction.
    """

    name: str | None = Field(default=None, max_length=255)
    birth_year: BirthYear | None = None
    birth_month: int | None = Field(default=None, ge=1, le=12)
    life_expectancy: int | None = Field(default=None, ge=50, le=120)


class SpouseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    name: str | None = None
    birth_year: int | None = None
    birth_month: int | None = Field(default=None, ge=1, le=12)
    life_expectancy: int | None = None
    income_streams: list = []
    retirement_milestone_id: uuid.UUID | None = None
