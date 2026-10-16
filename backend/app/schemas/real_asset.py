"""Request and response models for saved real asset records.

Shared real asset types are in ``coastmath.schemas.real_asset``.
"""
import uuid

from pydantic import ConfigDict, Field, model_validator

from coastmath.schemas.item_name import ItemName
from coastmath.schemas.real_asset import (
    AssetTaxTreatment,
    RealEstateSettings,
    real_estate_errors,
)


class RealAssetCreate(RealEstateSettings):
    tax_treatment: AssetTaxTreatment = "unspecified"
    name: ItemName
    adjusted_basis: float | None = Field(default=None, ge=0)
    current_value: float = Field(..., gt=0)
    annual_appreciation_rate: float = 0.03
    is_primary_residence: bool = False
    auto_liquidate_on_depletion: bool = False
    liquidation_target_account_id: uuid.UUID | None = None
    annual_property_tax: float = Field(default=0, ge=0)
    annual_maintenance: float = Field(default=0, ge=0)
    property_tax_rate: float | None = Field(default=None, ge=0, le=1)
    maintenance_rate: float | None = Field(default=None, ge=0, le=1)
    insurance_rate: float | None = Field(default=None, ge=0, le=1)
    sale_year: int | None = None
    sale_month: int = Field(default=1, ge=1, le=12)
    purchase_funding_account_id: uuid.UUID | None = None
    qbi_eligible: bool = False
    rental_active_participation: bool = True

    @model_validator(mode="after")
    def check_liquidation_target(self) -> "RealAssetCreate":
        if self.auto_liquidate_on_depletion and self.liquidation_target_account_id is None:
            raise ValueError(
                "liquidation_target_account_id is required when auto_liquidate_on_depletion is True"
            )
        errors = real_estate_errors(self.__dict__)
        if errors:
            raise ValueError("; ".join(errors))
        return self


class RealAssetUpdate(RealEstateSettings):
    tax_treatment: AssetTaxTreatment = "unspecified"
    name: ItemName | None = None
    adjusted_basis: float | None = Field(default=None, ge=0)
    current_value: float | None = Field(default=None, gt=0)
    annual_appreciation_rate: float | None = None
    is_primary_residence: bool | None = None
    auto_liquidate_on_depletion: bool | None = None
    liquidation_target_account_id: uuid.UUID | None = None
    annual_property_tax: float | None = Field(default=None, ge=0)
    annual_maintenance: float | None = Field(default=None, ge=0)
    property_tax_rate: float | None = Field(default=None, ge=0, le=1)
    maintenance_rate: float | None = Field(default=None, ge=0, le=1)
    insurance_rate: float | None = Field(default=None, ge=0, le=1)
    sale_year: int | None = None
    sale_month: int | None = Field(default=None, ge=1, le=12)
    purchase_funding_account_id: uuid.UUID | None = None
    qbi_eligible: bool | None = None
    rental_active_participation: bool | None = None


class RealAssetRead(RealEstateSettings):
    tax_treatment: AssetTaxTreatment = "unspecified"
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    name: str
    adjusted_basis: float | None = Field(default=None, ge=0)
    current_value: float
    annual_appreciation_rate: float
    is_primary_residence: bool
    auto_liquidate_on_depletion: bool
    liquidation_target_account_id: uuid.UUID | None = None
    annual_property_tax: float
    annual_maintenance: float
    property_tax_rate: float | None = None
    maintenance_rate: float | None = None
    insurance_rate: float | None = None
    sale_year: int | None = None
    sale_month: int = 1
    purchase_funding_account_id: uuid.UUID | None = None
    qbi_eligible: bool = False
    rental_active_participation: bool = True
