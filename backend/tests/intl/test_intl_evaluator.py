"""Generic evaluator features, exercised through custom (`XX`) regimes.

Expected values are worked by hand in each test from the spec it builds.
"""
from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from coastmath.engine.intl.evaluator import evaluate, marginal_rate
from coastmath.engine.intl.spec import TransactionTaxSpec, WealthTaxSpec
from coastmath.engine.intl.types import (
    RegimeOverrides,
    RegimeYearInputs,
    TradeInputs,
    WealthBalances,
    WealthInputs,
)
from tests.intl.helpers import brackets, flat_brackets, inputs, layer, make_spec, person


def amounts(result, code):
    return [line.amount for line in result.lines if line.code == code]


# ---------------------------------------------------------------------------
# Brackets, allowances, credits, caps
# ---------------------------------------------------------------------------


def test_progressive_brackets_and_allowance():
    spec = make_spec(
        national=[layer(brackets=brackets((0, 0.1), (10_000, 0.2), (50_000, 0.4)), allowance={"amount": 5_000})]
    )
    result = evaluate(inputs(spec, person(employment=65_000)))
    # taxable 60,000: 10,000*0.1 + 40,000*0.2 + 10,000*0.4 = 13,000
    assert result.income_tax == pytest.approx(13_000)
    assert result.taxable_income_by_person == {"self": 60_000}


def test_allowance_taper():
    spec = make_spec(
        national=[
            layer(
                brackets=flat_brackets(0.2),
                allowance={"amount": 12_000, "taper_start": 100_000, "taper_rate": 0.5},
            )
        ]
    )
    # 110,000: allowance 12,000 - 0.5 * 10,000 = 7,000 -> taxable 103,000
    assert evaluate(inputs(spec, person(employment=110_000))).total == pytest.approx(20_600)
    # 130,000: allowance fully tapered away
    assert evaluate(inputs(spec, person(employment=130_000))).total == pytest.approx(26_000)
    # Below the taper start the full allowance applies.
    assert evaluate(inputs(spec, person(employment=50_000))).total == pytest.approx(7_600)


def test_credit_is_amount_times_rate_and_floored_at_layer_tax():
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.15), credits=[{"amount": 10_000, "rate": 0.15}])]
    )
    # tax 3,000 - credit 1,500
    assert evaluate(inputs(spec, person(employment=20_000))).total == pytest.approx(1_500)
    # tax 750 < credit 1,500 -> floored at zero, never negative
    assert evaluate(inputs(spec, person(employment=5_000))).total == 0.0


def test_credit_taper():
    spec = make_spec(
        national=[
            layer(
                brackets=flat_brackets(0.3),
                credits=[{"amount": 1_000, "taper_start": 50_000, "taper_rate": 0.1}],
            )
        ]
    )
    # 60,000: credit 1,000 - 0.1 * 10,000 = 0
    assert evaluate(inputs(spec, person(employment=60_000))).total == pytest.approx(18_000)
    # 55,000: credit 500
    assert evaluate(inputs(spec, person(employment=55_000))).total == pytest.approx(16_000)


def test_flat_non_progressive_mode_taxes_whole_base_at_reached_rate():
    spec = make_spec(national=[layer(brackets=brackets((0, 0.0), (20_000, 0.05), (40_000, 0.1)), mode="flat")])
    assert evaluate(inputs(spec, person(employment=19_999))).total == 0.0
    assert evaluate(inputs(spec, person(employment=30_000))).total == pytest.approx(1_500)
    assert evaluate(inputs(spec, person(employment=40_000))).total == pytest.approx(4_000)


def test_base_cap_and_tax_cap():
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.1), tax_cap=3_000)],
        contributions=[
            layer(
                "levy",
                category="social_contribution",
                include={"employment": 1.0},
                brackets=flat_brackets(0.02),
                base_cap=50_000,
            )
        ],
    )
    result = evaluate(inputs(spec, person(employment=80_000)))
    assert amounts(result, "income_tax") == [pytest.approx(3_000)]
    assert amounts(result, "levy") == [pytest.approx(1_000)]
    assert result.social_contributions == pytest.approx(1_000)


