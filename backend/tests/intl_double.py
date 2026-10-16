"""A small stand-in for the country tax regime package (``coastmath.engine.intl``).

It implements the shared contract's public names with simple, predictable
rules so integration tests can check the planner's wiring independently of
the real country packs:

- Country ``ZZ`` ("Testland", regions ``N`` and ``S``): national income tax
  is a flat 20% of taxable income after deductible contributions; region
  ``S`` adds 5%. Capital gains are half included; ``nontaxable`` income is
  excluded. A 5% social contribution applies to employment income. The
  optional wealth tax is 1% of net worth above 100,000 per person; the
  optional transaction tax is 0.5% of sales. A benefit-recovery line takes
  15% of a person's ``ZZ:pension`` benefit when their other taxable income
  exceeds 50,000. Estate tax is 10% of a gross estate above 100,000.
  Account kinds include ``saver`` (access age 60 with a 20% early-withdrawal
  penalty) and ``preserved`` (access age 60, no penalty).
- Country ``XX``: tax at the custom spec's flat ``rate`` on taxable income.

Every call is recorded in ``CALLS`` for assertions.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CALLS: list[Any] = []


class IncomeType(enum.StrEnum):
    employment = "employment"
    self_employment = "self_employment"
    pension = "pension"
    government_pension = "government_pension"
    retirement_withdrawal = "retirement_withdrawal"
    interest = "interest"
    dividends_qualified = "dividends_qualified"
    dividends_other = "dividends_other"
    capital_gains = "capital_gains"
    rental = "rental"
    other_taxable = "other_taxable"
    nontaxable = "nontaxable"


@dataclass(frozen=True)
class PersonYear:
    person: str
    age: int
    alive: bool
    income: dict
    deductible_contributions: float = 0.0
    benefit_amounts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WealthInputs:
    household: dict
    by_person: dict


@dataclass(frozen=True)
class TradeInputs:
    purchases: dict
    sales: dict


@dataclass(frozen=True)
class TaxLine:
    code: str
    label: str
    category: str
    person: str | None
    amount: float


@dataclass(frozen=True)
class RegimeYearResult:
    lines: list
    income_tax: float = 0.0
    social_contributions: float = 0.0
    wealth_tax: float = 0.0
    transaction_tax: float = 0.0
    benefit_recovery: float = 0.0
    total: float = 0.0
    taxable_income_by_person: dict = field(default_factory=dict)
    marginal_ordinary_rate_by_person: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RegimeYearInputs:
    country: str
    region: str | None
    year: int
    inflation_factor: float
    filing: str
    people: tuple
    wealth: WealthInputs | None = None
    trades: TradeInputs | None = None
    prior_year: RegimeYearResult | None = None
    custom_spec: Any = None
    overrides: Any = None


@dataclass(frozen=True)
class BenefitContext:
    year: int
    age: int
    birth_year: int
    birth_month: int
    start_age: int | None
    params: Any
    inflation_factor: float
    prior_year: Any
    filing: str
    spouse_alive: bool | None = None
    spouse_benefit_amounts: dict = field(default_factory=dict)
    owner: str = "self"


@dataclass(frozen=True)
class BenefitYear:
    amount: float
    income_type: str = "government_pension"
    notes: tuple = ()


@dataclass(frozen=True)
class EstateInputs:
    country: str
    year: int
    decedent: str
    age: int
    gross_estate: float
    region: str | None = None
    surviving_spouse: bool = False
    inflation_factor: float = 1.0
    wealth: Any = None
    predeceased_partner: bool = False
    unrealized_gains: dict = field(default_factory=dict)
    taxable_deferred_balance: float = 0.0
    terminal_year: Any = None


class ContributionLimitSpec(BaseModel):
    annual_amount: float | None = None
    percent_of_earned_income: float | None = None
    percent_cap_amount: float | None = None
    age_min: float | None = None
    age_max: float | None = None
    shared_group: str | None = None
    lifetime_cap: float | None = None
    balance_cap: float | None = None
    index: bool = True


class MinimumWithdrawalSpec(BaseModel):
    start_age: float
    rates_by_age: dict[int, float]


class ConversionSpec(BaseModel):
    kind_id: str
    age: float


class AccountKindSpec(BaseModel):
    id: str
    label: str
    category: Literal["taxable", "tax_deferred", "tax_free", "cash"]
    contribution_limit: ContributionLimitSpec | None = None
    contribution_deductible: bool = False
    contribution_tax_rate: float = 0.0
    earnings_tax_rate: float = 0.0
    access_age: float | None = None
    early_withdrawal_penalty_rate: float = 0.0
    withdrawal_taxable: bool = True
    tax_free_withdrawal_fraction: float = 0.0
    tax_free_lifetime_cap: float | None = None
    minimum_withdrawal: MinimumWithdrawalSpec | None = None
    converts_to: ConversionSpec | None = None
    bonus_rate: float = 0.0
    bonus_cap: float | None = None
    employer_match_allowed: bool = False


class WealthTaxSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate: float = Field(ge=0, le=1)
    allowance: float = Field(default=0, ge=0)


class TransactionTaxSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate: float = Field(ge=0, le=1)
    applies_to: Literal["buy", "sell", "both"] = "sell"


class MetaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str
    base_year: int = 2026


class RegimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: MetaSpec
    rate: float = Field(default=0.1, ge=0, le=1)
    wealth_tax: WealthTaxSpec | None = None
    transaction_tax: TransactionTaxSpec | None = None


class PensionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annual_amount: float = Field(ge=0)
    default_start_age: int = 65
    survivor_fraction: float = Field(default=0.6, ge=0, le=1)


class PensionRule:
    id = "ZZ:pension"
    label = "Testland pension"
    params_model = PensionParams

    def annual_amount(self, ctx: BenefitContext) -> BenefitYear:
        CALLS.append(("benefit", ctx))
        start = ctx.start_age if ctx.start_age is not None else ctx.params.default_start_age
        if ctx.age < start:
            return BenefitYear(0.0)
        amount = ctx.params.annual_amount * ctx.inflation_factor
        if not ctx.spouse_alive and ctx.owner == "self":
            amount += sum(ctx.spouse_benefit_amounts.values()) * ctx.params.survivor_fraction
        return BenefitYear(amount, "government_pension")


class TestlandEstate:
    def estate_tax(self, inputs: EstateInputs) -> float:
        CALLS.append(("estate", inputs))
        return 0.1 * max(0.0, inputs.gross_estate - 100_000.0)


KINDS = {
    "ZZ": [
        AccountKindSpec(
            id="saver", label="Saver", category="tax_deferred",
            contribution_limit=ContributionLimitSpec(annual_amount=10_000, shared_group="save", age_max=70),
            contribution_deductible=True, access_age=60, early_withdrawal_penalty_rate=0.2,
            tax_free_withdrawal_fraction=0.25, tax_free_lifetime_cap=20_000,
            converts_to=ConversionSpec(kind_id="income", age=71),
        ),
        AccountKindSpec(
            id="partner_saver", label="Partner saver", category="tax_deferred",
            contribution_limit=ContributionLimitSpec(annual_amount=10_000, shared_group="save"),
            contribution_deductible=True,
        ),
        AccountKindSpec(
            id="income", label="Retirement income", category="tax_deferred",
            minimum_withdrawal=MinimumWithdrawalSpec(start_age=71, rates_by_age={71: 0.05, 80: 0.1}),
        ),
        AccountKindSpec(
            id="free", label="Free saver", category="tax_free", withdrawal_taxable=False,
            contribution_limit=ContributionLimitSpec(
                percent_of_earned_income=0.1, percent_cap_amount=5_000, lifetime_cap=12_000, balance_cap=100_000,
                age_min=18, index=False),
            contribution_tax_rate=0.15, earnings_tax_rate=0.1, bonus_rate=0.25, bonus_cap=1_000,
            employer_match_allowed=True,
        ),
        AccountKindSpec(id="brokerage", label="Brokerage", category="taxable"),
        # An access age with no early-withdrawal penalty: preserved until 60.
        AccountKindSpec(id="preserved", label="Preserved saver", category="tax_deferred", access_age=60),
    ],
}
COUNTRIES = {
    "ZZ": SimpleNamespace(
        code="ZZ", name="Testland", currency="TZS", filing_unit="individual",
        regions=[SimpleNamespace(code="N", name="North"), SimpleNamespace(code="S", name="South")],
        benefit_rules=["ZZ:pension"], spec_years=[2026], approximations=["Test approximation."]),
    "XX": SimpleNamespace(
        code="XX", name="Other", currency="", filing_unit="individual", regions=[],
        benefit_rules=[], spec_years=[], approximations=["Custom regime."]),
}


class _Registry:
    def list_countries(self):
        return list(COUNTRIES.values())

    def get_country(self, code):
        return COUNTRIES[code]

    def load_spec(self, code, year):
        return RegimeSpec(meta={"country": code})

    def account_kinds(self, code):
        return KINDS.get(code, [])

    def benefit_rule(self, rule_id):
        if rule_id != PensionRule.id:
            raise KeyError(rule_id)
        return PensionRule()

    def estate_rule(self, code):
        return TestlandEstate() if code == "ZZ" else None


_TAXABLE_TYPES = [t for t in IncomeType if t is not IncomeType.nontaxable]


def _taxable(person: PersonYear) -> float:
    total = 0.0
    for key, amount in person.income.items():
        kind = IncomeType(key)
        if kind is IncomeType.nontaxable:
            continue
        total += amount * (0.5 if kind is IncomeType.capital_gains else 1.0)
    return max(0.0, total - person.deductible_contributions)


def evaluate(inputs: RegimeYearInputs) -> RegimeYearResult:
    CALLS.append(("evaluate", inputs))
    lines: list[TaxLine] = []
    taxable_by_person = {}
    if inputs.country == "XX":
        rate = inputs.custom_spec.rate
        for person in inputs.people:
            taxable = _taxable(person)
            taxable_by_person[person.person] = taxable
            lines.append(TaxLine("custom", "Income tax", "income_national", person.person, taxable * rate))
        income_tax = sum(line.amount for line in lines)
        return RegimeYearResult(lines=lines, income_tax=income_tax, total=income_tax,
                                taxable_income_by_person=taxable_by_person,
                                marginal_ordinary_rate_by_person={p.person: rate for p in inputs.people})
    social = recovery = 0.0
    for person in inputs.people:
        taxable = _taxable(person)
        taxable_by_person[person.person] = taxable
        lines.append(TaxLine("national", "National income tax", "income_national", person.person, 0.2 * taxable))
        if inputs.region == "S":
            lines.append(TaxLine("regional", "South income tax", "income_regional", person.person, 0.05 * taxable))
        employment = person.income.get("employment", 0.0)
        if employment:
            lines.append(TaxLine("social", "Social contribution", "social_contribution", person.person, 0.05 * employment))
            social += 0.05 * employment
        pension = person.benefit_amounts.get("ZZ:pension", 0.0)
        if pension and taxable - pension > 50_000:
            lines.append(TaxLine("recovery", "Pension recovery", "benefit_recovery", person.person, 0.15 * pension))
            recovery += 0.15 * pension
    income_tax = sum(line.amount for line in lines if line.category.startswith("income_"))
    wealth = transaction = 0.0
    overrides = inputs.overrides or {}
    wealth_spec = overrides.get("wealth_tax")
    if wealth_spec and inputs.wealth is not None:
        spec = WealthTaxSpec.model_validate(wealth_spec)
        for person, balances in inputs.wealth.by_person.items():
            amount = spec.rate * max(0.0, balances["net_worth"] - spec.allowance)
            if amount:
                lines.append(TaxLine("wealth", "Wealth tax", "wealth", person, amount))
                wealth += amount
    transaction_spec = overrides.get("transaction_tax")
    if transaction_spec and inputs.trades is not None:
        spec = TransactionTaxSpec.model_validate(transaction_spec)
        base = 0.0
        if spec.applies_to in ("sell", "both"):
            base += sum(inputs.trades.sales.values())
        if spec.applies_to in ("buy", "both"):
            base += sum(inputs.trades.purchases.values())
        if base:
            transaction = spec.rate * base
            lines.append(TaxLine("stamp", "Transaction tax", "transaction", None, transaction))
    total = income_tax + social + recovery + wealth + transaction
    return RegimeYearResult(
        lines=lines, income_tax=income_tax, social_contributions=social, wealth_tax=wealth,
        transaction_tax=transaction, benefit_recovery=recovery, total=total,
        taxable_income_by_person=taxable_by_person,
        marginal_ordinary_rate_by_person={p.person: 0.25 if inputs.region == "S" else 0.2 for p in inputs.people},
    )


def marginal_rate(inputs, person, income_type, delta=1000.0):
    return 0.2


def namespace() -> SimpleNamespace:
    types = SimpleNamespace(
        IncomeType=IncomeType, PersonYear=PersonYear, WealthInputs=WealthInputs, TradeInputs=TradeInputs,
        TaxLine=TaxLine, RegimeYearResult=RegimeYearResult, RegimeYearInputs=RegimeYearInputs,
        BenefitContext=BenefitContext, BenefitYear=BenefitYear, EstateInputs=EstateInputs,
        AccountKindSpec=AccountKindSpec,
    )
    return SimpleNamespace(
        types=types,
        spec=SimpleNamespace(RegimeSpec=RegimeSpec),
        registry=_Registry(),
        evaluator=SimpleNamespace(evaluate=evaluate, marginal_rate=marginal_rate),
    )
