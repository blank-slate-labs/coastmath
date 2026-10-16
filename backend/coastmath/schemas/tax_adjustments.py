"""User tax adjustments and scheduled tax-setting changes (tax_settings JSONB).

``adjustments`` are explicit deductions, credits and percent surcharges; see
``coastmath.engine.tax_adjustments``. ``scheduled_changes`` replace a typed
whitelist of tax settings from a calendar year or a plan milestone; see
``coastmath.engine.tax_schedule``. Both are omitted when empty, so stored settings
without them are unchanged.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from coastmath.schemas.expense import omit_none
from coastmath.schemas.state_brackets import FederalBrackets, StateBrackets

MAX_TAX_ADJUSTMENTS = 50
MAX_SCHEDULED_TAX_CHANGES = 50
# Far above any household figure; bounds stored JSON and engine arithmetic.
MAX_ADJUSTMENT_AMOUNT = 1_000_000_000
# Owner RMD start ages a plan may assume (statute today: 72, 73 or 75).
MIN_RMD_START_AGE = 70
MAX_RMD_START_AGE = 80

AdjustmentKind = Literal["deduction", "credit", "surcharge"]
AdjustmentScope = Literal["federal", "state", "both"]
DeductionType = Literal["above_the_line", "itemized"]
# ordinary_taxable_income: taxable income taxed at ordinary rates;
# taxable_income: that plus taxable capital gains and qualified dividends;
# capital_gains: the taxable capital gains and qualified dividends alone;
# income_tax: the income tax itself, before user credits.
SurchargeBase = Literal["ordinary_taxable_income", "taxable_income", "capital_gains", "income_tax"]
AmountBasis = Literal["today", "nominal"]
Frequency = Literal["once", "annual", "every_n_years"]


class TaxAdjustment(BaseModel):
    """One deduction, credit or surcharge over an explicit window of tax years."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=120)
    kind: AdjustmentKind
    # Deductions may apply to both returns; a credit or surcharge belongs to one.
    scope: AdjustmentScope
    deduction_type: DeductionType | None = Field(default=None, exclude_if=omit_none)
    refundable: bool = Field(default=False, exclude_if=lambda value: not value)
    # Deductions and credits: dollars per applicable tax year.
    amount: float | None = Field(default=None, ge=0, le=MAX_ADJUSTMENT_AMOUNT, exclude_if=omit_none)
    # Surcharges: decimal rate on ``base`` (0.01 = 1%), optionally capped.
    rate: float | None = Field(default=None, gt=0, le=1, exclude_if=omit_none)
    base: SurchargeBase | None = Field(default=None, exclude_if=omit_none)
    max_amount: float | None = Field(default=None, ge=0, le=MAX_ADJUSTMENT_AMOUNT, exclude_if=omit_none)
    # today: plan-start dollars indexed with plan inflation; nominal: as entered.
    amount_basis: AmountBasis
    # household applies on every return; a person's item stops after the
    # return for the year of their death.
    owner: Literal["self", "spouse", "household"] = "household"
    start_year: int | None = Field(default=None, ge=1900, le=2300, exclude_if=omit_none)
    start_milestone_id: str | None = Field(default=None, max_length=64, exclude_if=omit_none)
    # Inclusive. Open-ended when neither is set or the end milestone never fires.
    end_year: int | None = Field(default=None, ge=1900, le=2300, exclude_if=omit_none)
    end_milestone_id: str | None = Field(default=None, max_length=64, exclude_if=omit_none)
    frequency: Frequency
    interval_years: int | None = Field(default=None, ge=2, le=50, exclude_if=omit_none)

    @model_validator(mode="after")
    def _consistent(self) -> "TaxAdjustment":
        if self.kind == "deduction":
            if self.deduction_type is None:
                raise ValueError("A deduction needs deduction_type: above_the_line or itemized.")
        elif self.deduction_type is not None:
            raise ValueError("Only deductions have a deduction_type.")
        if self.kind in ("credit", "surcharge") and self.scope == "both":
            raise ValueError("A credit or surcharge applies to the federal or the state return, not both.")
        if self.refundable and self.kind != "credit":
            raise ValueError("Only credits can be refundable.")
        if self.kind == "surcharge":
            if self.rate is None or self.base is None:
                raise ValueError("A surcharge needs a rate and a base.")
            if self.amount is not None:
                raise ValueError("A surcharge uses rate, not amount.")
        else:
            if self.amount is None:
                raise ValueError("A deduction or credit needs an amount.")
            if self.rate is not None or self.base is not None or self.max_amount is not None:
                raise ValueError("Only surcharges have a rate, base or max_amount.")
        if self.start_year is not None and self.start_milestone_id is not None:
            raise ValueError("Choose a start year or a start milestone, not both.")
        if self.end_year is not None and self.end_milestone_id is not None:
            raise ValueError("Choose an end year or an end milestone, not both.")
        if self.start_year is not None and self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("An adjustment's end year must be on or after its start year.")
        if self.frequency == "once" and (self.end_year is not None or self.end_milestone_id is not None):
            raise ValueError("A one-time adjustment has no end.")
        if (self.frequency == "every_n_years") != (self.interval_years is not None):
            raise ValueError("interval_years is required for, and only for, every_n_years.")
        return self