def test_age_bounds_start_and_stop_a_layer():
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.0))],
        contributions=[
            layer(
                "pension_contribution",
                category="social_contribution",
                brackets=flat_brackets(0.1),
                age_min=18,
                age_max=64,
            )
        ],
    )
    assert evaluate(inputs(spec, person(age=40, employment=10_000))).total == pytest.approx(1_000)
    assert evaluate(inputs(spec, person(age=65, employment=10_000))).total == 0.0
    assert evaluate(inputs(spec, person(age=17, employment=10_000))).total == 0.0


def test_contribution_layer_that_reduces_taxable_income():
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.2))],
        contributions=[
            layer(
                "social",
                category="social_contribution",
                include={"employment": 1.0},
                brackets=flat_brackets(0.1),
                reduces_taxable_income=True,
            )
        ],
    )
    result = evaluate(inputs(spec, person(employment=100_000)))
    # social 10,000 first; income tax on 90,000
    assert [line.code for line in result.lines] == ["social", "income_tax"]
    assert amounts(result, "income_tax") == [pytest.approx(18_000)]
    assert result.taxable_income_by_person["self"] == pytest.approx(90_000)


def test_deductible_contributions_reduce_income_layers_only():
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.2))],
        contributions=[layer("levy", category="levy", brackets=flat_brackets(0.01))],
    )
    result = evaluate(inputs(spec, person(employment=50_000, deductible_contributions=10_000)))
    assert amounts(result, "income_tax") == [pytest.approx(8_000)]
    assert amounts(result, "levy") == [pytest.approx(500)]


def test_surtax_on_layer_tax():
    spec = make_spec(
        meta={"regions": [{"code": "R1", "name": "Region one"}], "default_region": "R1"},
        national=[layer(brackets=flat_brackets(0.1))],
        regional={
            "R1": [
                layer("regional_tax", category="income_regional", brackets=flat_brackets(0.05)),
                layer(
                    "regional_surtax",
                    category="income_regional",
                    base="layer_tax",
                    base_layers=["regional_tax"],
                    brackets=brackets((0, 0.0), (2_000, 0.5)),
                ),
            ]
        },
    )
    result = evaluate(inputs(spec, person(employment=100_000)))
    # regional tax 5,000; surtax 50% of 3,000
    assert amounts(result, "regional_surtax") == [pytest.approx(1_500)]
    assert result.income_tax == pytest.approx(10_000 + 5_000 + 1_500)
    assert [line.code for line in result.lines] == ["income_tax", "regional_tax", "regional_surtax"]


def test_alternative_schedule_takes_the_lower_tax():
    spec = make_spec(
        national=[
            layer(
                brackets=brackets((0, 0.1), (10_000, 0.3)),
                allowance={"amount": 10_000},
                alternative={"brackets": flat_brackets(0.15)},
            )
        ]
    )
    # 50,000: normal = 1,000 + 30,000*0.3 = 10,000; standard = 7,500
    assert evaluate(inputs(spec, person(employment=50_000))).total == pytest.approx(7_500)
    # 20,000: normal = 1,000; standard = 3,000
    assert evaluate(inputs(spec, person(employment=20_000))).total == pytest.approx(1_000)


def test_include_fraction_and_exclude():
    spec = make_spec(
        national=[
            layer(brackets=flat_brackets(0.1), exclude=["government_pension"]),
            layer("rent_tax", include={"rental": 0.5}, brackets=flat_brackets(0.2)),
        ]
    )
    result = evaluate(inputs(spec, person(employment=10_000, government_pension=5_000, rental=4_000, nontaxable=9_999)))
    assert amounts(result, "income_tax") == [pytest.approx(1_400)]  # 10,000 + 4,000
    assert amounts(result, "rent_tax") == [pytest.approx(400)]


def test_indexing_scales_thresholds_but_not_rates():
    spec = make_spec(
        meta={"default_indexing": "inflation", "indexing": {"frozen": "none"}},
        national=[
            layer(brackets=brackets((0, 0.0), (10_000, 0.2)), allowance={"amount": 0}),
            layer("frozen_tax", brackets=brackets((0, 0.0), (10_000, 0.1)), index_group="frozen"),
        ],
    )
    result = evaluate(inputs(spec, person(employment=20_000), inflation_factor=1.5))
    # indexed edge 15,000 -> 1,000; frozen edge 10,000 -> 1,000
    assert amounts(result, "income_tax") == [pytest.approx(1_000)]
    assert amounts(result, "frozen_tax") == [pytest.approx(1_000)]


