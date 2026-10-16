"""State subtractions of federally taxable Social Security benefits.

Each income-tax state's rule lives under ``social_security_subtraction`` in
``coastmath/data/tax_brackets_2026.json`` and is sourced state by state in the
"State Social Security treatment" section of
``_sources`` in ``tax_brackets_2026.json``. Every rule starts from the
federally taxable benefits (IRC 86) already in federal AGI. Rule ``type``:

- ``full``: subtract all federally taxable benefits.
- ``none``: the state taxes benefits as the federal return does.
- ``retirement_exclusion``: the state's subtraction is part of its
  retirement-income rule (Colorado; ``coastmath.engine.state_retirement_exclusion``),
  so nothing is subtracted here.
- ``linear_phaseout``: full below ``start`` (federal AGI, by filing status),
  none at ``start + width`` and above, proportional between. A ``width`` of 0
  is a cliff: full at or below ``start``, none above. An optional
  ``minimum_age`` limits it to people who reached that age, each person's
  share of the taxable benefits following their share of gross benefits.
- ``threshold_partial``: full below ``threshold``; at or above it the
  subtraction is the taxable benefits less the smaller of
  ``taxable_share_above`` of gross benefits or of the IRC 86(b)(1) excess.
- ``stepped_phaseout``: full at or below ``threshold``; reduced by
  ``step_reduction`` for each ``step`` of federal AGI (or part of one) above
  it. An ``alternate`` method (a maximum reduced by ``reduction_rate`` of
  provisional income above a threshold, at most the taxable benefits) applies
  when it is larger.
- ``credit_phaseout``: a nonrefundable credit of the flat state rate times the
  taxable benefits, reduced by ``credit_reduction_per_dollar`` for each dollar
  of modified AGI above ``threshold``. Without a state-credit hook in the
  engine it is modeled as the equivalent subtraction: the credit divided by
  the flat rate.

``indexed`` thresholds scale with the state inflation factor (calendar anchor
2026 = 1.0); other dollar amounts are statutory constants. With custom state
brackets only a rule marked ``applies_with_custom_brackets`` is applied, so
custom brackets keep their federal-AGI semantics.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from coastmath.engine.state_retirement_exclusion import RetirementIncome


@dataclass(frozen=True)
class SocialSecurityContext:
    """Return-level figures a state rule may key on."""

    filing_status: str
    #: Federally taxable benefits (IRC 86) included in federal AGI.
    taxable_social_security: float
    #: Gross benefits received on the return.
    social_security_income: float
    #: Federal AGI including capital gains and taxable benefits.
    federal_agi: float
    #: IRC 86(b)(2) modified AGI: AGI without benefits plus tax-exempt interest.
    modified_agi_86: float
    #: IRC 86(b)(1) excess of modified AGI plus half the benefits over the
    #: base amount (zero when below it).
    provisional_excess: float
    tax_exempt_interest: float = 0.0
    persons: Sequence[RetirementIncome] = ()
    inflation_factor: float = 1.0
    #: The flat state rate a credit rule converts with.
    state_rate: float = 0.0


def _by_status(value, filing_status: str) -> float:
    if isinstance(value, Mapping):
        return float(value.get(filing_status, value.get("default", value.get("single", 0.0))))
    return float(value)


def _qualifying_taxable(rule: Mapping, context: SocialSecurityContext) -> float:
    """Taxable benefits of the people who meet the rule's age test."""
    taxable = max(0.0, context.taxable_social_security)
    minimum_age = rule.get("minimum_age")
    if minimum_age is None:
        return taxable
    gross = context.social_security_income
    if gross <= 0:
        return 0.0
    qualifying = sum(max(0.0, person.social_security) for person in context.persons
                     if person.age is not None and person.age >= math.ceil(float(minimum_age)))
    return taxable * min(1.0, qualifying / gross)


def state_social_security_subtraction(rule: Mapping | None, context: SocialSecurityContext) -> float:
    """Return the state subtraction of federally taxable benefits for one return."""
    taxable = max(0.0, context.taxable_social_security)
    if not rule or taxable <= 0:
        return 0.0
    kind = rule["type"]
    status = context.filing_status
    factor = context.inflation_factor if rule.get("indexed") else 1.0
    agi = context.federal_agi
    if kind == "full":
        return taxable
    if kind in ("none", "retirement_exclusion"):
        return 0.0
    if kind == "linear_phaseout":
        start = _by_status(rule["start"], status) * factor
        width = float(rule.get("width", 0.0))
        if agi <= start:
            share = 1.0
        elif width <= 0:
            share = 0.0
        else:
            share = max(0.0, (start + width - agi) / width)
        return _qualifying_taxable(rule, context) * share
    if kind == "threshold_partial":
        if agi < _by_status(rule["threshold"], status) * factor:
            return taxable
        share = float(rule["taxable_share_above"])
        still_taxed = min(share * max(0.0, context.social_security_income),
                          share * max(0.0, context.provisional_excess))
        return max(0.0, taxable - still_taxed)
    if kind == "stepped_phaseout":
        threshold = _by_status(rule["threshold"], status) * factor
        # Minn. Stat. 290.0132 subd. 26(j) indexes the thresholds only.
        step = _by_status(rule["step"], status)
        steps = math.ceil(max(0.0, agi - threshold) / step) if step > 0 else 0
        simplified = taxable * max(0.0, 1.0 - float(rule["step_reduction"]) * steps)
        alternate = 0.0
        alt = rule.get("alternate")
        if alt:
            provisional = context.modified_agi_86 + 0.5 * taxable
            maximum = (_by_status(alt["maximum"], status)
                       - float(alt["reduction_rate"])
                       * max(0.0, provisional - _by_status(alt["provisional_income_threshold"], status)))
            alternate = min(taxable, max(0.0, maximum))
        return max(simplified, alternate)
    if kind == "credit_phaseout":
        if context.state_rate <= 0:
            return 0.0
        modified_agi = agi + max(0.0, context.tax_exempt_interest)
        reduction = float(rule["credit_reduction_per_dollar"]) * max(
            0.0, modified_agi - _by_status(rule["threshold"], status) * factor)
        credit = max(0.0, context.state_rate * taxable - reduction)
        return credit / context.state_rate
    raise ValueError(f"Unknown state Social Security rule type: {kind!r}")
