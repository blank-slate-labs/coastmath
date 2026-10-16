"""User tax adjustments (deductions, credits, surcharges) in the tax engine.

Expected values are worked from the engine's own unadjusted results and the
statutory identities: above-the-line deductions change AGI (IRC 62), itemized
ones only taxable income (IRC 63(d)), credits never touch payroll tax, SE tax
or NIIT, and a refundable excess is paid as cash.
"""
from dataclasses import fields

import pytest

from coastmath.engine.tax_adjustments import (
    ResolvedAdjustment,
    YearAdjustments,
    apply_credits,
    resolve_year_adjustments,
)
from coastmath.engine.tax_engine import (
    _state_tax_and_taxable_income,
    ca_behavioral_health_tax,
    calculate,
)

BASE = dict(gross_income=120_000.0, deductions=0.0, filing_status="single", tax_year=2026,
            earned_income=120_000.0, net_investment_income=0.0)


def adjust(*items: ResolvedAdjustment) -> YearAdjustments:
    return YearAdjustments(tuple(items))


def deduction(amount, deduction_type="above_the_line", scope="both"):
    return ResolvedAdjustment(id="d", name="d", kind="deduction", scope=scope,
                              deduction_type=deduction_type, amount=amount)


def credit(amount, scope="federal", refundable=False):
    return ResolvedAdjustment(id="c", name="c", kind="credit", scope=scope, refundable=refundable, amount=amount)


def surcharge(rate, base, scope="federal", cap=None):
    return ResolvedAdjustment(id="s", name="s", kind="surcharge", scope=scope, rate=rate, base=base, max_amount=cap)


def test_no_adjustments_matches_the_unadjusted_result_field_for_field():
    for kwargs in (BASE, {**BASE, "state_code": "CA"}, {**BASE, "state_code": "OH", "capital_gains": 30_000.0},
                   {**BASE, "settings": {"mode": "flat", "ordinary_income_tax_rate": .2}}):
        assert calculate(**kwargs) == calculate(**kwargs, adjustments=None)


def test_above_the_line_deduction_lowers_agi_on_both_returns():
    base = calculate(**BASE, state_code="GA")
    both = calculate(**BASE, state_code="GA", adjustments=adjust(deduction(10_000)))
    assert both.agi == pytest.approx(base.agi - 10_000)
    assert both.taxable_income == pytest.approx(base.taxable_income - 10_000)
    assert both.state < base.state
    assert both.fica_tax == base.fica_tax and both.niit == base.niit
    assert both.tax_adjustment_deductions == pytest.approx(10_000)


def test_federal_only_deduction_is_added_back_to_the_state_base_and_state_only_is_not_federal():
    base = calculate(**BASE, state_code="GA")
    federal = calculate(**BASE, state_code="GA", adjustments=adjust(deduction(10_000, scope="federal")))
    state = calculate(**BASE, state_code="GA", adjustments=adjust(deduction(10_000, scope="state")))
    both = calculate(**BASE, state_code="GA", adjustments=adjust(deduction(10_000)))
    assert federal.agi == pytest.approx(base.agi - 10_000)
    assert federal.state == pytest.approx(base.state)
    assert state.agi == pytest.approx(base.agi) and state.federal == pytest.approx(base.federal)
    assert state.state == pytest.approx(both.state)
    assert state.tax_adjustment_deductions == 0


def test_itemized_deduction_never_changes_agi_and_only_helps_above_the_standard_deduction():
    base = calculate(**BASE)
    small = calculate(**BASE, adjustments=adjust(deduction(5_000, "itemized")))
    assert small.federal == pytest.approx(base.federal)
    assert small.deduction_used == "standard" and small.tax_adjustment_deductions == 0
    large = calculate(**BASE, adjustments=adjust(deduction(base.standard_deduction + 4_000, "itemized")))
    assert large.agi == pytest.approx(base.agi)
    assert large.deduction_used == "itemized"
    assert large.taxable_income == pytest.approx(base.taxable_income - 4_000)
    assert large.tax_adjustment_deductions == pytest.approx(base.standard_deduction + 4_000)


def test_itemized_user_deduction_joins_salt_and_mortgage_categories():
    items = {"salt": 9_000.0, "property_tax": 4_000.0, "mortgage_interest": 6_000.0}
    base = calculate(**BASE, itemized_deductions=items)
    extra = calculate(**BASE, itemized_deductions=items, adjustments=adjust(deduction(3_000, "itemized")))
    assert base.deduction_used == "itemized"
    assert extra.deduction_amount == pytest.approx(base.deduction_amount + 3_000)


