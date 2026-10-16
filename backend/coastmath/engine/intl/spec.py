"""`RegimeSpec`: the data schema of a country tax pack (and of a custom regime).

A pack is `coastmath/data/tax_regimes/<CC>/<YEAR>.json`. Every money figure in a
spec is in the pack currency at `meta.base_year` prices.

Indexing
--------
Each money-bearing component (layer, allowance, credit, wealth and capital-gains
sections, contribution limits) names an index group in `index_group`, or leaves it
null to use the default group. `meta.indexing` maps a group to `inflation` or
`none`; groups it does not list use `meta.default_indexing`. An `inflation` group's
thresholds, allowances, caps and credit amounts are multiplied by
`RegimeYearInputs.inflation_factor` (cumulative from the base year); rates never
are. Account kinds index their limits unless `contribution_limit.index` is false.

Sources
-------
Components carry an optional `source` id. Packs shipped in `coastmath/data` must set
it on every figure-bearing component; the id is a key of the spec's `sources` table
(figure, value and a primary-source citation). Custom regimes leave it empty.
"""
from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from coastmath.engine.intl import plugins
from coastmath.engine.intl.types import ACCOUNT_CATEGORIES, IncomeType

_MODEL_CONFIG = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

Rate = Annotated[float, Field(ge=0.0, le=1.0)]
Money = Annotated[float, Field(ge=0.0)]
RuleRef = Annotated[str, Field(pattern=r"^rule:[A-Z]{2}:[a-z0-9_]+$")]

FilingUnit = Literal["individual", "joint", "joint_splitting"]
IncomeLayerCategory = Literal["income_national", "income_regional", "income_local"]
ContributionCategory = Literal["social_contribution", "levy"]
LayerCategory = Literal[
    "income_national", "income_regional", "income_local", "social_contribution", "levy"
]


class _Model(BaseModel):
    model_config = _MODEL_CONFIG


# ---------------------------------------------------------------------------
# Brackets
# ---------------------------------------------------------------------------


class Bracket(_Model):
    lower: Money
    upper: Money | None = None
    rate: Rate


def _check_brackets(brackets: list[Bracket], what: str) -> list[Bracket]:
    if not brackets:
        raise ValueError(f"{what}: at least one bracket is required")
    if brackets[0].lower != 0:
        raise ValueError(f"{what}: the first bracket must start at 0")
    for index, bracket in enumerate(brackets):
        last = index == len(brackets) - 1
        if last:
            if bracket.upper is not None:
                raise ValueError(f"{what}: the last bracket must be open-ended (upper null)")
            continue
        if bracket.upper is None:
            raise ValueError(f"{what}: only the last bracket may be open-ended")
        if bracket.upper <= bracket.lower:
            raise ValueError(f"{what}: bracket bounds must ascend")
        if brackets[index + 1].lower != bracket.upper:
            raise ValueError(f"{what}: brackets must be contiguous")
    return brackets


Brackets = list[Bracket]


# ---------------------------------------------------------------------------
# Layer components
# ---------------------------------------------------------------------------


class Allowance(_Model):
    """An amount deducted from the layer base, optionally tapered away.

    Effective allowance = max(0, amount - taper_rate * max(0, base - taper_start)).
    In a `joint` unit the allowance is `couple_amount` when set, otherwise
    `amount` times the number of people in the unit.
    """

    label: str | None = None
    amount: Money
    couple_amount: Money | None = None
    taper_start: Money | None = None
    taper_rate: Rate = 0.0
    index_group: str | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _taper(self) -> Allowance:
        if self.taper_rate > 0 and self.taper_start is None:
            raise ValueError("taper_rate requires taper_start")
        return self


class Credit(_Model):
    """A nonrefundable credit worth `amount * rate`, tapered on the layer base.

    The tapered amount is max(0, amount - taper_rate * max(0, base - taper_start)).
    The layer's credits together never exceed the layer's tax.
    """

    label: str | None = None
    amount: Money
    rate: Rate = 1.0
    taper_start: Money | None = None
    taper_rate: Rate = 0.0
    index_group: str | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _taper(self) -> Credit:
        if self.taper_rate > 0 and self.taper_start is None:
            raise ValueError("taper_rate requires taper_start")
        return self