def _check_unique_ids(adjustments: list[TaxAdjustment]) -> None:
    ids = [item.id for item in adjustments]
    if len(set(ids)) != len(ids):
        raise ValueError("Tax adjustment ids must be unique.")


class ScheduledTaxSettings(BaseModel):
    """The tax settings a scheduled change may replace. Omitted keys are kept.

    ``state_brackets: []`` returns to the built-in state tables and
    ``federal_brackets: []`` to the built-in federal brackets.
    ``adjustments`` replaces the whole adjustment list.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    mode: Literal["detailed", "flat"] | None = Field(default=None, exclude_if=omit_none)
    ordinary_income_tax_rate: float | None = Field(default=None, ge=0, le=1, exclude_if=omit_none)
    capital_gains_tax_rate: float | None = Field(default=None, ge=0, le=1, exclude_if=omit_none)
    state_brackets: StateBrackets | None = Field(default=None, exclude_if=omit_none)
    adjustments: list[TaxAdjustment] | None = Field(
        default=None, max_length=MAX_TAX_ADJUSTMENTS, exclude_if=omit_none)
    state_deduction_rules: bool | None = Field(default=None, exclude_if=omit_none)
    federal_brackets: FederalBrackets | None = Field(default=None, exclude_if=omit_none)
    federal_standard_deduction: float | None = Field(
        default=None, ge=0, le=MAX_ADJUSTMENT_AMOUNT, exclude_if=omit_none)

    @model_validator(mode="after")
    def _not_empty(self) -> "ScheduledTaxSettings":
        if all(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError("A scheduled tax change must set at least one setting.")
        if self.adjustments:
            _check_unique_ids(self.adjustments)
        return self


class ScheduledTaxChange(BaseModel):
    """Settings that take effect from a calendar year or a milestone's year."""

    model_config = ConfigDict(extra="forbid")

    year: int | None = Field(default=None, ge=1900, le=2300, exclude_if=omit_none)
    milestone_id: str | None = Field(default=None, max_length=64, exclude_if=omit_none)
    settings: ScheduledTaxSettings

    @model_validator(mode="after")
    def _one_trigger(self) -> "ScheduledTaxChange":
        if (self.year is None) == (self.milestone_id is None):
            raise ValueError("Choose either a year or a milestone for a scheduled tax change.")
        return self


class TaxCustomizationFields(BaseModel):
    """Mixed into the persisted and stateless tax settings models."""

    adjustments: list[TaxAdjustment] = Field(
        default_factory=list, max_length=MAX_TAX_ADJUSTMENTS, exclude_if=lambda value: not value)
    scheduled_changes: list[ScheduledTaxChange] = Field(
        default_factory=list, max_length=MAX_SCHEDULED_TAX_CHANGES, exclude_if=lambda value: not value)
    # Opt-in statutory state itemized/standard choice, exemption phaseouts and
    # federal income tax subtraction for states with supported rules.
    state_deduction_rules: bool = Field(default=False, exclude_if=lambda value: not value)
    # Custom federal ordinary-income brackets for every filing status, and a
    # basic standard deduction in their place (coastmath.engine.tax_engine
    # .federal_ordinary_schedule). Capital gains rates, NIIT, AMT and credits
    # keep the built-in law. Indexed amounts are plan-start dollars grown with
    # plan inflation; unindexed amounts are nominal in every year.
    federal_brackets: FederalBrackets | None = Field(default=None, exclude_if=omit_none)
    federal_standard_deduction: float | None = Field(
        default=None, ge=0, le=MAX_ADJUSTMENT_AMOUNT, exclude_if=omit_none)
    federal_overrides_indexed: bool = Field(default=True, exclude_if=lambda value: value)
    # Owner RMD start ages in place of the SECURE 2.0 schedule, for modeling a
    # possible law change; inherited-account rules are unchanged.
    rmd_start_ages: dict[Literal["self", "spouse"], Annotated[
        int, Field(ge=MIN_RMD_START_AGE, le=MAX_RMD_START_AGE)]] | None = Field(default=None, exclude_if=omit_none)

    @model_validator(mode="after")
    def _unique_adjustments(self):
        _check_unique_ids(self.adjustments)
        return self


def all_adjustments(tax_settings: dict | None) -> list[dict]:
    """The plan-level adjustments and those inside scheduled changes."""
    settings = tax_settings or {}
    rows = list(settings.get("adjustments") or [])
    for change in settings.get("scheduled_changes") or []:
        rows.extend((change.get("settings") or {}).get("adjustments") or [])
    return rows


def referenced_milestone_ids(tax_settings: dict | None) -> set[str]:
    """Every milestone id the tax customization in ``tax_settings`` refers to."""
    ids = {str(change["milestone_id"]) for change in (tax_settings or {}).get("scheduled_changes") or []
           if change.get("milestone_id")}
    for row in all_adjustments(tax_settings):
        for key in ("start_milestone_id", "end_milestone_id"):
            if row.get(key):
                ids.add(str(row[key]))
    return ids
