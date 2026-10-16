"""Request and response models for saved assumption curve records.

Shared assumption curve types are in ``coastmath.schemas.assumption_curve``.
"""
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from coastmath.schemas.assumption_curve import (
    CurveType,
    validate_control_points,
    validate_rate,
)


class AssumptionCurveCreate(BaseModel):
    curve_type: CurveType
    mode: Literal["fixed", "curve"] = "fixed"
    fixed_rate: float | None = None
    control_points: list[dict[str, Any]] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "AssumptionCurveCreate":
        if self.mode == "fixed" and self.fixed_rate is None:
            raise ValueError("fixed_rate required when mode is 'fixed'")
        if self.mode == "curve" and not self.control_points:
            raise ValueError("control_points required when mode is 'curve'")
        return self

    @field_validator("fixed_rate")
    @classmethod
    def validate_fixed_rate(cls, v: float | None) -> float | None:
        return None if v is None else validate_rate(v)

    @field_validator("control_points")
    @classmethod
    def validate_control_points(
        cls, v: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return validate_control_points(v)


class AssumptionCurveUpdate(BaseModel):
    curve_type: CurveType | None = None
    mode: Literal["fixed", "curve"] | None = None
    fixed_rate: float | None = None
    control_points: list[dict[str, Any]] | None = Field(default=None, max_length=200)

    @field_validator("fixed_rate")
    @classmethod
    def validate_fixed_rate(cls, v: float | None) -> float | None:
        return None if v is None else validate_rate(v)

    @field_validator("control_points")
    @classmethod
    def validate_control_points(
        cls, v: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        return None if v is None else validate_control_points(v)


class AssumptionCurveRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    curve_type: CurveType
    mode: Literal["fixed", "curve"]
    fixed_rate: float | None = None
    control_points: list[dict[str, Any]] = []