class AlternativeSchedule(_Model):
    """The layer's tax is the lower of its normal tax and this schedule.

    The schedule applies to the layer base before the allowance (for example a
    standard rate on net income).
    """

    label: str | None = None
    brackets: Brackets
    index_group: str | None = None
    source: str | None = None

    @field_validator("brackets")
    @classmethod
    def _brackets(cls, value: list[Bracket]) -> list[Bracket]:
        return _check_brackets(value, "alternative schedule")


class Layer(_Model):
    """One tax computed on income (or on other layers' tax, for a surtax).

    Base (income layers):
        sum over people in the unit and income types of amount * inclusion
        - deductible contributions (`deduct_contributions`; default: income layers only)
        - contribution layers marked `reduces_taxable_income` (income layers only)
        capped at `base_cap`, then reduced by the allowance.

    Base (surtax layers, `base == "layer_tax"`): the sum of `base_layers` tax for
    the people in the unit.

    Inclusion of an income type is `include[type]` when `include` is given (types
    it omits are excluded), otherwise 1.0; `exclude` zeroes types; `nontaxable` is
    never included. For income layers the spec's capital-gains, dividend and
    interest modes then apply (see `RegimeSpec`).

    `mode == "flat"` (non-progressive) taxes the whole base at the rate of the
    bracket the base falls in. `unit` overrides the filing unit; contribution
    layers default to `person`.
    """

    id: Annotated[str, Field(pattern=r"^[a-z0-9_]+$")]
    label: str
    category: LayerCategory
    base: Literal["income", "layer_tax"] = "income"
    base_layers: list[str] = Field(default_factory=list)
    include: dict[IncomeType, Rate] | None = None
    exclude: list[IncomeType] = Field(default_factory=list)
    # None: income layers deduct deductible contributions, contribution layers do not.
    deduct_contributions: bool | None = None
    reduces_taxable_income: bool = False
    unit: Literal["filing", "person"] | None = None
    age_min: int | None = Field(default=None, ge=0, le=130)
    age_max: int | None = Field(default=None, ge=0, le=130)
    allowance: Allowance | None = None
    brackets: Brackets
    couple_brackets: Brackets | None = None
    mode: Literal["progressive", "flat"] = "progressive"
    credits: list[Credit] = Field(default_factory=list)
    alternative: AlternativeSchedule | None = None
    base_cap: Money | None = None
    tax_cap: Money | None = None
    index_group: str | None = None
    source: str | None = None

    @field_validator("brackets", "couple_brackets")
    @classmethod
    def _brackets(cls, value: list[Bracket] | None) -> list[Bracket] | None:
        if value is None:
            return None
        return _check_brackets(value, "layer")

    @model_validator(mode="after")
    def _shape(self) -> Layer:
        if self.base == "layer_tax" and not self.base_layers:
            raise ValueError(f"layer {self.id}: a layer_tax base needs base_layers")
        if self.base == "income" and self.base_layers:
            raise ValueError(f"layer {self.id}: base_layers only applies to a layer_tax base")
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError(f"layer {self.id}: age_min exceeds age_max")
        if self.reduces_taxable_income and self.category not in ("social_contribution", "levy"):
            raise ValueError(
                f"layer {self.id}: only contribution or levy layers can reduce taxable income"
            )
        if self.reduces_taxable_income and self.base == "layer_tax":
            raise ValueError(f"layer {self.id}: a surtax cannot reduce taxable income")
        return self

    @property
    def is_income_layer(self) -> bool:
        return self.category.startswith("income_")

    @property
    def deducts_contributions(self) -> bool:
        if self.deduct_contributions is not None:
            return self.deduct_contributions
        return self.is_income_layer

    @property
    def effective_unit(self) -> str:
        if self.unit is not None:
            return self.unit
        return "filing" if self.is_income_layer else "person"


# ---------------------------------------------------------------------------
# Investment income
# ---------------------------------------------------------------------------


class CostBaseIndexation(_Model):
    """Cost bases indexed by inflation from `start_year` (see `coastmath.engine.intl.gains`).

    Holdings of a household taxed under the regime in `start_year` are deemed sold
    and reacquired at market value at the start of that year. The gain accrued
    before then is deferred until the holding is sold and is included at
    `deferred_inclusion`. The cost base from `start_year` grows with inflation;
    indexation never creates or increases a loss.
    """

    start_year: int
    deferred_inclusion: Rate = 1.0
    source: str | None = None