# ---------------------------------------------------------------------------
# Filing units
# ---------------------------------------------------------------------------


PROGRESSIVE = brackets((0, 0.0), (20_000, 0.2), (60_000, 0.4))


def test_individual_filing_taxes_each_person_separately():
    spec = make_spec(national=[layer(brackets=PROGRESSIVE)])
    result = evaluate(inputs(spec, person("self", employment=80_000), person("spouse", employment=0)))
    assert [(line.person, line.amount) for line in result.lines] == [("self", pytest.approx(16_000))]
    assert result.taxable_income_by_person == {"self": 80_000, "spouse": 0}


def test_joint_filing_uses_one_schedule_and_couple_allowance():
    spec = make_spec(
        meta={"filing_unit": "joint"},
        national=[layer(brackets=PROGRESSIVE, allowance={"amount": 5_000})],
    )
    result = evaluate(inputs(spec, person("self", employment=80_000), person("spouse", employment=20_000)))
    # base 100,000 - 10,000 allowance = 90,000: 8,000 + 12,000
    assert [(line.person, line.amount) for line in result.lines] == [(None, pytest.approx(20_000))]
    assert result.taxable_income_by_person == {"self": pytest.approx(72_000), "spouse": pytest.approx(18_000)}

    couple = make_spec(
        meta={"filing_unit": "joint"},
        national=[
            layer(
                brackets=PROGRESSIVE,
                couple_brackets=brackets((0, 0.0), (40_000, 0.2), (120_000, 0.4)),
                allowance={"amount": 5_000, "couple_amount": 8_000},
            )
        ],
    )
    result = evaluate(inputs(couple, person("self", employment=80_000), person("spouse", employment=20_000)))
    assert result.total == pytest.approx((92_000 - 40_000) * 0.2)


def test_joint_splitting_is_twice_the_tax_on_half():
    spec = make_spec(
        meta={"filing_unit": "joint_splitting"},
        national=[layer(brackets=PROGRESSIVE, allowance={"amount": 5_000})],
    )
    result = evaluate(inputs(spec, person("self", employment=150_000), person("spouse", employment=0)))
    # half = 75,000 - 5,000 = 70,000: 8,000 + 4,000 = 12,000; x2
    assert result.total == pytest.approx(24_000)
    single = evaluate(inputs(spec, person("self", employment=150_000), filing="single"))
    # single: 145,000 -> 8,000 + 85,000 * 0.4
    assert single.total == pytest.approx(42_000)


def test_deceased_spouse_is_excluded_and_unit_becomes_individual():
    spec = make_spec(meta={"filing_unit": "joint"}, national=[layer(brackets=PROGRESSIVE)])
    result = evaluate(
        inputs(spec, person("self", employment=80_000), person("spouse", alive=False, employment=50_000))
    )
    assert [(line.person, line.amount) for line in result.lines] == [("self", pytest.approx(16_000))]
    assert "spouse" not in result.marginal_ordinary_rate_by_person


def test_contribution_layers_stay_per_person_under_joint_filing():
    spec = make_spec(
        meta={"filing_unit": "joint"},
        national=[layer(brackets=flat_brackets(0.0))],
        contributions=[layer("social", category="social_contribution", brackets=flat_brackets(0.05), base_cap=50_000)],
    )
    result = evaluate(inputs(spec, person("self", employment=80_000), person("spouse", employment=20_000)))
    assert [(line.person, line.amount) for line in result.lines] == [
        ("self", pytest.approx(2_500)),
        ("spouse", pytest.approx(1_000)),
    ]


# ---------------------------------------------------------------------------
# Capital gains and investment income
# ---------------------------------------------------------------------------


def test_capital_gains_inclusion_rate():
    spec = make_spec(national=[layer(brackets=flat_brackets(0.3))], capital_gains={"inclusion_rate": 0.5})
    assert evaluate(inputs(spec, person(capital_gains=10_000))).total == pytest.approx(1_500)


def test_capital_gains_exempt():
    spec = make_spec(national=[layer(brackets=flat_brackets(0.3))], capital_gains={"mode": "exempt"})
    assert evaluate(inputs(spec, person(employment=1_000, capital_gains=10_000))).total == pytest.approx(300)


