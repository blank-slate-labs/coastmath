"""Registration and discovery of pack rule modules.

A pack adds Python behavior by dropping a module into `coastmath/engine/intl/rules/`.
Nothing central lists these modules: `discover()` imports every module in that
package once. A module registers rules in either of two ways:

- decorators: `@register_tax_rule("QZ:dividend_credit", phase="after_income_tax")`,
  `@register_benefit_rule` on a class (or instance) and `@register_estate_rule`;
- module attributes, read after import: `TAX_RULES` (a list of `TaxRule`),
  `BENEFIT_RULES` (a list of `BenefitRule` instances or classes) and
  `ESTATE_RULES` (a list of `EstateRule` instances or classes).

`discover()` runs only from a lookup, never while a module is loading, so a rule module
may import the registry or evaluator at its top without forming an import cycle.
"""
from __future__ import annotations

import importlib
import pkgutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from coastmath.engine.intl.types import (
    BenefitRule,
    EstateRule,
    IncomeType,
    Person,
    TaxLine,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from coastmath.engine.intl.spec import RegimeSpec
    from coastmath.engine.intl.types import RegimeYearInputs

RulePhase = Literal["income", "after_income_tax", "after_investment", "final"]
RULE_PHASES: tuple[str, ...] = ("income", "after_income_tax", "after_investment", "final")


@dataclass(frozen=True, slots=True)
class RuleContext:
    """What a custom tax rule sees.

    `lines` is the partial result so far (in evaluation order).
    `income_by_person` is each living person's income after earlier income-phase
    adjustments. `factor(group)` returns the indexing multiplier for an index group.
    """

    inputs: RegimeYearInputs
    spec: RegimeSpec
    params: dict[str, Any]
    lines: tuple[TaxLine, ...]
    income_by_person: dict[Person, dict[str, float]]
    region: str | None
    factor: Callable[[str | None], float]

    def person_lines(self, person: Person, categories: set[str] | frozenset[str]) -> float:
        return sum(
            line.amount for line in self.lines if line.person == person and line.category in categories
        )


@dataclass(frozen=True, slots=True)
class RuleOutput:
    """A rule's contribution.

    - `lines` are appended to the result.
    - `replace` maps `code` (every person) or `code@person` to a replacement line
      that takes the first match's position; other matches are removed, and a
      None replacement removes them all.
    - `income_adjustments` (income phase only) adds amounts to a person's income
      types before the income layers run. Amounts may be negative.
    - `taxable_income` reports a person's ordinary taxable income when the rule
      computes income tax itself; it replaces the figure the layers recorded.
    """

    lines: tuple[TaxLine, ...] = ()
    replace: dict[str, TaxLine | None] = field(default_factory=dict)
    income_adjustments: dict[str, dict[str, float]] = field(default_factory=dict)
    taxable_income: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaxRule:
    id: str
    phase: RulePhase
    fn: Callable[[RuleContext], RuleOutput]
    # Income types whose generic treatment this rule takes over when a mode
    # references it (informational; the spec's mode decides exclusion).
    handles: tuple[IncomeType, ...] = ()


_TAX_RULES: dict[str, TaxRule] = {}
_BENEFIT_RULES: dict[str, BenefitRule] = {}
_ESTATE_RULES: dict[str, EstateRule] = {}
_lock = threading.RLock()
# Set once every rule module has been imported.
_discovered = threading.Event()


def register_tax_rule(
    rule_id: str, *, phase: RulePhase, handles: tuple[IncomeType, ...] = ()
) -> Callable[[Callable[[RuleContext], RuleOutput]], Callable[[RuleContext], RuleOutput]]:
    if phase not in RULE_PHASES:
        raise ValueError(f"unknown rule phase {phase!r}")

    def decorator(fn: Callable[[RuleContext], RuleOutput]) -> Callable[[RuleContext], RuleOutput]:
        add_tax_rule(TaxRule(id=rule_id, phase=phase, fn=fn, handles=handles))
        return fn

    return decorator


def add_tax_rule(rule: TaxRule) -> None:
    existing = _TAX_RULES.get(rule.id)
    if existing is not None and existing.fn is not rule.fn:
        raise ValueError(f"tax rule {rule.id!r} is registered twice")
    if rule.phase not in RULE_PHASES:
        raise ValueError(f"unknown rule phase {rule.phase!r}")
    _TAX_RULES[rule.id] = rule


def remove_tax_rule(rule_id: str) -> None:
    """Unregister a rule. Intended for tests that register temporary rules."""
    _TAX_RULES.pop(rule_id, None)


def _instance(obj: Any) -> Any:
    return obj() if isinstance(obj, type) else obj


def register_benefit_rule(obj: Any) -> Any:
    rule = _instance(obj)
    if not isinstance(rule, BenefitRule):
        raise TypeError(f"{obj!r} does not implement BenefitRule")
    existing = _BENEFIT_RULES.get(rule.id)
    if existing is not None and type(existing) is not type(rule):
        raise ValueError(f"benefit rule {rule.id!r} is registered twice")
    _BENEFIT_RULES[rule.id] = rule
    return obj


def register_estate_rule(obj: Any) -> Any:
    rule = _instance(obj)
    if not isinstance(rule, EstateRule):
        raise TypeError(f"{obj!r} does not implement EstateRule")
    existing = _ESTATE_RULES.get(rule.country)
    if existing is not None and type(existing) is not type(rule):
        raise ValueError(f"estate rule for {rule.country!r} is registered twice")
    _ESTATE_RULES[rule.country] = rule
    return obj


def discover() -> None:
    """Import every module in `coastmath.engine.intl.rules` once."""
    if _discovered.is_set():
        return
    with _lock:
        if _discovered.is_set():
            return
        package = importlib.import_module("coastmath.engine.intl.rules")
        for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
            if info.name.startswith("_"):
                continue
            module = importlib.import_module(f"{package.__name__}.{info.name}")
            for rule in getattr(module, "TAX_RULES", ()):
                add_tax_rule(rule)
            for rule in getattr(module, "BENEFIT_RULES", ()):
                register_benefit_rule(rule)
            for rule in getattr(module, "ESTATE_RULES", ()):
                register_estate_rule(rule)
        _discovered.set()


def tax_rule(rule_id: str) -> TaxRule | None:
    discover()
    return _TAX_RULES.get(rule_id)


def benefit_rules() -> dict[str, BenefitRule]:
    discover()
    return dict(_BENEFIT_RULES)


def estate_rules() -> dict[str, EstateRule]:
    discover()
    return dict(_ESTATE_RULES)
