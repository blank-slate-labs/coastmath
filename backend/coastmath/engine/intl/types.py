"""Value types shared by the international tax evaluator, its packs and the simulator.

Inputs and results are frozen dataclasses: they are created once per tax year,
never mutated, and cheap to build inside the yearly loop. The regime data itself
(`RegimeSpec`, `AccountKindSpec`) is Pydantic because it is loaded from JSON and
user documents and must be validated.

Totals on `RegimeYearResult` group line categories as follows:

- `income_tax`: `income_national`, `income_regional`, `income_local` and `credit`
  lines (credits are negative).
- `social_contributions`: `social_contribution` and `levy` lines.
- `wealth_tax`, `transaction_tax` and `benefit_recovery`: their own category.
- `total`: every line.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from coastmath.engine.intl.spec import RegimeSpec, TransactionTaxSpec, WealthTaxSpec


class IncomeType(StrEnum):
    """Fixed income vocabulary. Packs classify these; they never add new types."""

    EMPLOYMENT = "employment"
    SELF_EMPLOYMENT = "self_employment"
    # Private pensions and annuities.
    PENSION = "pension"
    # Any state pension, including US Social Security received abroad.
    GOVERNMENT_PENSION = "government_pension"
    # The taxable part of a tax-deferred account withdrawal.
    RETIREMENT_WITHDRAWAL = "retirement_withdrawal"
    INTEREST = "interest"
    DIVIDENDS_QUALIFIED = "dividends_qualified"
    DIVIDENDS_OTHER = "dividends_other"
    # Net realized gains, before any inclusion rate.
    CAPITAL_GAINS = "capital_gains"
    # Net rental income.
    RENTAL = "rental"
    OTHER_TAXABLE = "other_taxable"
    NONTAXABLE = "nontaxable"


INCOME_TYPES: tuple[IncomeType, ...] = tuple(IncomeType)

Person = Literal["self", "spouse"]
Filing = Literal["single", "couple"]
AccountCategory = Literal["taxable", "tax_deferred", "tax_free", "cash"]
ACCOUNT_CATEGORIES: tuple[str, ...] = ("taxable", "tax_deferred", "tax_free", "cash")

TaxLineCategory = Literal[
    "income_national",
    "income_regional",
    "income_local",
    "social_contribution",
    "levy",
    "wealth",
    "transaction",
    "credit",
    "benefit_recovery",
]
INCOME_TAX_CATEGORIES = frozenset({"income_national", "income_regional", "income_local", "credit"})
SOCIAL_CATEGORIES = frozenset({"social_contribution", "levy"})


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapitalGainParts:
    """How a person's `capital_gains` income splits, for specs that need it.

    All amounts are already inside `capital_gains` (the engine's nominal net
    realized gain). The evaluator reads them only when the spec's capital gains
    section asks for them (`cost_base_indexation`, `main_residence_exempt`).

    - `deferred`: the gain (or loss, negative) accrued before the indexation
      start on holdings sold this year.
    - `indexation`: how much cost-base indexation lowers the remaining gain (>= 0).
    - `main_residence`: gain on the sale of the main residence (>= 0).
    """

    deferred: float = 0.0
    indexation: float = 0.0
    main_residence: float = 0.0


@dataclass(frozen=True, slots=True)
class PersonYear:
    """One person's tax-relevant amounts for one year (in the plan currency)."""

    person: Person
    age: int
    alive: bool = True
    income: dict[str, float] = field(default_factory=dict)
    # Contributions to account kinds marked `contribution_deductible`.
    deductible_contributions: float = 0.0
    # Benefit rule id -> amount received this year (for clawbacks).
    benefit_amounts: dict[str, float] = field(default_factory=dict)
    # The split of `capital_gains` (None: all of it is an ordinary gain).
    capital_gain_parts: CapitalGainParts | None = None

    def __post_init__(self) -> None:
        if isinstance(self.capital_gain_parts, dict):
            object.__setattr__(self, "capital_gain_parts", CapitalGainParts(**self.capital_gain_parts))

    def amount(self, income_type: str) -> float:
        return float(self.income.get(income_type, 0.0) or 0.0)