def test_capital_gains_flat_with_allowance():
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.3))],
        capital_gains={"mode": "flat", "rate": 0.2, "allowance": 3_000},
    )
    result = evaluate(inputs(spec, person(employment=10_000, capital_gains=13_000)))
    assert amounts(result, "capital_gains") == [pytest.approx(2_000)]
    assert amounts(result, "income_tax") == [pytest.approx(3_000)]


def test_capital_gains_separate_brackets_stack_on_ordinary_income():
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.2), allowance={"amount": 10_000})],
        capital_gains={"mode": "separate_brackets", "brackets": brackets((0, 0.0), (50_000, 0.15), (100_000, 0.2))},
    )
    # ordinary taxable 40,000; gains 30,000 fill 40,000..70,000: 10,000 at 0% + 20,000 at 15%
    result = evaluate(inputs(spec, person(employment=50_000, capital_gains=30_000)))
    assert amounts(result, "capital_gains") == [pytest.approx(3_000)]

    unstacked = make_spec(
        national=[layer(brackets=flat_brackets(0.2), allowance={"amount": 10_000})],
        capital_gains={
            "mode": "separate_brackets",
            "stack_on_income": False,
            "brackets": brackets((0, 0.0), (50_000, 0.15), (100_000, 0.2)),
        },
    )
    assert amounts(evaluate(inputs(unstacked, person(employment=50_000, capital_gains=30_000))), "capital_gains") == []


def test_capital_losses_never_produce_negative_tax():
    spec = make_spec(national=[layer(brackets=flat_brackets(0.3))], capital_gains={"mode": "flat", "rate": 0.2})
    result = evaluate(inputs(spec, person(employment=10_000, capital_gains=-50_000)))
    assert result.total == pytest.approx(3_000)


def test_dividend_modes():
    base = {"national": [layer(brackets=flat_brackets(0.4))]}
    cg = {"mode": "flat", "rate": 0.25}
    ordinary = make_spec(**base, dividends={"qualified": {"mode": "ordinary"}})
    assert evaluate(inputs(ordinary, person(dividends_qualified=1_000))).total == pytest.approx(400)

    cg_rates = make_spec(**base, capital_gains=cg, dividends={"qualified": {"mode": "capital_gains_rates"}})
    result = evaluate(inputs(cg_rates, person(dividends_qualified=1_000, capital_gains=1_000)))
    assert amounts(result, "capital_gains") == [pytest.approx(500)]

    flat = make_spec(**base, dividends={"other": {"mode": "flat", "rate": 0.1, "allowance": 200}})
    result = evaluate(inputs(flat, person(dividends_other=1_000)))
    assert amounts(result, "dividends_other") == [pytest.approx(80)]
    assert amounts(result, "income_tax") == []

    separate = make_spec(
        **base, interest={"mode": "separate_brackets", "brackets": brackets((0, 0.0), (500, 0.3))}
    )
    assert amounts(evaluate(inputs(separate, person(interest=1_500))), "interest") == [pytest.approx(300)]

    exempt = make_spec(**base, interest={"mode": "exempt"})
    assert evaluate(inputs(exempt, person(interest=1_500))).total == 0.0


# ---------------------------------------------------------------------------
# Wealth and transaction taxes
# ---------------------------------------------------------------------------


def _wealth(net_worth, liquid, home=0.0, mortgage=0.0):
    return WealthBalances(
        net_worth=net_worth, liquid_net_worth=liquid, primary_home=home, primary_home_mortgage=mortgage
    )


def test_wealth_tax_household_net_worth_with_main_home_cap():
    spec = make_spec(
        wealth_tax={
            "unit": "household",
            "base": "net_worth",
            "allowance": 500_000,
            "rate": 0.01,
            "main_home_exemption_cap": 300_000,
        }
    )
    wealth = WealthInputs(household=_wealth(2_000_000, 1_200_000, home=1_000_000, mortgage=200_000))
    result = evaluate(inputs(spec, person("self"), person("spouse"), wealth=wealth))
    # 2,000,000 - min(800,000, 300,000) - 2 * 500,000 = 700,000
    assert amounts(result, "wealth_tax") == [pytest.approx(7_000)]
    assert result.wealth_tax == pytest.approx(7_000)