def test_itemized_user_deduction_is_allowed_for_amt():
    # Large preference income: only SALT (and the senior deduction) are added
    # back, so a user itemized deduction lowers AMT taxable income too.
    kwargs = dict(BASE, gross_income=600_000.0, earned_income=600_000.0,
                  itemized_deductions={"salt": 40_000.0, "mortgage_interest": 30_000.0})
    base = calculate(**kwargs)
    extra = calculate(**kwargs, adjustments=adjust(deduction(20_000, "itemized")))
    assert base.deduction_used == extra.deduction_used == "itemized"
    assert extra.amt < base.amt


def test_nonrefundable_credit_is_floored_at_income_tax_and_spares_payroll_and_niit():
    kwargs = dict(BASE, gross_income=30_000.0, earned_income=30_000.0, net_investment_income=0.0)
    base = calculate(**kwargs)
    income_tax = base.federal + base.capital_gains_tax
    result = calculate(**kwargs, adjustments=adjust(credit(income_tax + 5_000)))
    assert result.federal == 0 and result.capital_gains_tax == 0
    assert result.fica_tax == base.fica_tax and result.niit == base.niit
    assert result.total_tax == pytest.approx(base.total_tax - income_tax)
    assert result.tax_adjustment_credits == pytest.approx(income_tax)
    assert result.tax_adjustment_refund == 0


def test_refundable_credit_excess_is_netted_from_total_tax():
    kwargs = dict(BASE, gross_income=30_000.0, earned_income=30_000.0)
    base = calculate(**kwargs)
    income_tax = base.federal + base.capital_gains_tax
    result = calculate(**kwargs, adjustments=adjust(credit(income_tax + 5_000, refundable=True)))
    assert result.federal == 0
    assert result.tax_adjustment_refund == pytest.approx(5_000)
    assert result.tax_adjustment_credits == pytest.approx(income_tax + 5_000)
    assert result.total_tax == pytest.approx(base.total_tax - income_tax - 5_000)


def test_credit_order_nonrefundable_before_refundable():
    outcome = apply_credits(1_000, (credit(800), credit(500, refundable=True)))
    assert outcome.tax_after == 0 and outcome.refund == pytest.approx(300)
    assert outcome.applied == pytest.approx(1_300)
    assert apply_credits(-50, (credit(10),)).tax_after == 0


def test_credits_offset_capital_gains_tax_after_ordinary_tax():
    kwargs = dict(BASE, gross_income=20_000.0, earned_income=20_000.0, capital_gains=200_000.0)
    base = calculate(**kwargs)
    result = calculate(**kwargs, adjustments=adjust(credit(base.federal + 1_000)))
    assert result.federal == 0
    assert result.capital_gains_tax == pytest.approx(base.capital_gains_tax - 1_000)


def test_surcharges_use_their_base_and_cap_and_never_payroll():
    base = calculate(**BASE, capital_gains=10_000.0)
    ordinary = calculate(**BASE, capital_gains=10_000.0,
                         adjustments=adjust(surcharge(.01, "ordinary_taxable_income")))
    assert ordinary.federal == pytest.approx(base.federal + .01 * base.taxable_income)
    total = calculate(**BASE, capital_gains=10_000.0, adjustments=adjust(surcharge(.01, "taxable_income")))
    assert total.tax_adjustment_surcharge == pytest.approx(.01 * (base.taxable_income + 10_000))
    gains = calculate(**BASE, capital_gains=10_000.0, adjustments=adjust(surcharge(.10, "capital_gains")))
    assert gains.tax_adjustment_surcharge == pytest.approx(1_000)
    on_tax = calculate(**BASE, capital_gains=10_000.0, adjustments=adjust(surcharge(.10, "income_tax")))
    assert on_tax.tax_adjustment_surcharge == pytest.approx(.10 * (base.federal + base.capital_gains_tax))
    capped = calculate(**BASE, capital_gains=10_000.0,
                       adjustments=adjust(surcharge(.10, "income_tax", cap=500.0)))
    assert capped.tax_adjustment_surcharge == pytest.approx(500)
    for result in (ordinary, total, gains, on_tax, capped):
        assert result.fica_tax == base.fica_tax and result.niit == base.niit
        assert result.state == base.state