class CapitalGainsSpec(_Model):
    """Treatment of `capital_gains` income.

    - `ordinary_inclusion`: `inclusion_rate` of gains joins the income layers' base.
    - `separate_brackets`: gains less the allowance are taxed on `brackets`; with
      `stack_on_income` they occupy bracket space above the ordinary taxable
      income of `stack_layer` (default: the first national layer).
    - `flat`: gains less the allowance are taxed at `rate`.
    - `exempt`: gains are not taxed.

    Optional, for regimes that need the engine's split of the gain
    (`PersonYear.capital_gain_parts`):
    - `cost_base_indexation`: gains are measured on indexed cost bases, with a
      deferred pre-transition part; `capital_gains` becomes the net capital gain.
    - `main_residence_exempt`: gains on the main residence are not taxed.
    """

    mode: Literal["ordinary_inclusion", "separate_brackets", "flat", "exempt"] = "ordinary_inclusion"
    inclusion_rate: Rate = 1.0
    rate: Rate | None = None
    brackets: Brackets | None = None
    allowance: Money = 0.0
    stack_on_income: bool = True
    stack_layer: str | None = None
    category: IncomeLayerCategory = "income_national"
    label: str = "Capital gains tax"
    index_group: str | None = None
    source: str | None = None
    cost_base_indexation: CostBaseIndexation | None = None
    main_residence_exempt: bool = False

    @field_validator("brackets")
    @classmethod
    def _brackets(cls, value: list[Bracket] | None) -> list[Bracket] | None:
        return None if value is None else _check_brackets(value, "capital gains")

    @model_validator(mode="after")
    def _mode(self) -> CapitalGainsSpec:
        if self.mode == "flat" and self.rate is None:
            raise ValueError("capital gains: flat mode needs rate")
        if self.mode == "separate_brackets" and not self.brackets:
            raise ValueError("capital gains: separate_brackets mode needs brackets")
        return self


InvestmentMode = Literal["ordinary", "capital_gains_rates", "flat", "separate_brackets", "exempt"]


class InvestmentIncomeSpec(_Model):
    """Treatment of interest or one dividend class.

    - `ordinary`: joins the income layers' base (subject to each layer's inclusion).
    - `capital_gains_rates`: taxed together with gains under the capital-gains mode
      (fully included when that mode is `ordinary_inclusion`).
    - `flat` / `separate_brackets`: a separate line on this income less `allowance`.
    - `exempt`: not taxed.
    - `rule:<CC>:<id>`: removed from the generic treatment; the named custom rule
      handles it.
    """

    mode: InvestmentMode | RuleRef = "ordinary"
    rate: Rate | None = None
    brackets: Brackets | None = None
    allowance: Money = 0.0
    category: IncomeLayerCategory = "income_national"
    label: str | None = None
    index_group: str | None = None
    source: str | None = None

    @field_validator("brackets")
    @classmethod
    def _brackets(cls, value: list[Bracket] | None) -> list[Bracket] | None:
        return None if value is None else _check_brackets(value, "investment income")

    @model_validator(mode="after")
    def _mode(self) -> InvestmentIncomeSpec:
        if self.mode == "flat" and self.rate is None:
            raise ValueError("flat mode needs rate")
        if self.mode == "separate_brackets" and not self.brackets:
            raise ValueError("separate_brackets mode needs brackets")
        return self


class DividendsSpec(_Model):
    qualified: InvestmentIncomeSpec = Field(default_factory=InvestmentIncomeSpec)
    other: InvestmentIncomeSpec = Field(default_factory=InvestmentIncomeSpec)


# ---------------------------------------------------------------------------
# Wealth and transaction taxes
# ---------------------------------------------------------------------------


class WealthTaxSpec(_Model):
    """Annual tax on net worth.

    Base: `net_worth` or `liquid_net_worth` of each person (`unit == "person"`)
    or of the household, less the main-home exemption (equity up to
    `main_home_exemption_cap`; `net_worth` base only) and the allowance, then
    taxed on `brackets` or at `rate`. `rule:<id>` as `base` hands the whole
    computation to a custom rule; `combined_cap` names a rule that may replace
    the wealth lines afterward (for example an income-plus-wealth cap).
    """

    enabled: bool = True
    label: str = "Wealth tax"
    unit: Literal["person", "household"] = "person"
    base: Literal["net_worth", "liquid_net_worth"] | RuleRef = "net_worth"
    allowance: Money = 0.0
    couple_allowance: Money | None = None
    rate: Rate | None = None
    brackets: Brackets | None = None
    main_home_exemption_cap: Money | None = None
    combined_cap: RuleRef | None = None
    index_group: str | None = None
    source: str | None = None

    @field_validator("brackets")
    @classmethod
    def _brackets(cls, value: list[Bracket] | None) -> list[Bracket] | None:
        return None if value is None else _check_brackets(value, "wealth tax")

    @model_validator(mode="after")
    def _rates(self) -> WealthTaxSpec:
        builtin = not self.base.startswith("rule:")
        if builtin and self.enabled and self.rate is None and not self.brackets:
            raise ValueError("wealth tax: give rate or brackets")
        if self.rate is not None and self.brackets:
            raise ValueError("wealth tax: give rate or brackets, not both")
        return self


