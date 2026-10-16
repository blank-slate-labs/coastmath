"""Explicit annual coverage; omitted coverage never establishes eligibility."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CoveragePeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: Literal["self", "spouse"]
    start_year: int = Field(ge=2025, le=2300)
    # Inclusive; null continues through the projection horizon.
    end_year: int | None = Field(default=None, ge=2025, le=2300)

    @model_validator(mode="after")
    def chronological(self):
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("Coverage end_year must be on or after start_year.")
        return self


class HSACoverage(CoveragePeriod):
    # An eligible month asserts HDHP, no disqualifying coverage/Medicare and
    # no dependent status on that month's first day. No last-month rule.
    coverage: Literal["self_only", "family", "ineligible"]
    # Applies only to employee HSA contributions allocated through payroll.
    # Null preserves old-client behavior; direct never excludes FICA wages.
    payroll_funding: Literal["cafeteria", "direct"] | None = None
    eligible_months: list[Annotated[int, Field(ge=1, le=12)]] = Field(
        default_factory=lambda: list(range(1, 13)), max_length=12)

    @model_validator(mode="after")
    def unique_months(self):
        if len(set(self.eligible_months)) != len(self.eligible_months):
            raise ValueError("HSA eligible_months must be unique.")
        if self.coverage != "ineligible" and not self.eligible_months:
            raise ValueError("Eligible coverage requires at least one eligible month.")
        return self


class StatePayrollCoverage(CoveragePeriod):
    # W2 work localization and coverage from the first day of start_month.
    # Later years are full years; omitted preserves January coverage.
    start_month: int = Field(default=1, ge=1, le=12)
    state_code: Literal["CA", "WA"]
    ca_sdi: bool = False
    wa_paid_leave: bool = False
    wa_cares: bool = False
    employer_pays_fraction: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def compatible_programs(self):
        if (self.state_code == "CA" and (self.wa_paid_leave or self.wa_cares)
                or self.state_code == "WA" and self.ca_sdi):
            raise ValueError("Payroll program must match the covered work state.")
        return self


class CoverageSettings(BaseModel):
    # Opening-year reported state-program wages can differ from federal FICA
    # wages (for example California HSA contributions). Omitted keeps legacy
    # W2 history; zero explicitly replaces it for this person's state programs.
    state_payroll_wages_year_to_date: dict[Literal["self", "spouse"],
        Annotated[float, Field(ge=0, allow_inf_nan=False)]] = Field(default_factory=dict)
    # Per tax year: absent is unknown, zero explicitly means no dependents.
    ca_dependents_by_year: dict[Annotated[int, Field(ge=2025, le=2300)],
                                Annotated[int, Field(ge=0, le=30)]] = Field(default_factory=dict)
    # Ohio exemptions require an explicit federal dependent claim each year;
    # birth years alone do not establish student, support or residency tests.
    oh_dependents_by_year: dict[Annotated[int, Field(ge=2025, le=2300)],
                                Annotated[int, Field(ge=0, le=30)]] = Field(default_factory=dict)
    # Federal child tax credit: one birth year per child (IRC 24, under 17).
    dependent_birth_years: list[Annotated[int, Field(ge=1900, le=2300)]] = Field(
        default_factory=list, max_length=20)
    hsa_coverage: list[HSACoverage] = Field(default_factory=list, max_length=200)
    state_payroll_coverage: list[StatePayrollCoverage] = Field(default_factory=list, max_length=200)
    # Opening projection year only. Omitted amounts mean unpaid, not an
    # estimate of prior withholding; overpayments do not invent refunds.
    state_payroll_paid_year_to_date: dict[
        Literal["California SDI", "Washington Paid Leave", "Washington Cares"],
        Annotated[float, Field(ge=0, allow_inf_nan=False)],
    ] = Field(default_factory=dict)
    # None means unknown; [] explicitly establishes no personal exemption.
    ca_exemption_eligible_owners: list[Literal["self", "spouse"]] | None = Field(default=None, max_length=2)
    oh_exemption_eligible_owners: list[Literal["self", "spouse"]] | None = Field(default=None, max_length=2)

    @model_validator(mode="after")
    def nonoverlapping_periods(self):
        if self.ca_exemption_eligible_owners is not None and len(set(self.ca_exemption_eligible_owners)) != len(self.ca_exemption_eligible_owners):
            raise ValueError("California exemption owners must be unique.")
        if self.oh_exemption_eligible_owners is not None and len(set(self.oh_exemption_eligible_owners)) != len(self.oh_exemption_eligible_owners):
            raise ValueError("Ohio exemption owners must be unique.")
        for rows in (self.hsa_coverage, self.state_payroll_coverage):
            for i, row in enumerate(rows):
                for other in rows[:i]:
                    if row.owner == other.owner and max(row.start_year, other.start_year) <= min(
                            row.end_year or 2300, other.end_year or 2300):
                        raise ValueError("Coverage periods for an owner must not overlap.")
        return self