def test_state_credit_and_surcharge_stay_on_the_state_return():
    base = calculate(**BASE, state_code="GA")
    with_credit = calculate(**BASE, state_code="GA", adjustments=adjust(credit(500, scope="state")))
    assert with_credit.state == pytest.approx(base.state - 500)
    assert with_credit.federal == pytest.approx(base.federal)
    refund = calculate(**BASE, state_code="GA",
                       adjustments=adjust(credit(base.state + 200, scope="state", refundable=True)))
    assert refund.state == 0 and refund.tax_adjustment_refund == pytest.approx(200)
    assert refund.total_tax == pytest.approx(base.total_tax - base.state - 200)
    extra = calculate(**BASE, state_code="GA", adjustments=adjust(surcharge(.01, "taxable_income", scope="state")))
    assert extra.state > base.state and extra.federal == pytest.approx(base.federal)


def test_california_behavioral_health_tax_is_not_offset_by_state_credits():
    kwargs = dict(BASE, gross_income=1_500_000.0, earned_income=1_500_000.0, state_code="CA",
                  settings={"ca_exemption_eligible_owners": ["self"]})
    base = calculate(**kwargs)
    result = calculate(**kwargs, adjustments=adjust(credit(10_000_000, scope="state")))
    # Only the 1% tax on taxable income above $1,000,000 remains.
    taxable = _state_tax_and_taxable_income(base.modified_agi, "CA", tax_year=2026)[1]
    assert taxable > 1_000_000
    assert result.state == pytest.approx(ca_behavioral_health_tax(taxable))
    assert 0 < result.state < base.state


def test_flat_mode_applies_federal_above_the_line_deductions_credits_and_surcharges():
    settings = {"mode": "flat", "ordinary_income_tax_rate": .2, "capital_gains_tax_rate": .1}
    base = calculate(**BASE, settings=settings)
    result = calculate(**BASE, settings=settings, adjustments=adjust(
        deduction(10_000), deduction(5_000, "itemized"), credit(1_000), surcharge(.01, "ordinary_taxable_income")))
    assert result.agi == pytest.approx(base.agi - 10_000)
    taxable = base.taxable_income - 10_000
    assert result.total_tax == pytest.approx(.2 * taxable + .01 * taxable - 1_000)
    assert result.tax_adjustment_diagnostics


def test_resolution_amount_basis_frequency_and_windows():
    rows = [
        {"id": "a", "kind": "credit", "scope": "federal", "amount": 1_000, "amount_basis": "today",
         "frequency": "annual", "start_year": 2027, "end_year": 2028},
        {"id": "b", "kind": "credit", "scope": "federal", "amount": 1_000, "amount_basis": "nominal",
         "frequency": "once", "start_milestone_id": "m"},
        {"id": "c", "kind": "deduction", "deduction_type": "itemized", "scope": "federal", "amount": 100,
         "amount_basis": "nominal", "frequency": "every_n_years", "interval_years": 2, "start_year": 2026},
        {"id": "d", "kind": "deduction", "deduction_type": "above_the_line", "scope": "both", "amount": 100,
         "amount_basis": "nominal", "frequency": "annual", "end_milestone_id": "m", "owner": "spouse"},
    ]

    def ids(year, milestones=None, owners=frozenset({"self", "spouse"}), factor=1.0):
        result = resolve_year_adjustments(rows, year=year, plan_start_year=2026,
                                          milestone_years=milestones or {}, inflation_factor=factor,
                                          owners_on_return=owners)
        return {} if result is None else {item.id: item.amount for item in result.items}

    assert ids(2026) == {"c": 100, "d": 100}
    assert ids(2027, factor=1.1) == {"a": pytest.approx(1_100), "d": 100}
    assert ids(2028, {"m": 2028}) == {"a": 1_000, "b": 1_000, "c": 100, "d": 100}
    # The end milestone's year is the last year; a one-time item applies once.
    assert ids(2029, {"m": 2028}) == {}
    assert ids(2030, {"m": 2028}) == {"c": 100}
    # A spouse's own item stops once the spouse is no longer on the return.
    assert ids(2026, owners=frozenset({"self"})) == {"c": 100}


def test_unreached_or_missing_start_milestone_never_applies():
    row = {"id": "a", "kind": "credit", "scope": "federal", "amount": 1, "amount_basis": "nominal",
           "frequency": "annual", "start_milestone_id": "gone"}
    for year in range(2026, 2040):
        assert resolve_year_adjustments([row], year=year, plan_start_year=2026, milestone_years={},
                                        inflation_factor=1.0, owners_on_return=frozenset({"self"})) is None


def test_result_fields_default_to_zero():
    result = calculate(**BASE)
    names = {f.name for f in fields(result)}
    for name in ("tax_adjustment_deductions", "tax_adjustment_credits", "tax_adjustment_refund",
                 "tax_adjustment_surcharge", "state_federal_tax_subtraction"):
        assert name in names and getattr(result, name) == 0
