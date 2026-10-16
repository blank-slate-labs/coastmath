from itertools import pairwise
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SsBenefitBasis = Literal["amount", "pia"]


def validate_ss_benefit_basis(
    basis: str | None, pia_monthly: float | None, claiming_age: int | None, tax_category: str | None,
) -> None:
    """PIA basis needs a Social Security category, a positive PIA and a claiming age."""
    if basis != "pia":
        return
    if tax_category != "social_security":
        raise ValueError("PIA basis applies only to Social Security income (tax_category social_security)")
    if pia_monthly is None or pia_monthly <= 0:
        raise ValueError("PIA basis requires a positive monthly PIA (pia_monthly)")
    if claiming_age is None:
        raise ValueError("PIA basis requires a claiming age")


GrowthSegmentKind = Literal["percent", "inflation_offset", "dollar_change", "set_amount"]


class GrowthSegment(BaseModel):
    """One calendar-year span of an income growth schedule.

    ``percent``: ``value`` percent per year. ``inflation_offset``: that year's
    inflation plus ``value`` percentage points. ``dollar_change``: ``value``
    dollars per year. ``set_amount``: the annual amount is ``value`` in each
    covered year. Dollar kinds state ``dollars``: ``today`` (plan-start
    dollars, inflated) or ``nominal``. ``end_year`` is inclusive; null runs on.
    """
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start_year: int = Field(ge=1900, le=2200)
    end_year: int | None = Field(default=None, ge=1900, le=2200)
    kind: GrowthSegmentKind
    value: float = Field(ge=-1_000_000_000, le=1_000_000_000)
    dollars: Literal["today", "nominal"] | None = None

    @model_validator(mode="after")
    def check_segment(self):
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("A growth segment cannot end before it starts")
        dollar_kind = self.kind in {"dollar_change", "set_amount"}
        if dollar_kind and self.dollars is None:
            raise ValueError("Dollar growth segments must state today's or nominal dollars")
        if not dollar_kind and self.dollars is not None:
            raise ValueError("Only dollar growth segments take a dollar unit")
        if self.kind == "set_amount" and self.value < 0:
            raise ValueError("A set amount cannot be negative")
        if self.kind in {"percent", "inflation_offset"} and not -100 <= self.value <= 100:
            raise ValueError("Growth percentages must be between -100 and 100")
        return self


def validate_growth_schedule(segments: list[GrowthSegment] | None) -> None:
    """Segments must be in start-year order and must not overlap."""
    for previous, current in pairwise(segments or []):
        if previous.end_year is None or previous.end_year >= current.start_year:
            raise ValueError("Growth segments must be in year order and must not overlap")


GrowthSchedule = Annotated[list[GrowthSegment], Field(max_length=50)]


class ExSpouseRecord(BaseModel):
    """A former spouse's Social Security record for divorced-spouse benefits.

    ``pia_monthly`` is in plan-start dollars like the stream's own PIA.
    ``claim_age`` null means the former spouse has not claimed; ``death_year``
    null means alive. ``current_marriage_year`` is when the claimant's current
    marriage began (a remarriage at 60 or later keeps survivor benefits).
    ``survivor_claim_age`` null starts survivor benefits with the own claim.
    """
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    pia_monthly: float = Field(gt=0, le=100_000)
    birth_year: int = Field(ge=1900, le=2100)
    birth_month: int = Field(default=1, ge=1, le=12)
    marriage_years: float | None = Field(default=None, ge=0, le=100)
    marriage_lasted_10_years: bool = False
    divorce_year: int = Field(ge=1900, le=2200)
    divorce_month: int | None = Field(default=None, ge=1, le=12)
    claim_age: float | None = Field(default=None, ge=62, le=70)
    death_year: int | None = Field(default=None, ge=1900, le=2200)
    current_marriage_year: int | None = Field(default=None, ge=1900, le=2200)
    survivor_claim_age: float | None = Field(default=None, ge=60, le=70)

    @model_validator(mode="after")
    def check_record(self):
        if self.marriage_years is None and not self.marriage_lasted_10_years:
            raise ValueError("Enter the marriage length or confirm it lasted at least 10 years")
        if self.death_year is not None and self.death_year < self.divorce_year:
            raise ValueError("The former spouse's death year cannot precede the divorce")
        if self.divorce_year < self.birth_year:
            raise ValueError("The divorce year cannot precede the former spouse's birth")
        return self


def validate_income_extensions(
    *, growth_schedule, ex_spouse, ss_benefit_basis, tax_category, is_social_security, pension_formula,
) -> None:
    """Growth schedules fit non-Social-Security amounts; ex-spouse records fit PIA basis."""
    if growth_schedule:
        if is_social_security or tax_category == "social_security":
            raise ValueError("Social Security benefits grow with COLA; a growth schedule does not apply")
        if pension_formula:
            raise ValueError("A formula pension sets its own amount; a growth schedule does not apply")
    if ex_spouse is not None and ss_benefit_basis != "pia":
        raise ValueError("A former spouse's record requires a PIA-basis Social Security benefit")


IncomeTaxCategory = Literal["employment", "self_employment", "qualified_pension", "investment", "nonqualified_annuity", "other_ordinary", "social_security", "nontaxable"]

class PensionFormula(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    kind: Literal["flat", "final_average", "career_average"]
    linked_income_id: str | None = None
    benefit_percent_per_year: float = Field(default=0, ge=0, le=100)
    years_of_service_before_plan: float = Field(default=0, ge=0, le=100)
    final_average_years: int = Field(default=3, ge=1, le=50)
    flat_annual_amount: float | None = Field(default=None, ge=0)
    cola_percent: float | None = Field(default=None, ge=-100, le=100)

    @model_validator(mode="after")
    def check_formula(self):
        if self.kind == "flat" and self.flat_annual_amount is None:
            raise ValueError("Flat pension requires an annual amount")
        if self.kind != "flat" and not self.linked_income_id:
            raise ValueError("Salary-linked pension requires a salary income")
        return self


class IncomeCategoryFields(BaseModel):
    @model_validator(mode="after")
    def align_category_flags(self):
        if self.tax_category is not None:
            self.is_social_security = self.tax_category == "social_security"
            self.is_earned_income = self.tax_category in {"employment", "self_employment"}
            self.is_self_employed = self.tax_category == "self_employment"
        return self
