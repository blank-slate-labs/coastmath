"""Registry metadata, rule registration and the benefit/estate protocols."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from coastmath.engine.intl import plugins, registry
from coastmath.engine.intl.evaluator import evaluate
from coastmath.engine.intl.plugins import RuleContext, RuleOutput
from coastmath.engine.intl.spec import AccountKindSpec, MinimumWithdrawal
from coastmath.engine.intl.types import (
    BenefitContext,
    BenefitRule,
    BenefitYear,
    EstateInputs,
    EstateRule,
    IncomeType,
    TaxLine,
    WealthBalances,
)
from tests.intl.helpers import flat_brackets, inputs, layer, make_spec, person

TEST_RULE = "ZZ:test_surcharge"
TEST_INCOME_RULE = "ZZ:test_income_shift"


@pytest.fixture
def registered_rules():
    """Register test-only rules; production data never references them."""

    @plugins.register_tax_rule(TEST_RULE, phase="final")
    def surcharge(ctx: RuleContext) -> RuleOutput:
        rate = float(ctx.params.get("rate", 0.0))
        lines = []
        for line in ctx.lines:
            if line.code == "income_tax":
                lines.append(TaxLine("surcharge", "Surcharge", "levy", line.person, line.amount * rate))
        replace = {"income_tax@self": TaxLine("income_tax", "Income tax (replaced)", "income_national", "self", 1.0)}
        return RuleOutput(lines=tuple(lines), replace=replace if ctx.params.get("replace") else {})

    @plugins.register_tax_rule(TEST_INCOME_RULE, phase="income")
    def shift(ctx: RuleContext) -> RuleOutput:
        return RuleOutput(income_adjustments={"self": {IncomeType.EMPLOYMENT: 1_000.0}})

    yield
    plugins.remove_tax_rule(TEST_RULE)
    plugins.remove_tax_rule(TEST_INCOME_RULE)


def test_only_the_custom_regime_ships():
    assert [country.code for country in registry.list_countries()] == ["XX"]
    assert registry.get_country("NZ") is None


def test_list_countries_includes_packs_and_custom_but_not_us(fixture_pack):
    codes = [country.code for country in registry.list_countries()]
    assert codes == [fixture_pack, "XX"]
    assert "US" not in codes


def test_country_metadata_shape(fixture_pack):
    pack = registry.get_country(fixture_pack.lower())
    assert pack is not None
    data = pack.to_dict()
    assert data["name"] == "Fixture country"
    assert data["currency"] == "EUR"
    assert data["filing_unit"] == "individual"
    assert data["spec_years"] == [2026, 2027]
    assert data["regions"] == [{"code": "N", "name": "North"}, {"code": "S", "name": "South"}]
    assert data["default_region"] == "N"
    assert [kind["id"] for kind in data["account_kinds"]][:3] == ["QZ:pension_saver", "QZ:free_saver", "QZ:general"]
    assert [rule["id"] for rule in data["benefit_rules"]] == ["QZ:basic_pension"]
    assert "monthly_amount" in data["benefit_rules"][0]["params_schema"]["properties"]
    assert data["approximations"] == ["Test-only pack: every figure is invented."]
    custom = registry.get_country("XX")
    assert custom is not None and custom.custom and custom.currency is None
    assert registry.get_country("US") is None
    assert registry.get_country("QQ") is None


def test_load_spec_picks_latest_year_not_after_request(fixture_pack):
    spec_2026 = registry.load_spec(fixture_pack, 2026)
    spec_2027 = registry.load_spec(fixture_pack, 2027)
    assert spec_2026.meta.base_year == 2026 and spec_2027.meta.base_year == 2027
    assert registry.load_spec(fixture_pack, 2031) is spec_2027
    assert registry.load_spec(fixture_pack, 2001) is spec_2026  # falls back to the earliest
    with pytest.raises(KeyError):
        registry.load_spec("QQ", 2026)
    with pytest.raises(KeyError):
        registry.load_spec("XX", 2026)


def test_custom_rule_runs_at_its_phase_with_params(registered_rules):
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.1))],
        custom_rules=[{"id": TEST_RULE, "params": {"rate": 0.5}}],
    )
    result = evaluate(inputs(spec, person(employment=10_000)))
    assert [(line.code, line.amount) for line in result.lines] == [
        ("income_tax", pytest.approx(1_000)),
        ("surcharge", pytest.approx(500)),
    ]
    assert result.social_contributions == pytest.approx(500)


def test_custom_rule_replacement_and_income_adjustment(registered_rules):
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.1))],
        custom_rules=[{"id": TEST_INCOME_RULE}, {"id": TEST_RULE, "params": {"rate": 0.0, "replace": True}}],
    )
    result = evaluate(inputs(spec, person("self", employment=10_000), person("spouse", employment=10_000)))
    lines = [(line.code, line.person, line.amount) for line in result.lines]
    assert ("income_tax", "self", 1.0) in lines  # replaced
    assert ("income_tax", "spouse", pytest.approx(1_000)) in lines  # untouched
    assert lines[0][0] == "income_tax" and lines[0][1] == "self"  # keeps position


def test_income_adjustment_outside_income_phase_is_rejected():
    @plugins.register_tax_rule("ZZ:test_bad_phase", phase="final")
    def bad(ctx: RuleContext) -> RuleOutput:
        return RuleOutput(income_adjustments={"self": {"employment": 1.0}})

    try:
        spec = make_spec(custom_rules=[{"id": "ZZ:test_bad_phase"}])
        with pytest.raises(ValueError):
            evaluate(inputs(spec, person(employment=1.0)))
    finally:
        plugins.remove_tax_rule("ZZ:test_bad_phase")


def test_income_rule_adjusts_income_before_layers(registered_rules):
    spec = make_spec(national=[layer(brackets=flat_brackets(0.1))], custom_rules=[{"id": TEST_INCOME_RULE}])
    assert evaluate(inputs(spec, person(employment=10_000))).total == pytest.approx(1_100)


def test_duplicate_rule_registration_is_rejected(registered_rules):
    with pytest.raises(ValueError):

        @plugins.register_tax_rule(TEST_RULE, phase="final")
        def other(ctx: RuleContext) -> RuleOutput:  # pragma: no cover - never runs
            return RuleOutput()


def test_unknown_phase_is_rejected():
    with pytest.raises(ValueError):
        plugins.register_tax_rule("ZZ:test_phase", phase="sometime")  # type: ignore[arg-type]


class _Params(BaseModel):
    monthly: float = 100.0


class _TestBenefit:
    id = "ZZ:test_benefit"
    label = "Test benefit"
    params_model = _Params

    def annual_amount(self, ctx: BenefitContext) -> BenefitYear:
        if ctx.start_age is None or ctx.age < ctx.start_age:
            return BenefitYear(0.0)
        return BenefitYear(ctx.params.monthly * 12 * ctx.inflation_factor)


class _TestEstate:
    country = "ZZ"

    def estate_tax(self, inputs: EstateInputs) -> float:
        return 0.0 if inputs.surviving_spouse else max(0.0, inputs.gross_estate - 1_000_000) * 0.1


def test_benefit_and_estate_protocols_and_registration():
    benefit = _TestBenefit()
    assert isinstance(benefit, BenefitRule)
    assert isinstance(_TestEstate(), EstateRule)
    plugins.register_benefit_rule(_TestBenefit)
    plugins.register_estate_rule(_TestEstate)
    try:
        rule = registry.benefit_rule("ZZ:test_benefit")
        ctx = BenefitContext(
            year=2030,
            owner="spouse",
            age=66,
            birth_year=1964,
            birth_month=5,
            start_age=65,
            params=rule.params_model(monthly=500.0),
            inflation_factor=1.1,
            prior_year=None,
            filing="single",
        )
        assert rule.annual_amount(ctx).amount == pytest.approx(6_600)
        assert rule.annual_amount(ctx).income_type == IncomeType.GOVERNMENT_PENSION
        estate = registry.estate_rule("zz")
        assert estate is not None
        decedent = EstateInputs(
            country="ZZ",
            year=2040,
            decedent="self",
            age=88,
            gross_estate=3_000_000,
            wealth={"net_worth": 3_000_000, "taxable": 3_000_000},
        )
        assert decedent.wealth == WealthBalances(net_worth=3_000_000, taxable=3_000_000)
        assert estate.estate_tax(decedent) == pytest.approx(200_000)
        assert registry.estate_rule("QQ") is None
        with pytest.raises(TypeError):
            plugins.register_benefit_rule(object())
    finally:
        plugins._BENEFIT_RULES.pop("ZZ:test_benefit", None)
        plugins._ESTATE_RULES.pop("ZZ", None)
    with pytest.raises(KeyError):
        registry.benefit_rule("ZZ:test_benefit")


def test_account_kind_spec_semantics():
    kind = AccountKindSpec.model_validate(
        {
            "id": "payout",
            "label": "Retirement income fund",
            "category": "tax_deferred",
            "minimum_withdrawal": {"start_age": 71, "rates_by_age": {"71": 0.0528, "72": 0.054, "95": 0.2}},
        }
    )
    assert kind.withdrawal_is_taxable
    assert kind.minimum_withdrawal.rate_for_age(70) == 0.0
    assert kind.minimum_withdrawal.rate_for_age(80) == pytest.approx(0.054)
    assert kind.minimum_withdrawal.rate_for_age(99) == pytest.approx(0.2)
    tax_free = AccountKindSpec(id="tax_free", label="Tax-free", category="tax_free")
    assert not tax_free.withdrawal_is_taxable
    with pytest.raises(ValidationError):
        MinimumWithdrawal(start_age=71, rates_by_age={})
    with pytest.raises(ValidationError):
        make_spec(account_kinds=[{"id": "a", "label": "A", "category": "taxable", "converts_to": {"kind_id": "b", "age": 71}}])
    with pytest.raises(ValidationError):
        AccountKindSpec(id="x", label="X", category="taxable", surprise=True)  # type: ignore[call-arg]
