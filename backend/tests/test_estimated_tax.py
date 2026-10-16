"""IRC 6654 estimated tax: hand-computed rules, simulator integration and API.

Day counts used below (statutory due dates, no weekend shifts):
Apr 15 -> Jun 15 = 61 days; Jun 15 -> Sep 15 = 92; Sep 15 -> Jan 15 = 122;
Jan 15 -> Apr 15 = 90 (91 when February has 29 days). Inside these:
Jun 15 -> Jul 1 = 16 and Jul 1 -> Sep 15 = 76.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.plan import TaxSettings
from coastmath.engine import estimated_tax as et
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    PlanData,
    TaxResult,
)
from coastmath.schemas.plan_data_request import TaxSettingsRequest
from tests.corrected_fixture_support import engine_request

FLAT_8 = ((date(2000, 1, 1), .08),)


# ---------------------------------------------------------------------------
# Required annual payment, IRC 6654(d)(1)(B)-(C)
# ---------------------------------------------------------------------------

def test_ninety_percent_of_current_year_binds():
    # 90% x 10,000 = 9,000 < 100% x 20,000.
    assert et.required_annual_payment(10_000, 20_000, 100_000, "single") == pytest.approx(9_000)


def test_hundred_percent_of_prior_year_binds():
    # 100% x 20,000 = 20,000 < 90% x 30,000 = 27,000.
    assert et.required_annual_payment(30_000, 20_000, 100_000, "single") == pytest.approx(20_000)


def test_high_prior_year_agi_uses_110_percent():
    # AGI must exceed $150,000: 110% x 20,000 = 22,000 at 150,001; 100% at exactly 150,000.
    assert et.required_annual_payment(30_000, 20_000, 150_001, "married_filing_jointly") == pytest.approx(22_000)
    assert et.required_annual_payment(30_000, 20_000, 150_000, "married_filing_jointly") == pytest.approx(20_000)


def test_married_filing_separately_threshold_is_75000():
    assert et.required_annual_payment(30_000, 20_000, 80_000, "married_filing_separately") == pytest.approx(22_000)
    assert et.required_annual_payment(30_000, 20_000, 75_000, "married_filing_separately") == pytest.approx(20_000)
    assert et.required_annual_payment(30_000, 20_000, 80_000, "single") == pytest.approx(20_000)


def test_unknown_prior_year_uses_current_year_only_and_unknown_agi_is_conservative():
    assert et.required_annual_payment(30_000, None, None, "single") == pytest.approx(27_000)
    # Prior tax known, AGI unknown: the 110% share (22,000 < 27,000).
    assert et.required_annual_payment(30_000, 20_000, None, "single") == pytest.approx(22_000)


# ---------------------------------------------------------------------------
# Penalty arithmetic (required 4,000 => 1,000 per installment)
# ---------------------------------------------------------------------------

def test_penalty_when_nothing_is_paid():
    # Unpaid 1,000 / 2,000 / 3,000 / 4,000 over 61 / 92 / 122 / 90 days at 8%:
    # (61,000 + 184,000 + 366,000 + 360,000) x .08 / 365 = 77,680 / 365.
    assert et.underpayment_penalty(4_000, 0, [0, 0, 0, 0], 2026, FLAT_8) == pytest.approx(77_680 / 365)


def test_withholding_alone_satisfies_the_installments():
    # Withholding is deemed paid 1,000 on each due date (6654(g)(1)).
    assert et.underpayment_penalty(4_000, 4_000, [0, 0, 0, 0], 2026, FLAT_8) == 0
    assert et.underpayment_penalty(4_000, 6_000, [0, 0, 0, 0], 2026, FLAT_8) == 0


def test_partial_installments_apply_payments_in_due_date_order():
    # Estimates 1,000 / 0 / 2,000 / 1,000: only the second installment is
    # short, from Jun 15 until the Sep 15 payment covers it (92 days).
    assert et.underpayment_penalty(4_000, 0, [1_000, 0, 2_000, 1_000], 2026, FLAT_8) == pytest.approx(
        1_000 * 92 * .08 / 365)
    # Partial withholding plus a late catch-up: withholding 2,000 (500 each),
    # estimates 0 / 0 / 1,500 / 500. Unpaid 500 / 1,000 / 0 / 0.
    assert et.underpayment_penalty(4_000, 2_000, [0, 0, 1_500, 500], 2026, FLAT_8) == pytest.approx(
        (500 * 61 + 1_000 * 92) * .08 / 365)
    # An early overpayment carries forward to later installments.
    assert et.underpayment_penalty(4_000, 0, [4_000, 0, 0, 0], 2026, FLAT_8) == 0


def test_rate_change_mid_period():
    schedule = ((date(2026, 1, 1), .06), (date(2026, 7, 1), .09))
    # 1,000 x 61 x 6% + 2,000 x (16 x 6% + 76 x 9%) + 3,000 x 122 x 9% + 4,000 x 90 x 9%
    # = 3,660 + 15,600 + 32,940 + 32,400 = 84,600, over 365.
    assert et.underpayment_penalty(4_000, 0, [0, 0, 0, 0], 2026, schedule) == pytest.approx(84_600 / 365)


def test_leap_year_days_use_366_day_basis():
    # Tax year 2027: Sep 15 -> Jan 1, 2028 is 108 days (365 basis), then 14
    # days to Jan 15 and 91 days to Apr 15 on a 366-day basis.
    expected = .08 * (1_000 * 61 / 365 + 2_000 * 92 / 365 + 3_000 * (108 / 365 + 14 / 366) + 4_000 * 91 / 366)
    assert et.underpayment_penalty(4_000, 0, [0, 0, 0, 0], 2027, FLAT_8) == pytest.approx(expected)


def test_published_rates_by_date_and_last_rate_for_future_years():
    assert et.underpayment_rate(date(2026, 5, 1)) == .06
    assert et.underpayment_rate(date(2026, 7, 1)) == .07
    assert et.underpayment_rate(date(2035, 1, 1)) == et.RATE_SCHEDULE[-1][1]


# ---------------------------------------------------------------------------
# Which tax and which payments count, exceptions and strategies
# ---------------------------------------------------------------------------

def _year(strategy="settle_at_filing", prior=et.PriorYear(), payments=0.0, ptc=0.0, **tax):
    return et.evaluate_year(et.EstimatedTaxSettings(strategy), tax_year=2026, filing_status="single",
                            tax=TaxResult(**tax), payments=payments, ptc_reconciliation=ptc, prior=prior)


def test_payroll_tax_withheld_on_wages_is_not_an_estimated_payment():
    # Help-article example: $100,000 Texas salary, 15% withheld. The $7,650
    # payroll tax takes the first $7,650; $7,350 is federal withholding.
    year = _year(federal=13_170, fica_tax=7_650, payments=15_000, modified_agi=100_000)
    assert year.tax == pytest.approx(13_170)
    assert year.federal_withholding == pytest.approx(7_350)
    assert year.required_annual_payment == pytest.approx(11_853)  # 90% of 13,170
    # 2,963.25 required - 1,837.50 withheld = 1,125.75 short each quarter.
    short = 1_125.75
    expected = (short * 61 * .06 / 365                                  # Apr 15-Jun 15 at 6%
                + 2 * short * (16 * .06 + 76 * .07) / 365               # Jun 15-Sep 15
                + 3 * short * 122 * .07 / 365 + 4 * short * 90 * .07 / 365)
    assert year.underpayment_penalty == pytest.approx(expected)
    assert year.underpayment_penalty == pytest.approx(206.77, abs=.01)


def test_self_employment_niit_and_additional_medicare_count_state_does_not():
    year = _year(federal=9_000, capital_gains_tax=1_000, fica_tax=15_000, self_employment_tax=14_000,
                 additional_medicare_tax=500, niit=500, state=5_000)
    # 9,000 + 1,000 + 14,000 + 500 + 500 = 25,000; wage payroll tax 500 and state excluded.
    assert year.tax == pytest.approx(25_000)


def test_withholding_pool_is_shared_with_state_tax_in_proportion():
    # 8,000 withheld against 9,000 federal and 3,000 state: 8,000 x 9/12 = 6,000.
    assert _year(federal=9_000, state=3_000, payments=8_000).federal_withholding == pytest.approx(6_000)


def test_premium_credit_repayment_adds_and_net_credit_reduces_tax():
    assert _year(federal=5_000, ptc=-1_000).tax == pytest.approx(6_000)
    assert _year(federal=5_000, ptc=2_000).tax == pytest.approx(3_000)


def test_small_balance_due_exception():
    # 5,000 tax, 4,200 withheld: required 4,500 is not met, but the 800
    # balance is under $1,000 (6654(e)(1)).
    assert et.underpayment_penalty(4_500, 4_200, [0, 0, 0, 0], 2026) > 0
    year = _year(federal=5_000, payments=4_200)
    assert year.required_annual_payment == pytest.approx(4_500)
    assert year.underpayment_penalty == 0


def test_no_prior_year_liability_exception():
    year = _year(federal=40_000, prior=et.PriorYear(tax=0.0, agi=0.0))
    assert year.required_annual_payment == 0
    assert year.underpayment_penalty == 0


def test_strategies_set_estimates_and_avoid_the_penalty():
    tax = dict(federal=20_000, payments=5_000, prior=et.PriorYear(tax=16_000, agi=120_000))
    # Required: min(90% x 20,000 = 18,000, 100% x 16,000) = 16,000.
    settle = _year("settle_at_filing", **tax)
    assert settle.required_annual_payment == pytest.approx(16_000)
    assert settle.estimated_payments == 0 and settle.underpayment_penalty > 0
    safe = _year("safe_harbor", **tax)
    assert safe.estimated_payments == pytest.approx(11_000)
    assert safe.underpayment_penalty == 0
    full = _year("pay_in_full", **tax)
    assert full.estimated_payments == pytest.approx(15_000)
    assert full.underpayment_penalty == 0


def test_settings_parse_and_validate():
    assert et.parse_settings(None) is None
    assert et.parse_settings({}) is None
    assert et.parse_settings({"estimated_payments": {"strategy": "off", "prior_year_total_tax": 5}}) is None
    parsed = et.parse_settings({"estimated_payments": {"strategy": "safe_harbor", "prior_year_total_tax": 5}})
    assert parsed == et.EstimatedTaxSettings("safe_harbor", 5.0, None)
    with pytest.raises(ValueError):
        et.parse_settings({"estimated_payments": {"strategy": "quarterly"}})


@pytest.mark.parametrize("model", [TaxSettings, TaxSettingsRequest])
def test_schema_accepts_prior_year_fields_with_any_strategy(model):
    for strategy in et.STRATEGIES:
        settings = model(estimated_payments={"strategy": strategy, "prior_year_total_tax": 12_000,
                                             "prior_year_agi": 90_000})
        assert settings.estimated_payments.strategy == strategy
    for bad in ({"strategy": "quarterly"}, {"prior_year_total_tax": -1}, {"prior_year_agi": -1},
                {"strategy": "off", "extra": 1}):
        with pytest.raises(ValidationError):
            model(estimated_payments=bad)


def test_unset_strategy_is_omitted_from_saved_settings():
    assert "estimated_payments" not in TaxSettings().model_dump(mode="json")
    assert TaxSettings(estimated_payments={"strategy": "safe_harbor"}).model_dump(mode="json")[
        "estimated_payments"] == {"strategy": "safe_harbor", "prior_year_total_tax": None, "prior_year_agi": None}


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def salary_plan(estimated=None, lag=0, **changes):
    """$100,000 Texas salary, 15% withheld, $60,000 spending, zero returns."""
    settings = {"settlement_lag_years": lag}
    if estimated is not None:
        settings["estimated_payments"] = estimated
    values = dict(plan_id="00000000-0000-4000-8000-000000000001", birth_year=1980, filing_status="single",
                  life_expectancy=50, start_year=2026, state_code="TX", assumptions=AssumptionData(0, 0, 0),
                  income_streams=[IncomeData(id="pay", name="Salary", annual_amount=100_000, growth_rate=0,
                                             withholding_percent=.15)],
                  expenses=[ExpenseData(id="living", name="Living", annual_amount=60_000, inflation_linked=False)],
                  accounts={"cash": AccountInfo(balance=50_000, account_type="checking", name="Cash")},
                  drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash")], tax_settings=settings)
    values.update(changes)
    return PlanData(**values)


def retiree_plan(estimated=None, lag=0):
    """IRA-funded spending: estimates and the penalty need withdrawals that add tax."""
    settings = {"settlement_lag_years": lag}
    if estimated is not None:
        settings["estimated_payments"] = estimated
    return PlanData(plan_id="00000000-0000-4000-8000-000000000002", birth_year=1960, filing_status="single",
                    life_expectancy=69, start_year=2026, assumptions=AssumptionData(0, 0, 0),
                    expenses=[ExpenseData(id="living", name="Living", annual_amount=90_000, inflation_linked=False)],
                    accounts={"cash": AccountInfo(balance=20_000, account_type="checking", name="Cash"),
                              "ira": AccountInfo(balance=900_000, account_type="traditional_ira", name="IRA")},
                    drawdown_order=[DrawdownEntryData(rank=1, source_account_id="cash"),
                                    DrawdownEntryData(rank=2, source_account_id="ira")],
                    tax_settings=settings)


def cash_uses_balance(snapshot):
    flow = snapshot.cash_flow
    receipts = flow.gross_income + sum(d.amount for d in flow.drawdowns) + flow.tax_delta
    uses = (sum(e.amount for e in flow.expenses) + flow.tax_withheld + flow.early_withdrawal_penalty
            + sum(c.amount for c in flow.contributions) + flow.estimated_tax_payments + flow.underpayment_penalty)
    return receipts - uses


@pytest.mark.parametrize("build", [salary_plan, retiree_plan])
@pytest.mark.parametrize("lag", [0, 1])
def test_off_matches_the_existing_output_exactly(build, lag):
    baseline = run_simulation(build(lag=lag)).model_dump_json()
    for setting in ({"strategy": "off"}, {"strategy": "off", "prior_year_total_tax": 9_000, "prior_year_agi": 1}):
        assert run_simulation(build(setting, lag=lag)).model_dump_json() == baseline
    for key in ("estimated_tax_payments", "required_annual_payment", "underpayment_penalty"):
        assert key not in baseline


@pytest.mark.parametrize("build", [salary_plan, retiree_plan])
def test_safe_harbor_matches_settle_at_filing_cash_less_the_penalty(build):
    settle = run_simulation(build({"strategy": "settle_at_filing"})).yearly_snapshots[0]
    safe = run_simulation(build({"strategy": "safe_harbor"})).yearly_snapshots[0]
    off = run_simulation(build()).yearly_snapshots[0]
    penalty = settle.cash_flow.underpayment_penalty
    assert penalty > 0
    assert safe.cash_flow.underpayment_penalty == 0
    assert safe.cash_flow.estimated_tax_payments > 0
    # Same-year settlement: estimates only move tax earlier within the year.
    assert safe.net_cash_flow == pytest.approx(off.net_cash_flow, abs=.01)
    assert safe.net_worth == pytest.approx(off.net_worth, abs=.01)
    if build is salary_plan:
        # Cash-funded penalty: the difference is exactly the penalty.
        assert safe.net_cash_flow - settle.net_cash_flow == pytest.approx(penalty, abs=.01)
        assert safe.net_worth - settle.net_worth == pytest.approx(penalty, abs=.01)
        assert settle.taxes - safe.taxes == pytest.approx(penalty, abs=.01)
    else:
        # IRA-funded penalty also taxes the extra withdrawal.
        assert safe.net_worth - settle.net_worth > penalty


def test_salary_example_values():
    snap = run_simulation(salary_plan({"strategy": "safe_harbor"})).yearly_snapshots[0]
    flow = snap.cash_flow
    # Required 11,853 less 7,350 federal withholding = 4,503 of estimates;
    # 5,820 total balance less 4,503 leaves 1,317 owed at filing.
    assert flow.required_annual_payment == pytest.approx(11_853)
    assert flow.estimated_tax_payments == pytest.approx(4_503)
    assert flow.tax_delta == pytest.approx(-1_317)
    full = run_simulation(salary_plan({"strategy": "pay_in_full"})).yearly_snapshots[0].cash_flow
    assert full.estimated_tax_payments == pytest.approx(5_820)
    assert full.tax_delta == pytest.approx(0, abs=.01)


def test_later_years_use_the_simulated_prior_year():
    second = run_simulation(salary_plan({"strategy": "settle_at_filing", "prior_year_total_tax": 0})).yearly_snapshots
    # Year one: zero prior-year tax, no penalty (6654(e)(2)).
    assert second[0].cash_flow.underpayment_penalty == 0
    # Year two: min(90% x 13,170, 100% x 13,170 because 2026 AGI <= 150,000).
    assert second[1].cash_flow.required_annual_payment == pytest.approx(11_853)
    assert second[1].cash_flow.underpayment_penalty > 0


def test_first_year_prior_year_rule_and_high_agi():
    snap = run_simulation(salary_plan({"strategy": "safe_harbor", "prior_year_total_tax": 9_000,
                                       "prior_year_agi": 200_000})).yearly_snapshots[0]
    # min(11,853, 110% x 9,000 = 9,900).
    assert snap.cash_flow.required_annual_payment == pytest.approx(9_900)
    assert snap.cash_flow.estimated_tax_payments == pytest.approx(9_900 - 7_350)


@pytest.mark.parametrize("build", [salary_plan, retiree_plan])
def test_carried_balance_shrinks_by_the_estimates(build):
    off = run_simulation(build(lag=1)).yearly_snapshots[0]
    safe = run_simulation(build({"strategy": "safe_harbor"}, lag=1)).yearly_snapshots[0]
    settle = run_simulation(build({"strategy": "settle_at_filing"}, lag=1)).yearly_snapshots[0]
    estimates = safe.cash_flow.estimated_tax_payments
    assert estimates > 0
    # The carried balance is the year's balance after the estimates paid.
    assert safe.tax_balance == pytest.approx(-safe.cash_flow.tax_delta, abs=.01)
    assert safe.tax_balance == pytest.approx(safe.taxes - safe.cash_flow.tax_withheld - estimates, abs=.01)
    # The penalty travels with the carried balance.
    assert settle.tax_balance - off.tax_balance == pytest.approx(settle.cash_flow.underpayment_penalty, abs=.01)
    if build is salary_plan:
        assert off.tax_balance - safe.tax_balance == pytest.approx(estimates, abs=.01)
        # Estimates are paid this year instead of next.
        assert off.net_cash_flow - safe.net_cash_flow == pytest.approx(estimates, abs=.01)


@pytest.mark.parametrize("build", [salary_plan, retiree_plan])
@pytest.mark.parametrize("strategy", ["settle_at_filing", "safe_harbor", "pay_in_full"])
def test_cash_flow_outflows_and_tax_totals_balance(build, strategy):
    result = run_simulation(build({"strategy": strategy}))
    for snapshot in result.yearly_snapshots:
        # Every dollar in reaches an outflow, including estimates and the penalty.
        assert cash_uses_balance(snapshot) == pytest.approx(0, abs=.02)
        assert snapshot.taxes == pytest.approx(
            snapshot.federal_tax + snapshot.state_tax + snapshot.local_tax + snapshot.capital_gains_tax
            + snapshot.fica_tax + snapshot.niit_tax + snapshot.early_withdrawal_penalty
            + snapshot.cash_flow.underpayment_penalty, abs=.01)
        assert snapshot.net_worth == pytest.approx(
            sum(snapshot.accounts.values()) + snapshot.real_assets_value - snapshot.liabilities_balance
            - snapshot.tax_balance - snapshot.unfunded_expenses, abs=1e-6)


def test_partial_first_year_with_entered_history_counts_taxes_already_paid():
    history = {"tax_year": 2026, "gross_income": 50_000, "tax_paid": 7_500,
               "w2_income_by_owner": {"self": 50_000}}
    plan = salary_plan({"strategy": "safe_harbor"}, first_year_fraction=.5)
    plan.tax_settings["year_to_date"] = history
    flow = run_simulation(plan).yearly_snapshots[0].cash_flow
    # Same calendar year as the full-year case: 15,000 paid in total.
    assert flow.estimated_tax_payments == pytest.approx(4_503)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

SETTING = {"strategy": "safe_harbor", "prior_year_total_tax": 9_000.0, "prior_year_agi": 200_000.0}


@pytest.mark.anyio
async def test_plan_create_update_read_round_trip(client):
    created = await client.post("/api/plans", json={
        "name": "Estimates", "birth_year": 1980, "plan_type": "FIXED_DATE", "start_date": "2027-01-01",
        "tax_settings": {"estimated_payments": SETTING}})
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["tax_settings"]["estimated_payments"] == SETTING
    url = f"/api/plans/{plan['id']}"
    assert (await client.get(url)).json()["tax_settings"]["estimated_payments"] == SETTING
    income = await client.post(f"{url}/incomes", json={"name": "Salary", "annual_amount": 100_000,
                                                      "withholding_percent": 15})
    assert income.status_code == 201, income.text
    simulated = await client.post(f"{url}/simulate")
    assert simulated.status_code == 200, simulated.text
    flow = simulated.json()["yearly_snapshots"][0]["cash_flow"]
    assert flow["required_annual_payment"] > 0 and flow["estimated_tax_payments"] > 0
    assert "underpayment_penalty" not in flow  # zero is omitted
    settings = {**plan["tax_settings"], "estimated_payments": {"strategy": "settle_at_filing"}}
    updated = await client.put(url, json={"tax_settings": settings})
    assert updated.status_code == 200, updated.text
    expected = {"strategy": "settle_at_filing", "prior_year_total_tax": None, "prior_year_agi": None}
    assert (await client.get(url)).json()["tax_settings"]["estimated_payments"] == expected
    flow = (await client.post(f"{url}/simulate")).json()["yearly_snapshots"][0]["cash_flow"]
    assert flow["underpayment_penalty"] > 0 and "estimated_tax_payments" not in flow


@pytest.mark.anyio
async def test_plans_without_the_setting_read_unchanged(client):
    created = await client.post("/api/plans", json={"name": "Plain", "birth_year": 1980,
                                                    "tax_settings": {"settlement_lag_years": 0}})
    assert created.status_code == 201
    assert "estimated_payments" not in created.json()["tax_settings"]
    assert "estimated_payments" not in (await client.get(f"/api/plans/{created.json()['id']}")).json()["tax_settings"]


@pytest.mark.anyio
async def test_stateless_request_accepts_the_setting(client):
    body = engine_request(salary_plan(SETTING)).model_dump(mode="json")
    response = await client.post("/api/simulate/stateless", json=body)
    assert response.status_code == 200, response.text
    flow = response.json()["yearly_snapshots"][0]["cash_flow"]
    assert flow["required_annual_payment"] == pytest.approx(9_900)
    assert flow["estimated_tax_payments"] == pytest.approx(2_550)


@pytest.mark.anyio
@pytest.mark.parametrize("bad", [{"strategy": "quarterly"}, {"prior_year_total_tax": -1}, {"surprise": True}])
async def test_invalid_setting_uses_the_shared_error_envelope(client, bad):
    created = await client.post("/api/plans", json={"name": "Bad", "birth_year": 1980,
                                                    "tax_settings": {"estimated_payments": bad}})
    body = engine_request(salary_plan()).model_dump(mode="json")
    body["tax_settings"]["estimated_payments"] = bad
    stateless = await client.post("/api/simulate/stateless", json=body)
    for response in (created, stateless):
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["message"] and isinstance(error["details"], list) and error["details"]