def test_wealth_tax_per_person_liquid_base_with_brackets():
    spec = make_spec(
        wealth_tax={
            "unit": "person",
            "base": "liquid_net_worth",
            "brackets": brackets((0, 0.0), (1_000_000, 0.01), (2_000_000, 0.02)),
            "main_home_exemption_cap": 300_000,
        }
    )
    wealth = WealthInputs(
        household=_wealth(9_000_000, 4_000_000),
        by_person={"self": _wealth(6_000_000, 3_000_000, home=1_000_000)},
    )
    result = evaluate(inputs(spec, person("self"), person("spouse"), wealth=wealth))
    # self: liquid 3,000,000 (home exemption ignored) -> 10,000 + 20,000
    # spouse: no split given -> household / 2 = 2,000,000 -> 10,000
    assert [(line.person, line.amount) for line in result.lines] == [
        ("self", pytest.approx(30_000)),
        ("spouse", pytest.approx(10_000)),
    ]


def test_wealth_override_replaces_pack_section():
    spec = make_spec(wealth_tax={"rate": 0.01})
    wealth = WealthInputs(household=_wealth(1_000_000, 1_000_000))
    override = RegimeOverrides(wealth_tax=WealthTaxSpec(enabled=False))
    assert evaluate(inputs(spec, person(), wealth=wealth)).total == pytest.approx(10_000)
    assert evaluate(inputs(spec, person(), wealth=wealth, overrides=override)).total == 0.0


def test_transaction_tax_sides_and_categories():
    trades = TradeInputs(purchases={"taxable": 10_000, "tax_free": 5_000}, sales={"taxable": 4_000})
    both = make_spec(transaction_tax={"rate": 0.001, "applies_to": "both"})
    assert evaluate(inputs(both, person(), trades=trades)).transaction_tax == pytest.approx(14)
    buy = make_spec(transaction_tax={"rate": 0.001, "applies_to": "buy", "account_categories": ["taxable", "tax_free"]})
    assert evaluate(inputs(buy, person(), trades=trades)).transaction_tax == pytest.approx(15)
    sell = make_spec(transaction_tax={"rate": 0.002, "applies_to": "sell"})
    override = RegimeOverrides(transaction_tax=TransactionTaxSpec(rate=0.01, applies_to="sell"))
    assert evaluate(inputs(sell, person(), trades=trades)).transaction_tax == pytest.approx(8)
    assert evaluate(inputs(sell, person(), trades=trades, overrides=override)).transaction_tax == pytest.approx(40)


# ---------------------------------------------------------------------------
# Marginal rates, determinism, validation
# ---------------------------------------------------------------------------


def test_marginal_rate_at_and_around_bracket_edges():
    spec = make_spec(national=[layer(brackets=brackets((0, 0.1), (50_000, 0.3)))])
    at_edge = inputs(spec, person(employment=50_000))
    assert marginal_rate(at_edge, "self", "employment") == pytest.approx(0.3)
    below = inputs(spec, person(employment=49_000))
    assert marginal_rate(below, "self", "employment") == pytest.approx(0.1)
    # Straddling the edge blends the two rates.
    assert marginal_rate(inputs(spec, person(employment=49_500)), "self", "employment") == pytest.approx(0.2)
    assert marginal_rate(below, "self", "employment", delta=1.0) == pytest.approx(0.1)


def test_marginal_rate_never_nan():
    spec = make_spec(national=[layer(brackets=flat_brackets(0.2))])
    data = inputs(spec, person(employment=10_000))
    for delta in (0.0, -5.0, math.nan, math.inf):
        assert marginal_rate(data, "self", "employment", delta=delta) == 0.0
    assert marginal_rate(data, "spouse", "employment") == 0.0
    assert marginal_rate(data, "self", "nontaxable") == 0.0


def test_marginal_ordinary_rate_by_person_combines_layers():
    spec = make_spec(
        national=[layer(brackets=flat_brackets(0.2))],
        contributions=[layer("health", category="levy", brackets=flat_brackets(0.02))],
    )
    result = evaluate(inputs(spec, person("self", employment=10_000), person("spouse")))
    assert result.marginal_ordinary_rate_by_person == {
        "self": pytest.approx(0.22),
        "spouse": pytest.approx(0.22),
    }


