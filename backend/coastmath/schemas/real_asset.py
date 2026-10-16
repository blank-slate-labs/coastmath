from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetTaxTreatment = Literal["unspecified", "personal_use", "investment", "rental"]
RentalPropertyClass = Literal["residential", "nonresidential"]


class RentalUseStep(BaseModel):
    """From ``year`` on, ``rate`` (a decimal) of the property is rented out."""

    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=1900, le=2200)
    rate: float = Field(ge=0, le=1)


class RealEstateSettings(BaseModel):
    """Purchase, selling-cost, rental and home-sale fields of a real asset.

    All are optional; blank values keep the asset's earlier behavior. Dollar
    amounts are plan-start (today's) dollars, rates are decimals (0.06 for
    6%) except ``purchase_loan_rate``, which is an annual percent like a
    liability's ``interest_rate``. ``rental_expense_rate`` (a share of
    collected rent) replaces ``rental_expenses`` when set.

    ``rental_use_rate`` makes a rental mixed use: the share of the property
    rented out (blank = fully rented). Rent and fixed rental expenses are
    entered as if the whole property were rented and are scaled by the share,
    as are depreciation, carrying costs and loan interest; the personal share
    keeps its itemized property tax and, for a main home, mortgage interest.
    ``rental_use_schedule`` steps change the share from a given year.
    """

    purchase_year: int | None = Field(default=None, ge=1900, le=2200)
    purchase_month: int | None = Field(default=None, ge=1, le=12)
    purchase_price: float | None = Field(default=None, gt=0)
    down_payment_amount: float | None = Field(default=None, ge=0)
    down_payment_rate: float | None = Field(default=None, ge=0, le=1)
    closing_costs: float | None = Field(default=None, ge=0)
    purchase_loan_rate: float | None = Field(default=None, ge=0, le=100)
    purchase_loan_term_months: int | None = Field(default=None, ge=1, le=600)
    selling_cost_rate: float | None = Field(default=None, ge=0, le=1)
    rental_income: float | None = Field(default=None, ge=0)
    rental_income_growth_rate: float | None = Field(default=None, ge=-1, le=1)
    rental_expenses: float | None = Field(default=None, ge=0)
    rental_expense_rate: float | None = Field(default=None, ge=0, le=1)
    vacancy_rate: float | None = Field(default=None, ge=0, le=1)
    rental_property_class: RentalPropertyClass | None = None
    land_value_rate: float | None = Field(default=None, ge=0, le=1)
    building_basis: float | None = Field(default=None, ge=0)
    prior_depreciation: float | None = Field(default=None, ge=0)
    suspended_passive_loss: float | None = Field(default=None, ge=0)
    owned_since_year: int | None = Field(default=None, ge=1900, le=2200)
    owned_since_month: int | None = Field(default=None, ge=1, le=12)
    primary_residence_since_year: int | None = Field(default=None, ge=1900, le=2200)
    primary_residence_since_month: int | None = Field(default=None, ge=1, le=12)
    rental_use_rate: float | None = Field(default=None, ge=0, le=1)
    rental_use_schedule: list[RentalUseStep] | None = Field(default=None, max_length=100)

    @field_validator("rental_use_schedule")
    @classmethod
    def _schedule_years(cls, steps: list[RentalUseStep] | None) -> list[RentalUseStep] | None:
        if steps is None:
            return None
        years = [step.year for step in steps]
        if len(set(years)) != len(years):
            raise ValueError("rental_use_schedule years must be unique")
        return sorted(steps, key=lambda step: step.year)


def _mixed_use(values: Mapping[str, Any]) -> bool:
    """Whether the values configure any personal-use share of a rental."""
    rates = [values.get("rental_use_rate")]
    for step in values.get("rental_use_schedule") or []:
        rates.append(step["rate"] if isinstance(step, dict) else step.rate)
    return any(rate is not None and float(rate) < 1 for rate in rates)


def real_estate_errors(values: Mapping[str, Any]) -> list[str]:
    """Cross-field checks shared by create, update and stateless requests."""
    get = values.get
    errors = []
    if get("purchase_year") is not None:
        if get("purchase_price") is None:
            errors.append("purchase_price is required with purchase_year")
        if get("sale_year") is not None and (
            (get("sale_year"), get("sale_month") or 1) <= (get("purchase_year"), get("purchase_month") or 1)
        ):
            errors.append("the planned sale must come after the planned purchase")
    if get("down_payment_amount") is not None and get("down_payment_rate") is not None:
        errors.append("enter down_payment_amount or down_payment_rate, not both")
    if (get("down_payment_amount") is not None and get("purchase_price") is not None
            and get("down_payment_amount") > get("purchase_price")):
        errors.append("down_payment_amount cannot exceed purchase_price")
    if (get("purchase_loan_rate") is None) != (get("purchase_loan_term_months") is None):
        errors.append("a purchase loan needs both purchase_loan_rate and purchase_loan_term_months")
    if get("tax_treatment") == "rental" and get("is_primary_residence") and not _mixed_use(values):
        errors.append("a primary residence can use rental tax treatment only with a rental-use share below 100%")
    for prefix in ("owned_since", "primary_residence_since"):
        if get(f"{prefix}_month") is not None and get(f"{prefix}_year") is None:
            errors.append(f"{prefix}_month requires {prefix}_year")
    return errors