class TransactionTaxSpec(_Model):
    enabled: bool = True
    label: str = "Transaction tax"
    rate: Rate
    applies_to: Literal["buy", "sell", "both"] = "both"
    account_categories: list[Literal["taxable", "tax_deferred", "tax_free", "cash"]] = Field(
        default_factory=lambda: ["taxable"]
    )
    source: str | None = None


# ---------------------------------------------------------------------------
# Account kinds
# ---------------------------------------------------------------------------


class ContributionLimit(_Model):
    annual_amount: Money | None = None
    percent_of_earned_income: Rate | None = None
    percent_cap_amount: Money | None = None
    age_min: int | None = Field(default=None, ge=0, le=130)
    age_max: int | None = Field(default=None, ge=0, le=130)
    # Kinds sharing a group share one annual limit.
    shared_group: str | None = None
    lifetime_cap: Money | None = None
    balance_cap: Money | None = None
    index: bool = True
    # Room ledger (per owner and shared group): unused room carries forward
    # without limit and each year adds that year's limit; a plan may give the
    # unused room at its start (`intl_settings.starting_room`).
    carry_forward: bool = False
    # Withdrawals add their amount back to room on the next 1 January.
    withdrawals_restore_room: bool = False
    # `percent_of_earned_income` applies to the prior year's earned income.
    percent_of_prior_year_income: bool = False
    # The indexed `annual_amount` is rounded to the nearest multiple of this.
    index_rounding: Annotated[float, Field(gt=0.0)] | None = None
    # `percent_of_earned_income` limits only the member's own contributions;
    # employer contributions count toward `annual_amount` alone.
    percent_limit_excludes_employer: bool = False
    source: str | None = None

    @model_validator(mode="after")
    def _employer_percent(self) -> ContributionLimit:
        if self.percent_limit_excludes_employer and (
                self.percent_of_earned_income is None or self.carry_forward):
            raise ValueError("percent_limit_excludes_employer requires percent_of_earned_income "
                             "and no carry_forward")
        return self


class MinimumWithdrawal(_Model):
    start_age: int = Field(ge=0, le=130)
    # Age -> fraction of the start-of-year balance; ages above the last key use it.
    rates_by_age: dict[int, Rate]
    source: str | None = None

    @field_validator("rates_by_age")
    @classmethod
    def _rates(cls, value: dict[int, float]) -> dict[int, float]:
        if not value:
            raise ValueError("rates_by_age must not be empty")
        return dict(sorted(value.items()))

    def rate_for_age(self, age: int) -> float:
        if age < self.start_age:
            return 0.0
        rate = 0.0
        for key, value in self.rates_by_age.items():
            if key <= age:
                rate = value
        return rate


class Conversion(_Model):
    kind_id: Annotated[str, Field(pattern=r"^[a-z0-9_]+$")]
    age: int = Field(ge=0, le=130)


class AccountKindSpec(_Model):
    id: Annotated[str, Field(pattern=r"^[a-z0-9_]+$")]
    label: str
    category: Literal["taxable", "tax_deferred", "tax_free", "cash"]
    contribution_limit: ContributionLimit | None = None
    contribution_deductible: bool = False
    contribution_tax_rate: Rate = 0.0
    earnings_tax_rate: Rate = 0.0
    access_age: float | None = Field(default=None, ge=0, le=130)
    early_withdrawal_penalty_rate: Rate = 0.0
    # None: taxable for `tax_deferred`, not taxable otherwise.
    withdrawal_taxable: bool | None = None
    tax_free_withdrawal_fraction: Rate = 0.0
    tax_free_lifetime_cap: Money | None = None
    minimum_withdrawal: MinimumWithdrawal | None = None
    converts_to: Conversion | None = None
    bonus_rate: Rate = 0.0
    bonus_cap: Money | None = None
    employer_match_allowed: bool = False
    source: str | None = None

    @property
    def withdrawal_is_taxable(self) -> bool:
        if self.withdrawal_taxable is not None:
            return self.withdrawal_taxable
        return self.category == "tax_deferred"


