"""Catalog of country tax regimes a plan or residency period can use.

US plans keep the existing federal, state and local tax path, so the US is
not listed. ``XX`` ("Other") is a regime the user describes in the plan's
``intl_settings.custom_regime``.
"""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.models.user import User
from coastmath.engine import intl_bridge

router = APIRouter(prefix="/tax-regimes", tags=["tax regimes"])


class RegionRead(BaseModel):
    code: str
    name: str


class AccountKindRead(BaseModel):
    id: str  # "<CC>:<kind_id>", the value of accounts.intl_account_kind
    label: str
    category: str
    # Key rules in plain words (limits, tax treatment, access age).
    rules: list[str] = []
    # Unused contribution room carries forward; the plan can give the room
    # left at its start (intl_settings.starting_room).
    carries_room: bool = False
    # Room is a percent of the prior year's earned income (the plan can give
    # that income for its first year: intl_settings.prior_year_earned_income).
    uses_prior_year_income: bool = False


class BenefitRuleRead(BaseModel):
    id: str
    label: str
    params_schema: dict[str, Any]


class TaxRegimeRead(BaseModel):
    code: str
    name: str
    # Null for "XX" (Other): a custom regime uses the plan's currency.
    currency: str | None
    filing_unit: str | None
    regions: list[RegionRead]
    # The region a new plan or move starts in; null means the first region.
    default_region: str | None = None
    # True for "XX" (Other), the regime the user describes.
    custom: bool = False
    account_kinds: list[AccountKindRead]
    benefit_rules: list[BenefitRuleRead]
    spec_years: list[int]
    approximations: list[str]


class TaxRegimeCatalogRead(BaseModel):
    countries: list[TaxRegimeRead]


@router.get("", response_model=TaxRegimeCatalogRead)
def list_tax_regimes(current_user: User = Depends(get_current_user)) -> TaxRegimeCatalogRead:
    return TaxRegimeCatalogRead(countries=[TaxRegimeRead(**entry) for entry in intl_bridge.catalog()])
