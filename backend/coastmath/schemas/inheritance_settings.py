"""Beneficiary elections and decedent history, shared by both request paths."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InheritanceSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    distribution_method: Literal['automatic','life_expectancy','ten_year','spousal_rollover'] = 'automatic'
    decedent_birth_year: int | None = Field(default=None,ge=1850,le=2200)
    decedent_died_after_rbd: bool | None = None
    beneficiary_is_minor_child: bool = False
    year_of_death_rmd_remaining: float = Field(default=0,ge=0)