assert set(ACCOUNT_CATEGORIES) == {"taxable", "tax_deferred", "tax_free", "cash"}


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


class Region(_Model):
    code: Annotated[str, Field(pattern=r"^[A-Z0-9]{1,8}$")]
    name: str


class CustomRuleRef(_Model):
    id: Annotated[str, Field(pattern=r"^[A-Z]{2}:[a-z0-9_]+$")]
    params: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None


class Meta(_Model):
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    name: str
    base_year: int = Field(ge=1900, le=2200)
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    filing_unit: FilingUnit = "individual"
    regions: list[Region] = Field(default_factory=list)
    default_region: str | None = None
    # Months of the calendar year, notes on how a non-calendar tax year maps, etc.
    notes: list[str] = Field(default_factory=list)
    approximations: list[str] = Field(default_factory=list)
    default_indexing: Literal["inflation", "none"] = "none"
    indexing: dict[str, Literal["inflation", "none"]] = Field(default_factory=dict)


class SourceCitation(_Model):
    """One figure, its value in the spec and the primary source that publishes it."""

    figure: str
    value: str
    citation: str


class RegimeSpec(_Model):
    """A country's regime for the years from `meta.base_year`.

    Evaluation order (see `evaluator.py`): contribution layers that reduce taxable
    income, then national, regional and local income layers (allowance, brackets,
    credits, alternative schedule, caps), then surtaxes, then capital gains and
    investment income, then the remaining contribution and levy layers, then
    wealth and transaction taxes; custom rules run at their declared phase.
    """

    meta: Meta
    national: list[Layer] = Field(default_factory=list)
    regional: dict[str, list[Layer]] = Field(default_factory=dict)
    local: list[Layer] = Field(default_factory=list)
    contributions: list[Layer] = Field(default_factory=list)
    capital_gains: CapitalGainsSpec = Field(default_factory=CapitalGainsSpec)
    dividends: DividendsSpec = Field(default_factory=DividendsSpec)
    interest: InvestmentIncomeSpec = Field(default_factory=InvestmentIncomeSpec)
    wealth_tax: WealthTaxSpec | None = None
    transaction_tax: TransactionTaxSpec | None = None
    account_kinds: list[AccountKindSpec] = Field(default_factory=list)
    benefit_rules: list[str] = Field(default_factory=list)
    custom_rules: list[CustomRuleRef] = Field(default_factory=list)
    # Citations keyed by the `source` ids components carry, and notes on when
    # and against what they were checked.
    sources: dict[str, SourceCitation] = Field(default_factory=dict)
    source_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistency(self) -> RegimeSpec:
        region_codes = [region.code for region in self.meta.regions]
        if len(set(region_codes)) != len(region_codes):
            raise ValueError("duplicate region codes")
        for code in self.regional:
            if code not in region_codes:
                raise ValueError(f"regional layers for unknown region {code!r}")
        if self.meta.default_region is not None and self.meta.default_region not in region_codes:
            raise ValueError(f"default_region {self.meta.default_region!r} is not a listed region")

        layers = self.all_layers()
        shared_ids: set[str] = set()
        for scope, layer in layers:
            if scope.startswith("regional:"):
                continue
            if layer.id in shared_ids:
                raise ValueError(f"duplicate layer id {layer.id!r}")
            shared_ids.add(layer.id)
        for code, regional in self.regional.items():
            regional_ids = [layer.id for layer in regional]
            if len(set(regional_ids)) != len(regional_ids) or shared_ids & set(regional_ids):
                raise ValueError(f"duplicate layer id in region {code!r}")
        for scope, layer in layers:
            if scope == "national" and layer.category != "income_national":
                raise ValueError(f"national layer {layer.id} must use category income_national")
            if scope.startswith("regional:") and layer.category != "income_regional":
                raise ValueError(f"regional layer {layer.id} must use category income_regional")
            if scope == "local" and layer.category != "income_local":
                raise ValueError(f"local layer {layer.id} must use category income_local")
            if scope == "contributions" and layer.category not in ("social_contribution", "levy"):
                raise ValueError(f"contribution layer {layer.id} must use social_contribution or levy")

        # Surtax references must point at an earlier layer visible from that scope.
        for region in [None, *region_codes]:
            order = [layer for _, layer in self.ordered_layers(region)]
            seen_ids: set[str] = set()
            for layer in order:
                for ref in layer.base_layers:
                    if ref not in seen_ids:
                        raise ValueError(
                            f"layer {layer.id}: base layer {ref!r} must be an earlier layer"
                        )
                seen_ids.add(layer.id)

        if self.capital_gains.stack_layer is not None:
            national_ids = {layer.id for layer in self.national}
            if self.capital_gains.stack_layer not in national_ids:
                raise ValueError("capital_gains.stack_layer must be a national layer id")

        kind_ids = [kind.id for kind in self.account_kinds]
        if len(set(kind_ids)) != len(kind_ids):
            raise ValueError("duplicate account kind ids")
        for kind in self.account_kinds:
            if kind.converts_to is not None and kind.converts_to.kind_id not in kind_ids:
                raise ValueError(f"account kind {kind.id}: converts_to names an unknown kind")

        self._check_rule_references()
        return self

    def _check_rule_references(self) -> None:
        for ref in self.rule_ids():
            if plugins.tax_rule(ref) is None:
                raise ValueError(f"unknown custom rule {ref!r}")
        known_benefits = plugins.benefit_rules()
        for rule_id in self.benefit_rules:
            if rule_id not in known_benefits:
                raise ValueError(f"unknown benefit rule {rule_id!r}")

    # -- helpers ----------------------------------------------------------

    def all_layers(self) -> list[tuple[str, Layer]]:
        layers: list[tuple[str, Layer]] = [("national", layer) for layer in self.national]
        for code, regional in self.regional.items():
            layers.extend((f"regional:{code}", layer) for layer in regional)
        layers.extend(("local", layer) for layer in self.local)
        layers.extend(("contributions", layer) for layer in self.contributions)
        return layers

    def ordered_layers(self, region: str | None) -> list[tuple[str, Layer]]:
        """Layers in evaluation order for one region.

        1. contribution/levy layers that reduce taxable income (income-based);
        2. national, regional and local income layers on income;
        3. surtaxes (layer_tax base) in declaration order: national, regional, local;
        4. the remaining contribution and levy layers (income, then layer_tax).
        """
        regional = self.regional.get(region, []) if region else []
        income_layers = [*self.national, *regional, *self.local]
        reducing = [c for c in self.contributions if c.reduces_taxable_income]
        others = [c for c in self.contributions if not c.reduces_taxable_income]
        ordered: list[tuple[str, Layer]] = [("pre", layer) for layer in reducing]
        ordered += [("income", layer) for layer in income_layers if layer.base == "income"]
        ordered += [("surtax", layer) for layer in income_layers if layer.base == "layer_tax"]
        ordered += [("contribution", layer) for layer in others if layer.base == "income"]
        ordered += [("contribution", layer) for layer in others if layer.base == "layer_tax"]
        return ordered

    def rule_ids(self) -> list[str]:
        """Every custom tax rule the spec uses, in a stable order (no duplicates)."""
        refs: list[str] = [rule.id for rule in self.custom_rules]
        modes: list[str | None] = [
            self.dividends.qualified.mode,
            self.dividends.other.mode,
            self.interest.mode,
        ]
        if self.wealth_tax is not None:
            modes += [self.wealth_tax.base, self.wealth_tax.combined_cap]
        for mode in modes:
            if mode and mode.startswith("rule:"):
                refs.append(mode.removeprefix("rule:"))
        return list(dict.fromkeys(refs))

    def rule_params(self, rule_id: str) -> dict[str, Any]:
        for rule in self.custom_rules:
            if rule.id == rule_id:
                return dict(rule.params)
        return {}

    def factor(self, group: str | None, inflation_factor: float) -> float:
        setting = self.meta.indexing.get(group, self.meta.default_indexing) if group else (
            self.meta.default_indexing
        )
        if setting == "none":
            return 1.0
        if not math.isfinite(inflation_factor) or inflation_factor <= 0:
            return 1.0
        return inflation_factor

    def source_ids(self) -> list[str]:
        """Every `source` id set anywhere in the spec (for the data integrity test)."""
        found: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, BaseModel):
                source = getattr(value, "source", None)
                if source:
                    found.append(source)
                for name in type(value).model_fields:
                    walk(getattr(value, name))
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(self)
        return found