@dataclass(frozen=True, slots=True)
class WealthBalances:
    """Balances by category. `debts` and `primary_home_mortgage` are positive amounts owed."""

    cash: float = 0.0
    taxable: float = 0.0
    tax_deferred: float = 0.0
    tax_free: float = 0.0
    real_assets: float = 0.0
    primary_home: float = 0.0
    debts: float = 0.0
    primary_home_mortgage: float = 0.0
    liquid_net_worth: float = 0.0
    net_worth: float = 0.0


@dataclass(frozen=True, slots=True)
class WealthInputs:
    """Household balances plus an optional split by person.

    When a person-level wealth tax needs a person missing from `by_person`, the
    evaluator splits `household` equally among the living people.
    """

    household: WealthBalances
    by_person: dict[str, WealthBalances] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Callers may pass plain dicts with the `WealthBalances` field names.
        object.__setattr__(self, "household", _balances(self.household))
        object.__setattr__(
            self, "by_person", {person: _balances(value) for person, value in self.by_person.items()}
        )


def _balances(value: WealthBalances | dict[str, float]) -> WealthBalances:
    if isinstance(value, WealthBalances):
        return value
    return WealthBalances(**{key: float(amount) for key, amount in dict(value).items()})


@dataclass(frozen=True, slots=True)
class TradeInputs:
    """Purchases and sales during the year, by account category."""

    purchases: dict[str, float] = field(default_factory=dict)
    sales: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RegimeOverrides:
    """User overrides that replace a pack's wealth or transaction section."""

    wealth_tax: WealthTaxSpec | None = None
    transaction_tax: TransactionTaxSpec | None = None

    def __post_init__(self) -> None:
        # Plain dicts (as stored in `intl_settings`) are validated here.
        from coastmath.engine.intl.spec import (  # noqa: PLC0415 - spec imports this module
            TransactionTaxSpec,
            WealthTaxSpec,
        )

        if isinstance(self.wealth_tax, dict):
            object.__setattr__(self, "wealth_tax", WealthTaxSpec.model_validate(self.wealth_tax))
        if isinstance(self.transaction_tax, dict):
            object.__setattr__(
                self, "transaction_tax", TransactionTaxSpec.model_validate(self.transaction_tax)
            )


@dataclass(frozen=True, slots=True)
class RegimeYearInputs:
    country: str
    year: int
    people: tuple[PersonYear, ...]
    region: str | None = None
    # Cumulative inflation from the spec's base year to `year` along the plan path.
    inflation_factor: float = 1.0
    filing: Filing = "single"
    wealth: WealthInputs | None = None
    trades: TradeInputs | None = None
    prior_year: RegimeYearResult | None = None
    # Used when `country == "XX"` (Other / custom).
    custom_spec: RegimeSpec | None = None
    # A `RegimeOverrides`, or a dict `{"wealth_tax": dict | None, "transaction_tax": dict | None}`.
    overrides: RegimeOverrides | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "people", tuple(self.people))
        if isinstance(self.overrides, dict):
            object.__setattr__(self, "overrides", RegimeOverrides(**self.overrides))
        if isinstance(self.wealth, dict):
            object.__setattr__(self, "wealth", WealthInputs(**self.wealth))
        if isinstance(self.trades, dict):
            object.__setattr__(self, "trades", TradeInputs(**self.trades))


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaxLine:
    code: str
    label: str
    category: TaxLineCategory
    person: Person | None
    amount: float


@dataclass(frozen=True, slots=True)
class RegimeYearResult:
    lines: list[TaxLine]
    income_tax: float
    social_contributions: float
    wealth_tax: float
    transaction_tax: float
    benefit_recovery: float
    total: float
    taxable_income_by_person: dict[str, float]
    # Combined marginal rate on an extra unit of `retirement_withdrawal` income.
    marginal_ordinary_rate_by_person: dict[str, float]

    @classmethod
    def from_lines(
        cls,
        lines: list[TaxLine],
        taxable_income_by_person: dict[str, float],
        marginal_ordinary_rate_by_person: dict[str, float] | None = None,
    ) -> RegimeYearResult:
        def total(categories: frozenset[str] | set[str]) -> float:
            return sum((line.amount for line in lines if line.category in categories), 0.0)

        return cls(
            lines=list(lines),
            income_tax=total(INCOME_TAX_CATEGORIES),
            social_contributions=total(SOCIAL_CATEGORIES),
            wealth_tax=total({"wealth"}),
            transaction_tax=total({"transaction"}),
            benefit_recovery=total({"benefit_recovery"}),
            total=sum((line.amount for line in lines), 0.0),
            taxable_income_by_person=dict(taxable_income_by_person),
            marginal_ordinary_rate_by_person=dict(marginal_ordinary_rate_by_person or {}),
        )


