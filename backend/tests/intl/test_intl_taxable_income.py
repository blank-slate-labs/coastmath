"""Taxable income is reported for every person, including when an age-gated national
schedule or a custom income tax rule computes the tax."""
from __future__ import annotations

import pytest

from coastmath.engine.intl import plugins
from coastmath.engine.intl.evaluator import evaluate
from coastmath.engine.intl.plugins import RuleContext, RuleOutput
from coastmath.engine.intl.types import PersonYear, TaxLine
from tests.intl.helpers import flat_brackets, inputs, layer, make_spec

INCOME_RULE = "QQ:test_income_tax"


@pytest.fixture
def income_tax_rule():
    """A rule that computes income tax itself: 25% of income above 10,000 per person."""

    @plugins.register_tax_rule(INCOME_RULE, phase="after_income_tax")
    def income_tax(ctx: RuleContext) -> RuleOutput:
        lines, taxable = [], {}
        for person in ctx.inputs.people:
            amount = max(0.0, sum(ctx.income_by_person[person.person].values()) - 10_000)
            taxable[person.person] = amount
            lines.append(TaxLine("rule_income_tax", "Income tax", "income_national", person.person, amount * 0.25))
        return RuleOutput(lines=tuple(lines), taxable_income=taxable)

    yield
    plugins.remove_tax_rule(INCOME_RULE)


def test_age_gated_schedule_reports_taxable_income_above_its_age():
    spec = make_spec(national=[
        layer("under_67", age_max=66, brackets=flat_brackets(0.3)),
        layer("from_67", age_min=67, brackets=flat_brackets(0.2)),
    ])
    younger = evaluate(inputs(spec, PersonYear("self", 60, income={"pension": 40_000})))
    older = evaluate(inputs(spec, PersonYear("self", 70, income={"pension": 40_000})))
    assert younger.taxable_income_by_person["self"] == pytest.approx(40_000)
    assert older.taxable_income_by_person["self"] == pytest.approx(40_000)
    assert older.income_tax == pytest.approx(8_000)


def test_custom_income_tax_rule_reports_its_taxable_income(income_tax_rule):
    spec = make_spec(custom_rules=[{"id": INCOME_RULE}])
    result = evaluate(inputs(spec, PersonYear("self", 45, income={"employment": 60_000})))
    assert result.taxable_income_by_person["self"] == pytest.approx(50_000)
    assert result.income_tax == pytest.approx(12_500)


def test_custom_income_tax_rule_reports_each_partner(income_tax_rule):
    spec = make_spec(custom_rules=[{"id": INCOME_RULE}])
    result = evaluate(inputs(spec, PersonYear("self", 45, income={"employment": 80_000}),
                             PersonYear("spouse", 45, income={"employment": 20_000})))
    assert result.taxable_income_by_person == pytest.approx({"self": 70_000, "spouse": 10_000})