def test_evaluation_is_deterministic():
    spec = make_spec(
        national=[layer(brackets=PROGRESSIVE)],
        contributions=[layer("social", category="social_contribution", brackets=flat_brackets(0.05))],
        capital_gains={"mode": "flat", "rate": 0.2},
        transaction_tax={"rate": 0.001},
    )
    data = inputs(
        spec,
        person("self", employment=80_000, capital_gains=5_000),
        person("spouse", employment=30_000),
        trades=TradeInputs(purchases={"taxable": 1_000}),
    )
    first, second = evaluate(data), evaluate(data)
    assert first == second
    assert [line.code for line in first.lines] == [
        "income_tax",
        "income_tax",
        "social",
        "social",
        "capital_gains",
        "transaction_tax",
    ]


def test_non_finite_income_is_rejected():
    spec = make_spec(national=[layer()])
    with pytest.raises(ValueError):
        evaluate(inputs(spec, person(employment=math.nan)))
    with pytest.raises(ValueError):
        evaluate(inputs(spec, person(bonus=1.0)))


@pytest.mark.parametrize(
    "bad",
    [
        [{"lower": 0, "upper": 10, "rate": 0.1}, {"lower": 11, "upper": None, "rate": 0.2}],
        [{"lower": 5, "upper": None, "rate": 0.1}],
        [{"lower": 0, "upper": 10, "rate": 0.1}],
        [{"lower": 0, "upper": None, "rate": 1.5}],
        [{"lower": 0, "upper": 10, "rate": 0.1}, {"lower": 10, "upper": 5, "rate": 0.2}, {"lower": 5, "upper": None, "rate": 0.2}],
    ],
)
def test_bracket_validation(bad):
    with pytest.raises(ValidationError):
        make_spec(national=[layer(brackets=bad)])


def test_spec_validation_rejects_bad_references():
    with pytest.raises(ValidationError):
        make_spec(national=[layer(unknown_key=1)])
    with pytest.raises(ValidationError):
        make_spec(regional={"ZZ": [layer("r", category="income_regional")]})
    with pytest.raises(ValidationError):
        make_spec(national=[layer("surtax", base="layer_tax", base_layers=["missing"])])
    with pytest.raises(ValidationError):
        make_spec(dividends={"qualified": {"mode": "rule:ZZ:missing_rule"}})
    with pytest.raises(ValidationError):
        make_spec(national=[layer(brackets=[{"lower": 0, "upper": None, "rate": math.inf}])])
    with pytest.raises(ValidationError):
        make_spec(national=[layer(), layer()])
    with pytest.raises(ValidationError):
        make_spec(benefit_rules=["ZZ:missing"])


def test_region_resolution():
    spec = make_spec(
        meta={"regions": [{"code": "A", "name": "A"}, {"code": "B", "name": "B"}]},
        national=[layer(brackets=flat_brackets(0.1))],
        regional={"B": [layer("b_tax", category="income_regional", brackets=flat_brackets(0.05))]},
    )
    assert evaluate(inputs(spec, person(employment=1_000), region="A")).total == pytest.approx(100)
    assert evaluate(inputs(spec, person(employment=1_000), region="B")).total == pytest.approx(150)
    with pytest.raises(ValueError):
        evaluate(inputs(spec, person(employment=1_000)))
    with pytest.raises(ValueError):
        evaluate(inputs(spec, person(employment=1_000), region="C"))


def test_custom_country_requires_spec():
    with pytest.raises(ValueError):
        evaluate(RegimeYearInputs(country="XX", year=2026, people=(person(),)))


def test_plain_dict_inputs_are_coerced():
    """Integration passes balances and overrides as plain dicts from `intl_settings`."""
    spec = make_spec(wealth_tax={"rate": 0.01}, transaction_tax={"rate": 0.001})
    data = inputs(
        spec,
        person(),
        wealth=WealthInputs(household={"net_worth": 1_000_000, "liquid_net_worth": 400_000}),
        trades={"purchases": {"taxable": 1_000}, "sales": {}},
        overrides={"wealth_tax": {"base": "liquid_net_worth", "rate": 0.02}, "transaction_tax": None},
    )
    result = evaluate(data)
    assert result.wealth_tax == pytest.approx(8_000)
    assert result.transaction_tax == pytest.approx(1)
    with pytest.raises(ValidationError):
        inputs(spec, person(), overrides={"wealth_tax": {"rate": 2.0}})