# ---------------------------------------------------------------------------
# Benefit and estate rule protocols
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BenefitContext:
    year: int
    age: int
    birth_year: int
    birth_month: int
    # Resolved by integration from `start_age` or `start_milestone_id`.
    start_age: int | None
    # An instance of the rule's `params_model`.
    params: BaseModel
    # Cumulative inflation from the plan's start year to `year`.
    inflation_factor: float
    prior_year: RegimeYearResult | None
    filing: Filing
    # None when there is no spouse.
    spouse_alive: bool | None = None
    spouse_benefit_amounts: dict[str, float] = field(default_factory=dict)
    # Whose benefit this is (`intl_settings.benefits[].owner`).
    owner: Person = "self"


@dataclass(frozen=True, slots=True)
class BenefitYear:
    amount: float
    income_type: IncomeType = IncomeType.GOVERNMENT_PENSION
    notes: tuple[str, ...] = ()


@runtime_checkable
class BenefitRule(Protocol):
    id: str
    label: str
    params_model: type[BaseModel]

    def annual_amount(self, ctx: BenefitContext) -> BenefitYear: ...


@dataclass(frozen=True, slots=True)
class EstateInputs:
    """A death in a year assessed under `country`.

    `gross_estate` is the decedent's share of net worth; `wealth` optionally gives
    that share by category (a `WealthBalances` or a dict of its fields).
    `predeceased_partner` is true at the last death of a couple whose other
    partner died first.
    """

    country: str
    year: int
    decedent: Person
    age: int
    gross_estate: float
    region: str | None = None
    surviving_spouse: bool = False
    inflation_factor: float = 1.0
    wealth: WealthBalances | None = None
    # The decedent outlived a partner (for allowances that transfer between
    # partners, such as transferable estate tax bands).
    predeceased_partner: bool = False
    # Inputs for income deemed at death (the decedent's share; empty when the
    # caller has none). `unrealized_gains` by `DEATH_GAIN_KEYS`: "taxable"
    # (taxable accounts), "real_assets" (real assets other than the main
    # home) and "primary_home" (the one main home an exemption may cover).
    unrealized_gains: dict[str, float] = field(default_factory=dict)
    # Balances of tax-deferred country accounts whose withdrawals are income.
    taxable_deferred_balance: float = 0.0
    # The death year's `RegimeYearInputs`, so a rule can recompute that
    # year's return with the deemed income.
    terminal_year: RegimeYearInputs | None = None

    def __post_init__(self) -> None:
        if self.wealth is not None:
            object.__setattr__(self, "wealth", _balances(self.wealth))
        unknown = set(self.unrealized_gains) - set(DEATH_GAIN_KEYS)
        if unknown:
            raise ValueError(f"unknown unrealized gain categories {sorted(unknown)}")
        object.__setattr__(
            self, "unrealized_gains",
            {key: float(amount) for key, amount in dict(self.unrealized_gains).items()},
        )


DEATH_GAIN_KEYS: tuple[str, ...] = ("taxable", "real_assets", "primary_home")


@runtime_checkable
class EstateRule(Protocol):
    country: str

    def estate_tax(self, inputs: EstateInputs) -> float: ...


# `AccountKindSpec` lives in spec.py (it is part of the pack schema); re-exported
# here so callers can import every public type from one module.
def __getattr__(name: str) -> Any:  # pragma: no cover - trivial
    if name == "AccountKindSpec":
        from coastmath.engine.intl.spec import (  # noqa: PLC0415 - spec imports this module
            AccountKindSpec,
        )

        return AccountKindSpec
    raise AttributeError(name)
