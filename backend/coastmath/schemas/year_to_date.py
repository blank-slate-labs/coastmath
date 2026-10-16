"""Opening calendar-year tax information; amounts precede the plan start."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
OwnerAmounts = dict[Literal["self", "spouse"], Nonnegative]


class YearToDateTax(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    tax_year: int = Field(ge=1900, le=2200)
    gross_income: Nonnegative = 0
    social_security_income: Nonnegative = 0
    capital_gains: float = 0
    qualified_dividends: Nonnegative = 0
    net_investment_income: Nonnegative = 0
    deductions: Nonnegative = 0
    tax_paid: Nonnegative = 0
    state_tax_paid: Nonnegative = 0
    property_tax: Nonnegative = 0
    mortgage_interest: Nonnegative = 0
    w2_income_by_owner: OwnerAmounts = Field(default_factory=dict)
    self_employment_income_by_owner: OwnerAmounts = Field(default_factory=dict)
    contributions_by_account: dict[str, Nonnegative] = Field(default_factory=dict, max_length=200)
    employer_contributions_by_account: dict[str, Nonnegative] = Field(default_factory=dict, max_length=200)
    # Withdrawals already taken from each account. They count toward this
    # year's required distribution; their income belongs in gross_income.
    distributions_by_account: dict[str, Nonnegative] = Field(default_factory=dict, max_length=200)

    @model_validator(mode="after")
    def check_totals(self):
        ordinary_components = (sum(self.w2_income_by_owner.values())
                               + sum(self.self_employment_income_by_owner.values())
                               + self.net_investment_income)
        if ordinary_components > self.gross_income + .01:
            raise ValueError("Gross ordinary income must include wages, business income and ordinary investment income")
        if self.state_tax_paid > self.tax_paid + .01:
            raise ValueError("Total taxes paid must include state income tax paid")
        return self
