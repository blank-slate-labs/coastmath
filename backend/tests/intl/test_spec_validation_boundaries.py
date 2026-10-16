"""Malformed country regime specs are rejected with the reason; valid edges load."""
from __future__ import annotations

import math
from typing import Any

import pytest
from pydantic import ValidationError

from coastmath.engine.intl.spec import (
    Allowance,
    CapitalGainsSpec,
    Credit,
    InvestmentIncomeSpec,
    Layer,
    WealthTaxSpec,
)
from tests.intl.helpers import brackets, flat_brackets, layer, make_spec


def _rejects(match: str, build) -> None:
    with pytest.raises(ValidationError, match=match):
        build()


@pytest.mark.parametrize(
    ("match", "fields"),
    [
        ("at least one bracket is required", {"brackets": []}),
        (
            "only the last bracket may be open-ended",
            {"brackets": [{"lower": 0, "upper": None, "rate": 0.1}, {"lower": 10, "upper": None, "rate": 0.2}]},
        ),
        ("a layer_tax base needs base_layers", {"base": "layer_tax"}),
        ("base_layers only applies to a layer_tax base", {"base_layers": ["other"]}),
        ("age_min exceeds age_max", {"age_min": 70, "age_max": 65}),
        ("only contribution or levy layers can reduce taxable income", {"reduces_taxable_income": True}),
    ],
)
def test_layer_shape_errors(match: str, fields: dict[str, Any]) -> None:
    _rejects(match, lambda: Layer.model_validate(layer("income_tax", **fields)))


def test_a_surtax_cannot_reduce_taxable_income() -> None:
    surtax = layer(
        "solidarity", category="levy", base="layer_tax", base_layers=["income_tax"],
        reduces_taxable_income=True,
    )
    _rejects("a surtax cannot reduce taxable income", lambda: Layer.model_validate(surtax))


@pytest.mark.parametrize("model", [Allowance, Credit])
def test_a_taper_rate_needs_a_taper_start(model) -> None:
    _rejects("taper_rate requires taper_start", lambda: model(amount=10_000, taper_rate=0.5))
    tapered = model(amount=10_000, taper_rate=0.5, taper_start=100_000)
    assert tapered.taper_start == 100_000


@pytest.mark.parametrize(
    ("match", "build"),
    [
        ("capital gains: flat mode needs rate", lambda: CapitalGainsSpec(mode="flat")),
        ("capital gains: separate_brackets mode needs brackets",
         lambda: CapitalGainsSpec(mode="separate_brackets")),
        ("flat mode needs rate", lambda: InvestmentIncomeSpec(mode="flat")),
        ("separate_brackets mode needs brackets", lambda: InvestmentIncomeSpec(mode="separate_brackets")),
        ("wealth tax: give rate or brackets", WealthTaxSpec),
        ("give rate or brackets, not both",
         lambda: WealthTaxSpec(rate=0.01, brackets=flat_brackets(0.01))),
    ],
)
def test_investment_and_wealth_sections_need_their_rates(match: str, build) -> None:
    _rejects(match, build)


def test_wealth_tax_rates_are_optional_when_disabled_or_delegated() -> None:
    assert WealthTaxSpec(enabled=False).rate is None
    assert WealthTaxSpec(base="rule:ES:wealth_tax").brackets is None


@pytest.mark.parametrize(
    ("match", "meta", "sections"),
    [
        ("duplicate region codes",
         {"regions": [{"code": "R1", "name": "One"}, {"code": "R1", "name": "Again"}]}, {}),
        ("default_region 'R2' is not a listed region",
         {"regions": [{"code": "R1", "name": "One"}], "default_region": "R2"}, {}),
        ("duplicate layer id in region 'R1'",
         {"regions": [{"code": "R1", "name": "One"}]},
         {"national": [layer("income_tax")],
          "regional": {"R1": [layer("income_tax", category="income_regional")]}}),
        ("national layer pension must use category income_national", None,
         {"national": [layer("pension", category="social_contribution")]}),
        ("regional layer county must use category income_regional",
         {"regions": [{"code": "R1", "name": "One"}]},
         {"regional": {"R1": [layer("county", category="income_local")]}}),
        ("local layer city must use category income_local", None,
         {"local": [layer("city", category="income_national")]}),
        ("contribution layer pension must use social_contribution or levy", None,
         {"contributions": [layer("pension", category="income_national")]}),
        ("capital_gains.stack_layer must be a national layer id", None,
         {"national": [layer("income_tax")],
          "capital_gains": {"mode": "separate_brackets", "brackets": flat_brackets(0.2),
                            "stack_layer": "missing"}}),
        ("duplicate account kind ids", None,
         {"account_kinds": [{"id": "pension", "label": "Pension", "category": "tax_deferred"},
                            {"id": "pension", "label": "Pension 2", "category": "tax_free"}]}),
    ],
)
def test_regime_consistency_errors(match: str, meta: dict[str, Any] | None, sections: dict[str, Any]) -> None:
    _rejects(match, lambda: make_spec(meta, **sections))


def test_capital_gains_can_stack_on_a_named_national_layer() -> None:
    spec = make_spec(
        national=[layer("income_tax", brackets=brackets((0, 0.1), (50_000, 0.3)))],
        capital_gains={"mode": "separate_brackets", "brackets": flat_brackets(0.2), "stack_layer": "income_tax"},
    )
    assert spec.capital_gains.stack_layer == "income_tax"


def test_layer_unit_override_and_unknown_rule_params() -> None:
    spec = make_spec(contributions=[layer("pension", category="social_contribution", unit="filing")])
    assert spec.contributions[0].effective_unit == "filing"
    assert spec.rule_params("XX:not_configured") == {}


@pytest.mark.parametrize("inflation_factor", [math.nan, math.inf, 0.0, -1.2])
def test_an_invalid_inflation_factor_leaves_indexed_amounts_unscaled(inflation_factor: float) -> None:
    spec = make_spec({"default_indexing": "inflation"})
    assert spec.factor(None, inflation_factor) == 1.0
    assert spec.factor(None, 1.25) == 1.25
