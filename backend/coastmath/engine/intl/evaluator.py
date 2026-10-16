"""Evaluate one tax year under a non-US regime.

`evaluate(inputs)` is pure and deterministic: the spec is loaded (and cached) by
the registry, then nothing else is read. Lines come out in a fixed order.

Order of evaluation
-------------------
0. When the capital gains section splits gains (`cost_base_indexation`,
   `main_residence_exempt`), `capital_gains` becomes the net capital gain worked
   out from `PersonYear.capital_gain_parts` (`coastmath.engine.intl.gains`).
   Custom rules of phase `income` run first; they may adjust each person's income.
1. Contribution and levy layers marked `reduces_taxable_income`. Their tax is
   deducted from the base of every income layer for the same person.
2. Income layers (national, then the plan region's, then local) on income:
   a. base = included income - deductible contributions - step-1 amounts, capped
      at `base_cap`;
   b. allowance, with taper;
   c. brackets (progressive, or flat: the whole base at the reached bracket's rate);
   d. nonrefundable credits, floored at the layer's tax;
   e. the alternative schedule on the pre-allowance base, if lower;
   f. `tax_cap`.
3. Surtax layers (base = earlier layers' tax), same steps b-f.
4. Remaining contribution and levy layers (income-based, then surtax-based).
   Custom rules of phase `after_income_tax` run here.
5. Capital gains (`flat` / `separate_brackets`, stacked on the ordinary taxable
   income) and dividend/interest modes `flat` / `separate_brackets`.
   Custom rules of phase `after_investment` run here.
6. Wealth tax, then transaction tax. Custom rules of phase `final` run last.

Filing units
------------
- `individual`: every living person is a unit.
- `joint`: the living people form one unit with one schedule (`couple_brackets`
  and the couple allowance when the unit has two people).
- `joint_splitting`: one unit; tax = n * tax(base / n), where n is the number of
  people in the unit (2 for a couple), with the single allowance per share.
A `single` filing, or a household with one living person, is always individual.
Layers with `unit == "person"` (the default for contribution layers) are always
per person. Joint-unit tax is attributed to people by their share of the base.

Indexing: every threshold is multiplied by `spec.factor(group, inflation_factor)`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import cast

from coastmath.engine.intl import gains, plugins, registry
from coastmath.engine.intl.plugins import RuleContext, RuleOutput
from coastmath.engine.intl.spec import (
    Allowance,
    Bracket,
    InvestmentIncomeSpec,
    Layer,
    RegimeSpec,
    TransactionTaxSpec,
    WealthTaxSpec,
)
from coastmath.engine.intl.types import (
    INCOME_TYPES,
    IncomeType,
    Person,
    PersonYear,
    RegimeYearInputs,
    RegimeYearResult,
    TaxLine,
    WealthBalances,
)

MARGINAL_DELTA = 1000.0
_INVESTMENT_TYPES = (
    IncomeType.DIVIDENDS_QUALIFIED,
    IncomeType.DIVIDENDS_OTHER,
    IncomeType.INTEREST,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_spec(inputs: RegimeYearInputs) -> RegimeSpec:
    """The spec used for `inputs`, with wealth/transaction overrides applied."""
    if inputs.country.upper() == registry.CUSTOM_COUNTRY:
        if inputs.custom_spec is None:
            raise ValueError("country XX needs custom_spec")
        spec = inputs.custom_spec
    else:
        spec = registry.load_spec(inputs.country, inputs.year)
    overrides = inputs.overrides
    if overrides is not None:
        update: dict[str, object] = {}
        if overrides.wealth_tax is not None:
            update["wealth_tax"] = overrides.wealth_tax
        if overrides.transaction_tax is not None:
            update["transaction_tax"] = overrides.transaction_tax
        if update:
            spec = spec.model_copy(update=update)
    return spec


def evaluate(inputs: RegimeYearInputs) -> RegimeYearResult:
    spec = resolve_spec(inputs)
    core = _evaluate_core(inputs, spec)
    marginals: dict[str, float] = {}
    for person in inputs.people:
        if person.alive:
            bumped = _evaluate_core(
                _bump(inputs, person.person, IncomeType.RETIREMENT_WITHDRAWAL, MARGINAL_DELTA), spec
            )
            marginals[person.person] = _finite_rate(bumped.total - core.total, MARGINAL_DELTA)
    return RegimeYearResult.from_lines(core.lines, core.taxable_by_person, marginals)


def marginal_rate(
    inputs: RegimeYearInputs, person: str, income_type: str, delta: float = MARGINAL_DELTA
) -> float:
    """Forward finite difference of total tax for `delta` more of `income_type`.

    At a bracket edge this returns the rate above the edge (the rate the next unit
    of income pays). Returns 0.0 for an unknown or deceased person, a non-positive
    or non-finite delta, and never NaN.
    """
    if not math.isfinite(delta) or delta <= 0:
        return 0.0
    if not any(p.person == person and p.alive for p in inputs.people):
        return 0.0
    spec = resolve_spec(inputs)
    base = _evaluate_core(inputs, spec)
    bumped = _evaluate_core(_bump(inputs, person, income_type, delta), spec)
    return _finite_rate(bumped.total - base.total, delta)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Core:
    lines: list[TaxLine]
    taxable_by_person: dict[str, float]

    @property
    def total(self) -> float:
        return sum(line.amount for line in self.lines)


@dataclass(slots=True)
class _State:
    inputs: RegimeYearInputs
    spec: RegimeSpec
    region: str | None
    people: list[PersonYear]
    income: dict[Person, dict[str, float]]
    lines: list[TaxLine]
    # Layer id -> person -> attributed tax.
    layer_tax: dict[str, dict[str, float]]
    # Person -> amount of step-1 contributions deducted from income layers.
    reducing: dict[str, float]
    taxable_by_person: dict[str, float]
    # Unit key -> ordinary taxable income of the stack layer (for capital gains).
    stack_taxable: dict[tuple[str, ...], float]

    def factor(self, group: str | None) -> float:
        return self.spec.factor(group, self.inputs.inflation_factor)


def _finite(value: float, what: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} must be finite")
    return number


def _finite_rate(diff: float, delta: float) -> float:
    rate = diff / delta
    return rate if math.isfinite(rate) else 0.0


def _bump(inputs: RegimeYearInputs, person: str, income_type: str, delta: float) -> RegimeYearInputs:
    people = []
    for p in inputs.people:
        if p.person == person:
            income = dict(p.income)
            income[income_type] = float(income.get(income_type, 0.0) or 0.0) + delta
            p = replace(p, income=income)
        people.append(p)
    return replace(inputs, people=tuple(people))


def _resolve_region(spec: RegimeSpec, region: str | None) -> str | None:
    codes = [r.code for r in spec.meta.regions]
    if not codes:
        return None
    chosen = region or spec.meta.default_region
    if chosen is None:
        raise ValueError(f"{spec.meta.country}: a region is required ({', '.join(codes)})")
    if chosen not in codes:
        raise ValueError(f"{spec.meta.country}: unknown region {chosen!r}")
    return chosen


def _evaluate_core(inputs: RegimeYearInputs, spec: RegimeSpec) -> _Core:
    people = [p for p in inputs.people if p.alive]
    income: dict[Person, dict[str, float]] = {}
    for p in people:
        income[p.person] = {
            str(t): _finite(p.income.get(t, 0.0) or 0.0, f"{p.person} {t}") for t in INCOME_TYPES
        }
        unknown = set(map(str, p.income)) - {str(t) for t in INCOME_TYPES}
        if unknown:
            raise ValueError(f"unknown income types {sorted(unknown)}")
        _apply_gain_parts(spec, p, income[p.person])
    state = _State(
        inputs=inputs,
        spec=spec,
        region=_resolve_region(spec, inputs.region),
        people=people,
        income=income,
        lines=[],
        layer_tax={},
        reducing={p.person: 0.0 for p in people},
        taxable_by_person={p.person: 0.0 for p in people},
        stack_taxable={},
    )
    rules = _rules_by_phase(spec)

    _run_rules(state, rules["income"], allow_income=True)

    ordered = spec.ordered_layers(state.region)
    stack_id = _stack_layer_id(spec)
    for stage, layer in ordered:
        if stage == "contribution":
            continue
        _apply_layer(
            state, layer, reduces=stage == "pre", stack=layer.id == stack_id,
            records_taxable=layer.base == "income" and any(layer is n for n in spec.national),
        )
    for stage, layer in ordered:
        if stage == "contribution":
            _apply_layer(state, layer, reduces=False, stack=False)
    _run_rules(state, rules["after_income_tax"])

    _apply_capital_gains(state)
    for income_type, treatment in (
        (IncomeType.DIVIDENDS_QUALIFIED, spec.dividends.qualified),
        (IncomeType.DIVIDENDS_OTHER, spec.dividends.other),
        (IncomeType.INTEREST, spec.interest),
    ):
        _apply_investment(state, income_type, treatment)
    _run_rules(state, rules["after_investment"])

    _apply_wealth(state, spec.wealth_tax)
    _apply_transaction(state, spec.transaction_tax)
    _run_rules(state, rules["final"])

    lines = [line for line in state.lines if abs(line.amount) >= 0.005]
    return _Core(lines=lines, taxable_by_person=state.taxable_by_person)


def _apply_gain_parts(spec: RegimeSpec, person: PersonYear, income: dict[str, float]) -> None:
    """Replace `capital_gains` by the net capital gain when the spec splits gains
    (`coastmath.engine.intl.gains`); other specs use the reported gain unchanged."""
    if gains.uses_parts(spec.capital_gains):
        income[str(IncomeType.CAPITAL_GAINS)] = gains.person_net_capital_gain(spec.capital_gains, person).assessable


# ---------------------------------------------------------------------------
# Units and inclusion
# ---------------------------------------------------------------------------


def _units(state: _State, layer_unit: str) -> list[tuple[PersonYear, ...]]:
    people = state.people
    if not people:
        return []
    joint = (
        layer_unit == "filing"
        and state.spec.meta.filing_unit != "individual"
        and state.inputs.filing == "couple"
        and len(people) > 1
    )
    if joint:
        return [tuple(people)]
    return [(p,) for p in people]


def _unit_key(unit: tuple[PersonYear, ...]) -> tuple[str, ...]:
    return tuple(p.person for p in unit)


def _stack_layer_id(spec: RegimeSpec) -> str | None:
    if spec.capital_gains.stack_layer:
        return spec.capital_gains.stack_layer
    for layer in spec.national:
        if layer.base == "income":
            return layer.id
    return None


def _investment_mode(spec: RegimeSpec, income_type: str) -> str:
    if income_type == IncomeType.DIVIDENDS_QUALIFIED:
        return spec.dividends.qualified.mode
    if income_type == IncomeType.DIVIDENDS_OTHER:
        return spec.dividends.other.mode
    return spec.interest.mode


def _inclusion(spec: RegimeSpec, layer: Layer, income_type: str) -> float:
    if income_type == IncomeType.NONTAXABLE or income_type in layer.exclude:
        return 0.0
    if layer.include is not None:
        fraction = float(layer.include.get(income_type, 0.0))  # type: ignore[call-overload]
    else:
        fraction = 1.0
    if fraction == 0.0 or not layer.is_income_layer:
        return fraction
    cg_mode = spec.capital_gains.mode
    if income_type == IncomeType.CAPITAL_GAINS:
        return fraction * spec.capital_gains.inclusion_rate if cg_mode == "ordinary_inclusion" else 0.0
    if income_type in _INVESTMENT_TYPES:
        mode = _investment_mode(spec, income_type)
        if mode == "ordinary":
            return fraction
        if mode == "capital_gains_rates" and cg_mode == "ordinary_inclusion":
            return fraction
        return 0.0
    return fraction


def _eligible(layer: Layer, person: PersonYear) -> bool:
    if layer.age_min is not None and person.age < layer.age_min:
        return False
    return layer.age_max is None or person.age <= layer.age_max


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


def _bracket_tax(amount: float, brackets: list[Bracket], factor: float, mode: str = "progressive") -> float:
    if amount <= 0:
        return 0.0
    if mode == "flat":
        rate = brackets[0].rate
        for bracket in brackets:
            if amount >= bracket.lower * factor:
                rate = bracket.rate
        return amount * rate
    tax = 0.0
    for bracket in brackets:
        lower = bracket.lower * factor
        if amount <= lower:
            break
        upper = math.inf if bracket.upper is None else bracket.upper * factor
        tax += (min(amount, upper) - lower) * bracket.rate
    return tax


def _tapered(amount: float, taper_start: float | None, taper_rate: float, base: float, factor: float) -> float:
    if taper_rate <= 0 or taper_start is None:
        return amount
    return max(0.0, amount - taper_rate * max(0.0, base - taper_start * factor))


def _allowance_amount(allowance: Allowance | None, base: float, size: int, factor: float) -> float:
    if allowance is None:
        return 0.0
    if size > 1:
        amount = allowance.couple_amount if allowance.couple_amount is not None else allowance.amount * size
    else:
        amount = allowance.amount
    return _tapered(amount * factor, allowance.taper_start, allowance.taper_rate, base, factor)


def _schedule(state: _State, layer: Layer, base: float, size: int) -> tuple[float, float]:
    """Tax and taxable amount on `base` for a unit of `size` people (not split)."""
    factor = state.factor(layer.index_group)
    allowance_factor = state.factor(layer.allowance.index_group) if layer.allowance else factor
    taxable = max(0.0, base - _allowance_amount(layer.allowance, base, size, allowance_factor))
    brackets = layer.couple_brackets if size > 1 and layer.couple_brackets else layer.brackets
    tax = _bracket_tax(taxable, brackets, factor, layer.mode)
    credits = 0.0
    for credit in layer.credits:
        credit_factor = state.factor(credit.index_group)
        amount = _tapered(credit.amount * credit_factor, credit.taper_start, credit.taper_rate, base, credit_factor)
        credits += amount * credit.rate
    tax = max(0.0, tax - credits)
    if layer.alternative is not None:
        alt_factor = state.factor(layer.alternative.index_group)
        tax = min(tax, _bracket_tax(base, layer.alternative.brackets, alt_factor))
    return tax, taxable


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


def _apply_layer(
    state: _State, layer: Layer, *, reduces: bool, stack: bool, records_taxable: bool = False
) -> None:
    """Apply one layer. The stack layer sets each person's taxable income; another
    national income layer (e.g. an age-gated schedule) raises it for its members."""
    spec = state.spec
    attributed: dict[str, float] = {}
    for unit in _units(state, layer.effective_unit):
        members = [p for p in unit if _eligible(layer, p)]
        if not members:
            continue
        shares: dict[str, float] = {}
        for p in members:
            if layer.base == "income":
                amount = sum(
                    state.income[p.person][str(t)] * _inclusion(spec, layer, t) for t in INCOME_TYPES
                )
                if layer.deducts_contributions:
                    amount -= p.deductible_contributions
                if layer.is_income_layer:
                    amount -= state.reducing.get(p.person, 0.0)
            else:
                amount = sum(state.layer_tax.get(ref, {}).get(p.person, 0.0) for ref in layer.base_layers)
            shares[p.person] = amount
        base = max(0.0, sum(shares.values()))
        factor = state.factor(layer.index_group)
        if layer.base_cap is not None:
            base = min(base, layer.base_cap * factor * len(members))
        size = len(members)
        if spec.meta.filing_unit == "joint_splitting" and size > 1:
            part_tax, part_taxable = _schedule(state, layer, base / size, 1)
            tax, taxable = part_tax * size, part_taxable * size
        else:
            tax, taxable = _schedule(state, layer, base, size)
        if layer.tax_cap is not None:
            tax = min(tax, layer.tax_cap * factor * size)

        weights = _weights(shares)
        for person, weight in weights.items():
            attributed[person] = attributed.get(person, 0.0) + tax * weight
            if stack:
                state.taxable_by_person[person] = taxable * weight
            elif records_taxable:
                state.taxable_by_person[person] = max(state.taxable_by_person.get(person, 0.0), taxable * weight)
        if stack:
            state.stack_taxable[_unit_key(unit)] = taxable
        person = members[0].person if size == 1 else None
        state.lines.append(TaxLine(layer.id, layer.label, layer.category, person, tax))

    state.layer_tax[layer.id] = attributed
    if reduces:
        for person, amount in attributed.items():
            state.reducing[person] = state.reducing.get(person, 0.0) + amount


def _weights(shares: dict[str, float]) -> dict[str, float]:
    positive = {k: max(0.0, v) for k, v in shares.items()}
    total = sum(positive.values())
    if total <= 0:
        return {k: 1.0 / len(shares) for k in shares} if shares else {}
    return {k: v / total for k, v in positive.items()}


# ---------------------------------------------------------------------------
# Capital gains and investment income
# ---------------------------------------------------------------------------


def _apply_capital_gains(state: _State) -> None:
    cg = state.spec.capital_gains
    if cg.mode not in ("flat", "separate_brackets"):
        return
    factor = state.factor(cg.index_group)
    pooled_types = [IncomeType.CAPITAL_GAINS] + [
        t for t in _INVESTMENT_TYPES if _investment_mode(state.spec, t) == "capital_gains_rates"
    ]
    for unit in _units(state, "filing"):
        size = len(unit)
        gains = max(0.0, sum(state.income[p.person][str(t)] for p in unit for t in pooled_types))
        taxable = max(0.0, gains - cg.allowance * factor * size)
        if cg.mode == "flat":
            tax = taxable * (cg.rate or 0.0)
        else:
            assert cg.brackets is not None
            start = state.stack_taxable.get(_unit_key(unit), 0.0) if cg.stack_on_income else 0.0
            parts = size if state.spec.meta.filing_unit == "joint_splitting" and size > 1 else 1
            start_part, gain_part = start / parts, taxable / parts
            tax = parts * (
                _bracket_tax(start_part + gain_part, cg.brackets, factor)
                - _bracket_tax(start_part, cg.brackets, factor)
            )
        person = unit[0].person if size == 1 else None
        state.lines.append(TaxLine("capital_gains", cg.label, cg.category, person, tax))


_INVESTMENT_LABELS = {
    IncomeType.DIVIDENDS_QUALIFIED: "Dividend tax",
    IncomeType.DIVIDENDS_OTHER: "Dividend tax (other)",
    IncomeType.INTEREST: "Interest tax",
}


def _apply_investment(state: _State, income_type: IncomeType, treatment: InvestmentIncomeSpec) -> None:
    if treatment.mode not in ("flat", "separate_brackets"):
        return
    factor = state.factor(treatment.index_group)
    label = treatment.label or _INVESTMENT_LABELS[income_type]
    for unit in _units(state, "filing"):
        size = len(unit)
        amount = max(0.0, sum(state.income[p.person][str(income_type)] for p in unit))
        taxable = max(0.0, amount - treatment.allowance * factor * size)
        if treatment.mode == "flat":
            tax = taxable * (treatment.rate or 0.0)
        else:
            assert treatment.brackets is not None
            parts = size if state.spec.meta.filing_unit == "joint_splitting" and size > 1 else 1
            tax = parts * _bracket_tax(taxable / parts, treatment.brackets, factor)
        person = unit[0].person if size == 1 else None
        state.lines.append(TaxLine(str(income_type), label, treatment.category, person, tax))


# ---------------------------------------------------------------------------
# Wealth and transaction taxes
# ---------------------------------------------------------------------------


def _split(balances: WealthBalances, parts: int) -> WealthBalances:
    if parts <= 1:
        return balances
    return WealthBalances(
        **{name: getattr(balances, name) / parts for name in WealthBalances.__dataclass_fields__}
    )


def _apply_wealth(state: _State, wealth: WealthTaxSpec | None) -> None:
    inputs = state.inputs.wealth
    if wealth is None or not wealth.enabled or inputs is None or not state.people:
        return
    if wealth.base.startswith("rule:"):
        return
    factor = state.factor(wealth.index_group)
    if wealth.unit == "person":
        units = [
            ((p,), inputs.by_person.get(p.person) or _split(inputs.household, len(state.people)))
            for p in state.people
        ]
    else:
        units = [(tuple(state.people), inputs.household)]
    for unit, balances in units:
        size = len(unit)
        value = balances.net_worth if wealth.base == "net_worth" else balances.liquid_net_worth
        value = _finite(value, "net worth")
        if wealth.base == "net_worth" and wealth.main_home_exemption_cap is not None:
            equity = max(0.0, balances.primary_home - balances.primary_home_mortgage)
            value -= min(equity, wealth.main_home_exemption_cap * factor)
        if size > 1:
            allowance = wealth.couple_allowance if wealth.couple_allowance is not None else wealth.allowance * size
        else:
            allowance = wealth.allowance
        taxable = max(0.0, value - allowance * factor)
        if wealth.brackets:
            tax = _bracket_tax(taxable, wealth.brackets, factor)
        else:
            tax = taxable * (wealth.rate or 0.0)
        person = unit[0].person if size == 1 else None
        state.lines.append(TaxLine("wealth_tax", wealth.label, "wealth", person, tax))


def _apply_transaction(state: _State, transaction: TransactionTaxSpec | None) -> None:
    trades = state.inputs.trades
    if transaction is None or not transaction.enabled or trades is None:
        return
    total = 0.0
    for category in transaction.account_categories:
        if transaction.applies_to in ("buy", "both"):
            total += max(0.0, _finite(trades.purchases.get(category, 0.0), "purchases"))
        if transaction.applies_to in ("sell", "both"):
            total += max(0.0, _finite(trades.sales.get(category, 0.0), "sales"))
    state.lines.append(
        TaxLine("transaction_tax", transaction.label, "transaction", None, total * transaction.rate)
    )


# ---------------------------------------------------------------------------
# Custom rules
# ---------------------------------------------------------------------------


def _rules_by_phase(spec: RegimeSpec) -> dict[str, list[plugins.TaxRule]]:
    grouped: dict[str, list[plugins.TaxRule]] = {phase: [] for phase in plugins.RULE_PHASES}
    for rule_id in spec.rule_ids():
        rule = plugins.tax_rule(rule_id)
        if rule is None:
            raise ValueError(f"unknown custom rule {rule_id!r}")
        grouped[rule.phase].append(rule)
    return grouped


def _run_rules(state: _State, rules: list[plugins.TaxRule], *, allow_income: bool = False) -> None:
    for rule in rules:
        ctx = RuleContext(
            inputs=state.inputs,
            spec=state.spec,
            params=state.spec.rule_params(rule.id),
            lines=tuple(state.lines),
            income_by_person={person: dict(amounts) for person, amounts in state.income.items()},
            region=state.region,
            factor=state.factor,
        )
        output = rule.fn(ctx)
        if not isinstance(output, RuleOutput):
            raise TypeError(f"custom rule {rule.id} must return RuleOutput")
        if output.income_adjustments:
            if not allow_income:
                raise ValueError(f"custom rule {rule.id}: income adjustments need phase 'income'")
            for person, adjustments in output.income_adjustments.items():
                if person not in state.income:
                    continue
                # A rule may name anyone; only a living person in the year is adjusted.
                income = state.income[cast(Person, person)]
                for income_type, amount in adjustments.items():
                    key = str(IncomeType(income_type))
                    income[key] += _finite(amount, f"{rule.id} adjustment")
        for person, amount in output.taxable_income.items():
            if person in state.taxable_by_person:
                state.taxable_by_person[person] = max(0.0, _finite(amount, f"{rule.id} taxable income"))
        for key, replacement in output.replace.items():
            state.lines = _replace_lines(state.lines, key, replacement)
        for line in output.lines:
            _finite(line.amount, f"{rule.id} line")
            state.lines.append(line)


def _replace_lines(lines: list[TaxLine], key: str, replacement: TaxLine | None) -> list[TaxLine]:
    """Replace the lines matching `key` (`code`, or `code@person`).

    The replacement takes the position of the first match; other matches are
    removed. A None replacement removes every match.
    """
    code, _, person = key.partition("@")
    result: list[TaxLine] = []
    placed = False
    for line in lines:
        if line.code == code and (not person or line.person == person):
            if replacement is not None and not placed:
                result.append(replacement)
                placed = True
            continue
        result.append(line)
    return result
