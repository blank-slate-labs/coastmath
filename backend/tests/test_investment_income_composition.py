"""Dividend and bond income tax composition (account investment_settings).

Statutory basis:
- IRC 1(h)(11): only qualified dividends get the preferential rate; the rest
  are ordinary income. IRC 1411(c)(1)(A)(i): all dividends and taxable
  interest are net investment income.
- IRC 103(a): municipal interest is excluded from gross income, but enters
  Social Security provisional income (IRC 86(b)(2)(B)), ACA MAGI
  (IRC 36B(d)(2)(B)) and IRMAA MAGI (42 U.S.C. 1395r(i)(4)(A)).
- 31 U.S.C. 3124(a): states and their subdivisions cannot tax U.S. Treasury
  interest, which stays federal ordinary income.
"""

import numpy as np
import pytest

from coastmath.engine.monte_carlo import _run_single_trial, _TrialInputs
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import _state_tax_and_taxable_income, calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeComposition,
    IncomeData,
    PlanData,
    SimState,
    account_income_composition,
)

BOND_WARNING = "Taxable bond interest is not modeled"


def _plan(accounts, *, state_code=None, income=None, healthcare=None, fraction=1.0,
          dividend_yield=0.0, birth_year=1960):
    return PlanData(
        plan_id="00000000-0000-4000-8000-0000000000b1",
        birth_year=birth_year,
        birth_month=1,
        filing_status="single",
        life_expectancy=90,
        start_year=2026,
        first_year_fraction=fraction,
        state_code=state_code,
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0,
                                   bond_return_rate=0.04, stock_dividend_yield=dividend_yield,
                                   cash_yield_rate=0.0),
        accounts={**accounts, "cash": AccountInfo(0, "checking")},
        income_streams=income or [],
        healthcare_settings=healthcare,
    )


def _bonds(settings=None, *, account_type="taxable_brokerage", balance=1_000_000):
    return AccountInfo(balance, account_type, cost_basis=balance if account_type == "taxable_brokerage" else None,
                       investment_settings={"bond_allocation": 1.0, **(settings or {})})


def _mix(treasury=0.0, municipal=0.0, other=0.0):
    return {"treasury": treasury, "municipal": municipal, "other": other}


def _pension(amount):
    return IncomeData("pension", "Pension", amount, growth_rate=0.0, tax_category="qualified_pension")


def _named(flows, name):
    return sum(flow.amount for flow in flows if flow.name == name)


# ---------------------------------------------------------------------------
# Growth: splitting and carving out income
# ---------------------------------------------------------------------------

def test_qualified_ratio_splits_taxable_dividends():
    account = AccountInfo(100_000, "taxable_brokerage", cost_basis=60_000,
                          investment_settings={"qualified_dividend_ratio": 0.7})
    state = SimState(year=2026, accounts={"b": account})
    dividends, interest = state.apply_growth(
        0.05, 0.04, 0.0, stock_dividend_yield=0.02,
        income_composition={"b": account_income_composition(account)})

    assert dividends == pytest.approx(2_000)
    assert interest == 0.0
    assert state.qualified_dividends_this_year == pytest.approx(1_400)
    assert state.ordinary_dividends_this_year == pytest.approx(600)
    assert state.ordinary_investment_income_this_year == pytest.approx(600)
    assert account.balance == pytest.approx(107_000)
    assert account.cost_basis == pytest.approx(62_000)


def test_bond_income_is_carved_from_total_return_and_raises_basis():
    settings = {"bond_income_yield": 0.035, "bond_income_mix": _mix(0.5, 0.3, 0.2),
                "municipal_state_exempt": True}
    legacy = AccountInfo(100_000, "taxable_brokerage", cost_basis=80_000)
    composed = AccountInfo(100_000, "taxable_brokerage", cost_basis=80_000, investment_settings=settings)
    state = SimState(year=2026, accounts={"legacy": legacy, "composed": composed})
    state.apply_growth(0.06, 0.04, 0.5, stock_dividend_yield=0.02, income_composition={
        aid: account_income_composition(acct) for aid, acct in state.accounts.items()})

    # 50% bonds at a 4% total return, 50% stocks at 6% price + 2% dividends.
    assert legacy.balance == pytest.approx(106_000)
    assert composed.balance == pytest.approx(legacy.balance, abs=1e-9)
    # Bond income 100,000 x 50% x 3.5% = 1,750 is recognized and reinvested.
    assert composed.cost_basis - legacy.cost_basis == pytest.approx(1_750)
    assert state.treasury_interest_this_year == pytest.approx(875)
    assert state.municipal_interest_this_year == pytest.approx(525)
    assert state.state_exempt_municipal_interest_this_year == pytest.approx(525)
    assert state.other_bond_interest_this_year == pytest.approx(350)
    assert state.qualified_dividends_this_year == pytest.approx(2_000)


def test_tax_advantaged_account_balance_unchanged_and_no_income_recognized():
    settings = {"qualified_dividend_ratio": 0.0, "bond_income_yield": 0.04,
                "bond_income_mix": _mix(other=1.0)}
    plain = AccountInfo(100_000, "traditional_ira")
    composed = AccountInfo(100_000, "traditional_ira", investment_settings=settings)
    state = SimState(year=2026, accounts={"plain": plain, "composed": composed})
    state.apply_growth(0.06, 0.04, 0.4, stock_dividend_yield=0.02, income_composition={
        aid: account_income_composition(acct) for aid, acct in state.accounts.items()})

    assert composed.balance == pytest.approx(plain.balance, abs=1e-9)
    assert composed.cost_basis is None
    assert state.qualified_dividends_this_year == 0
    assert state.ordinary_investment_income_this_year == 0
    assert state.bond_interest_this_year == 0


def test_tax_advantaged_settings_do_not_change_a_simulation():
    income = [_pension(30_000)]
    base = run_simulation(_plan({"ira": _bonds(account_type="traditional_ira")}, income=income))
    composed = run_simulation(_plan({"ira": _bonds({
        "qualified_dividend_ratio": 0.0, "bond_income_yield": 0.04,
        "bond_income_mix": _mix(municipal=1.0)}, account_type="traditional_ira")}, income=income))
    for before, after in zip(base.yearly_snapshots[:5], composed.yearly_snapshots[:5], strict=True):
        assert after.accounts["ira"] == pytest.approx(before.accounts["ira"], rel=1e-12)
        assert after.taxes == pytest.approx(before.taxes, rel=1e-12)


def test_composition_helpers_scale_partial_years_and_bound_income():
    composition = IncomeComposition(bond_income_yield=0.04)
    assert composition.for_period(0.5).bond_income_yield == pytest.approx(0.02)
    # A total loss leaves nothing to pay out: price may not fall below -100%.
    assert composition.bond_income_rate(-1.0) == 0.0
    assert composition.bond_income_rate(-0.99) == pytest.approx(0.01)
    # Unvalidated engine input is bounded and normalized.
    raw = account_income_composition(AccountInfo(1, "taxable_brokerage", investment_settings={
        "qualified_dividend_ratio": 1.5, "bond_income_mix": {"treasury": 2, "other": 2}}))
    assert raw.qualified_dividend_ratio == 1.0
    assert (raw.treasury, raw.municipal, raw.other) == (0.5, 0.0, 0.5)


def test_null_settings_are_the_legacy_simulation():
    nulls = {"stock_growth_rate": None, "dividend_yield": None, "bond_allocation": None,
             "qualified_dividend_ratio": None, "bond_income_yield": None,
             "bond_income_mix": None, "municipal_state_exempt": None}

    def run(settings):
        brokerage = AccountInfo(500_000, "taxable_brokerage", cost_basis=300_000,
                                investment_settings=settings)
        return run_simulation(_plan({"brokerage": brokerage}, state_code="CA", dividend_yield=0.02,
                                    income=[_pension(40_000)]))

    legacy, explicit = run(None), run(nulls)
    assert explicit.yearly_snapshots == legacy.yearly_snapshots
    assert explicit.metadata.warnings == legacy.metadata.warnings


# ---------------------------------------------------------------------------
# Whole simulations: accounting identity, character and tax
# ---------------------------------------------------------------------------

def test_bond_interest_reinvested_keeps_balance_and_cash_flow_identity():
    settings = {"bond_income_yield": 0.04, "bond_income_mix": _mix(other=1.0)}
    income = [_pension(60_000)]
    for fraction in (1.0, 0.5):
        legacy = run_simulation(_plan({"bonds": _bonds()}, fraction=fraction, income=income)).yearly_snapshots[0]
        composed_result = run_simulation(_plan({"bonds": _bonds(settings)}, fraction=fraction, income=income))
        composed = composed_result.yearly_snapshots[0]
        interest = 1_000_000 * 0.04 * fraction
        flow = composed.cash_flow
        assert _named(flow.income_sources, "Taxable-Account Bond Interest") == pytest.approx(interest)
        assert _named(flow.contributions, "Reinvested bond interest") == pytest.approx(interest)
        assert composed.gross_income - legacy.gross_income == pytest.approx(interest)
        # Total return is unchanged; only tax on the recognized interest differs.
        bond_growth = (1.04 ** fraction - 1) * 1_000_000
        assert composed.accounts["bonds"] == pytest.approx(1_000_000 + bond_growth)
        assert legacy.accounts["bonds"] == pytest.approx(1_000_000 + bond_growth)
        assert composed.taxes > legacy.taxes
        assert not any(BOND_WARNING in w for w in composed_result.metadata.warnings)


def test_ordinary_dividends_take_ordinary_rates_and_stay_in_nii():
    def year_one(ratio):
        brokerage = AccountInfo(1_000_000, "taxable_brokerage", cost_basis=1_000_000,
                                investment_settings={"qualified_dividend_ratio": ratio})
        return run_simulation(_plan({"brokerage": brokerage}, dividend_yield=0.02,
                                    income=[_pension(300_000)])).yearly_snapshots[0]

    qualified, ordinary = year_one(1.0), year_one(0.0)
    # $20,000 of dividends moves from the 15% capital-gains rate to the 35%
    # ordinary bracket at $300,000 of pension income (single, 2026 tables).
    shift = (ordinary.federal_tax + ordinary.capital_gains_tax) - (qualified.federal_tax + qualified.capital_gains_tax)
    assert shift == pytest.approx(20_000 * (0.35 - 0.15), rel=1e-6)
    # IRC 1411: both remain net investment income ($20,000 x 3.8%).
    assert ordinary.niit_tax == pytest.approx(760)
    assert qualified.niit_tax == pytest.approx(760)


def test_treasury_interest_is_exempt_from_state_tax_only():
    def year_one(settings):
        return run_simulation(_plan({"bonds": _bonds(settings)}, state_code="CA",
                                    income=[_pension(60_000)])).yearly_snapshots[0]

    legacy = year_one(None)
    other = year_one({"bond_income_yield": 0.04, "bond_income_mix": _mix(other=1.0)})
    treasury = year_one({"bond_income_yield": 0.04, "bond_income_mix": _mix(treasury=1.0)})
    assert treasury.federal_tax == pytest.approx(other.federal_tax)
    assert treasury.federal_tax > legacy.federal_tax
    assert other.state_tax > treasury.state_tax
    # 31 U.S.C. 3124(a): the Treasury interest leaves California income.
    assert treasury.state_tax == pytest.approx(legacy.state_tax)


def test_municipal_interest_is_federally_exempt_and_outside_nii():
    def year_one(settings, state_code=None):
        return run_simulation(_plan({"bonds": _bonds(settings)}, state_code=state_code,
                                    income=[_pension(250_000)])).yearly_snapshots[0]

    legacy = year_one(None)
    other = year_one({"bond_income_yield": 0.04, "bond_income_mix": _mix(other=1.0)})
    municipal = year_one({"bond_income_yield": 0.04, "bond_income_mix": _mix(municipal=1.0)})
    assert municipal.federal_tax == pytest.approx(legacy.federal_tax)
    assert municipal.niit_tax == 0
    assert other.niit_tax == pytest.approx(0.038 * 40_000)
    assert other.federal_tax > municipal.federal_tax

    # States tax municipal interest unless the plan marks the bonds in-state.
    taxed = year_one({"bond_income_yield": 0.04, "bond_income_mix": _mix(municipal=1.0)}, "CA")
    exempt = year_one({"bond_income_yield": 0.04, "bond_income_mix": _mix(municipal=1.0),
                       "municipal_state_exempt": True}, "CA")
    ca_legacy = year_one(None, "CA")
    assert exempt.state_tax == pytest.approx(ca_legacy.state_tax)
    assert taxed.state_tax > exempt.state_tax


def test_municipal_interest_raises_taxable_social_security_but_is_not_taxable_income():
    base = calculate(20_000, 0, "single", social_security_income=30_000)
    muni = calculate(20_000, 0, "single", social_security_income=30_000, tax_exempt_interest=40_000)
    # Pub. 915: provisional income 20,000 + 15,000 = 35,000 -> 4,500 + 850.
    assert base.taxable_social_security == pytest.approx(5_350)
    # With 40,000 of municipal interest it reaches 85% of benefits.
    assert muni.taxable_social_security == pytest.approx(25_500)
    assert muni.agi - base.agi == pytest.approx(25_500 - 5_350)
    assert muni.tax_exempt_interest == 40_000
    assert base.tax_exempt_interest == 0


def test_municipal_interest_enters_irmaa_lookback_magi():
    def snapshots(settings):
        return run_simulation(_plan(
            {"bonds": _bonds(settings)},
            income=[_pension(20_000),
                    IncomeData("ss", "Social Security", 30_000, growth_rate=0.0,
                               tax_category="social_security")],
            healthcare={"enabled": True, "medicare_enabled": True},
        )).yearly_snapshots

    legacy = snapshots(None)[2].healthcare
    municipal = snapshots({"bond_income_yield": 0.04, "bond_income_mix": _mix(municipal=1.0)})[2].healthcare
    assert legacy.medicare_lookback_year == municipal.medicare_lookback_year == 2026
    assert legacy.medicare_lookback_source == municipal.medicare_lookback_source == "history"
    # 2026 MAGI: pension + taxable Social Security (+ municipal interest).
    assert legacy.medicare_magi_used == pytest.approx(20_000 + 5_350)
    assert municipal.medicare_magi_used == pytest.approx(20_000 + 25_500 + 40_000)


def test_aca_magi_adds_back_municipal_interest():
    aca = {"enabled": True, "aca_enabled": True, "aca_benchmark_premium_annual": 12_000,
           "aca_plan_premium_annual": 11_000, "aca_apply_age_curve": False, "medicare_enabled": False}

    def healthcare(settings):
        return run_simulation(_plan({"bonds": _bonds(settings)}, income=[_pension(30_000)],
                                    healthcare=aca, birth_year=1970)).yearly_snapshots[0].healthcare

    legacy = healthcare(None)
    municipal = healthcare({"bond_income_yield": 0.04, "bond_income_mix": _mix(municipal=1.0)})
    assert municipal.aca_magi == pytest.approx(legacy.aca_magi + 40_000)
    assert municipal.aca_credit < legacy.aca_credit


def test_north_dakota_exclusion_ignores_nonqualified_dividends():
    # N.D.C.C. 57-38-30.3(2)(d): 40% of IRC 1(h)(11) qualified dividends.
    def taxable(qualified):
        return _state_tax_and_taxable_income(120_000, "ND", qualified_dividends=qualified)[1]

    assert taxable(10_000) - taxable(20_000) == pytest.approx(0.4 * 10_000)
    all_qualified = calculate(100_000, 0, "single", qualified_dividends=20_000, state_code="ND")
    half_ordinary = calculate(110_000, 0, "single", qualified_dividends=10_000, state_code="ND")
    assert half_ordinary.modified_agi == pytest.approx(all_qualified.modified_agi)
    assert half_ordinary.state > all_qualified.state

    def year_one(ratio):
        brokerage = AccountInfo(1_000_000, "taxable_brokerage", cost_basis=1_000_000,
                                investment_settings={"qualified_dividend_ratio": ratio})
        return run_simulation(_plan({"brokerage": brokerage}, state_code="ND", dividend_yield=0.02,
                                    income=[_pension(100_000)])).yearly_snapshots[0]

    assert year_one(0.5).state_tax > year_one(1.0).state_tax


def test_contribution_income_and_withdrawal_reversal_keep_each_character_share():
    composition = IncomeComposition(qualified_dividend_ratio=0.6, bond_income_yield=0.04,
                                    treasury=0.25, municipal=0.25, other=0.5,
                                    municipal_state_exempt=True)
    state = SimState(year=2026)
    # Stock dividends 1% and bond income 2% of the account: one third stock.
    state.income_character["b"] = composition.character(0.01, 0.02)
    state.recognize_yield_income("b", 3_000)
    assert state.qualified_dividends_this_year == pytest.approx(600)
    assert state.ordinary_dividends_this_year == pytest.approx(400)
    assert state.treasury_interest_this_year == pytest.approx(500)
    assert state.municipal_interest_this_year == pytest.approx(500)
    assert state.state_exempt_municipal_interest_this_year == pytest.approx(500)
    assert state.other_bond_interest_this_year == pytest.approx(1_000)
    state.reverse_yield_income("b", 300)
    assert state.qualified_dividends_this_year == pytest.approx(540)
    assert state.ordinary_dividends_this_year == pytest.approx(360)
    assert state.treasury_interest_this_year == pytest.approx(450)
    assert state.state_exempt_municipal_interest_this_year == pytest.approx(450)
    assert state.other_bond_interest_this_year == pytest.approx(900)
    # Unknown accounts keep the legacy all-qualified treatment.
    state.reverse_yield_income("unknown", 40)
    assert state.qualified_dividends_this_year == pytest.approx(500)


def test_monthly_spending_from_composed_account_simulates():
    settings = {"bond_allocation": 0.5, "qualified_dividend_ratio": 0.6, "bond_income_yield": 0.04,
                "bond_income_mix": _mix(0.25, 0.25, 0.5)}
    brokerage = AccountInfo(1_000_000, "taxable_brokerage", cost_basis=1_000_000,
                            investment_settings=settings)
    plan = _plan({"brokerage": brokerage}, dividend_yield=0.02)
    plan.expenses = [ExpenseData("living", "Living", 120_000, inflation_linked=False)]
    plan.drawdown_order = [DrawdownEntryData(1, "brokerage")]
    first = run_simulation(plan).yearly_snapshots[0]
    # Opening-balance income: 1,000,000 x 50% x 2% and x 4%.
    assert _named(first.cash_flow.income_sources, "Taxable Stock Dividends") == pytest.approx(10_000)
    assert _named(first.cash_flow.income_sources, "Taxable-Account Bond Interest") == pytest.approx(20_000)
    assert first.unfunded_expenses == 0


def test_monte_carlo_trial_carries_bond_income():
    history = np.array([[0.10, 0.05, 0.0], [-0.20, 0.08, 0.0], [0.15, -0.02, 0.0]], dtype=float)

    def trial(settings):
        plan = _plan({"bonds": _bonds(settings)}, income=[_pension(60_000)])
        inputs = _TrialInputs(plan, history, plan_years=3, start_year=2026, block_size_range=(1, 1))
        return _run_single_trial(inputs, seed=3)

    legacy = trial(None)
    composed = trial({"bond_income_yield": 0.03, "bond_income_mix": _mix(other=1.0)})
    for before, after in zip(legacy.yearly_snapshots[:3], composed.yearly_snapshots[:3], strict=True):
        # Sampled total returns (including a negative bond year) are kept;
        # the extra tax on recognized interest is paid from cash.
        assert after.accounts["bonds"] == pytest.approx(before.accounts["bonds"], rel=1e-12)
        assert after.net_worth < before.net_worth


# ---------------------------------------------------------------------------
# API: round trip, native-client merge and validation envelope
# ---------------------------------------------------------------------------

FULL_SETTINGS = {
    "stock_growth_rate": None,
    "dividend_yield": 0.02,
    "bond_allocation": 0.4,
    "qualified_dividend_ratio": 0.7,
    "bond_income_yield": 0.035,
    "bond_income_mix": {"treasury": 0.5, "municipal": 0.3, "other": 0.2},
    "municipal_state_exempt": True,
    "annual_fee_rate": None,
    "annual_fee_amount": None,
    "fee_percent_of_earnings": None,
    "reinvest_income": None,
}


async def _create(client, settings):
    return await client.post("/api/accounts", json={
        "name": "Brokerage", "account_type": "taxable_brokerage", "balance": 100_000,
        "cost_basis": 100_000, "investment_settings": settings,
    })


@pytest.mark.anyio
async def test_settings_round_trip_and_native_style_update_keeps_new_keys(client):
    created = await _create(client, FULL_SETTINGS)
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["investment_settings"] == FULL_SETTINGS
    listed = await client.get("/api/accounts")
    assert next(row for row in listed.json() if row["id"] == account["id"])["investment_settings"] == FULL_SETTINGS

    # The shipped native editor sends only the three keys it knows.
    native = {"stock_growth_rate": 0.05, "dividend_yield": 0.02, "bond_allocation": 0.4}
    updated = await client.put(f"/api/accounts/{account['id']}", json={"investment_settings": native})
    assert updated.status_code == 200, updated.text
    assert updated.json()["investment_settings"] == {**FULL_SETTINGS, **native}

    # An explicit null still clears one key; a null object clears them all.
    cleared = await client.put(f"/api/accounts/{account['id']}", json={
        "investment_settings": {**native, "bond_income_mix": None, "qualified_dividend_ratio": None}})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["investment_settings"]["bond_income_mix"] is None
    assert cleared.json()["investment_settings"]["qualified_dividend_ratio"] is None
    assert cleared.json()["investment_settings"]["bond_income_yield"] == 0.035
    off = await client.put(f"/api/accounts/{account['id']}", json={"investment_settings": None})
    assert off.status_code == 200, off.text
    assert off.json()["investment_settings"] is None


@pytest.mark.anyio
@pytest.mark.parametrize(("settings", "field", "reason"), [
    ({"bond_income_mix": {"treasury": 0.5, "municipal": 0.3, "other": 0.1}},
     "investment_settings.bond_income_mix", "add up to 100%"),
    ({"qualified_dividend_ratio": 1.2}, "investment_settings.qualified_dividend_ratio", "less than or equal to 1"),
    ({"bond_income_yield": -0.01}, "investment_settings.bond_income_yield", "greater than or equal to 0"),
    ({"bond_income_mix": {"treasury": 1.5, "other": -0.5}}, "investment_settings.bond_income_mix.treasury",
     "less than or equal to 1"),
])
async def test_invalid_settings_use_the_shared_error_envelope(client, settings, field, reason):
    response = await _create(client, settings)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert any(detail["field"] == field and reason in detail["reason"] for detail in error["details"]), error

    created = await _create(client, None)
    update = await client.put(f"/api/accounts/{created.json()['id']}", json={"investment_settings": settings})
    assert update.status_code == 422
    assert update.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_stateless_simulation_applies_the_settings(client):
    def body(settings):
        return {
            "plan_id": "00000000-0000-4000-8000-0000000000b2",
            "birth_year": 1960, "start_year": 2026, "life_expectancy": 70,
            "assumptions": {"inflation_rate": 0.0, "stock_growth_rate": 0.0, "bond_return_rate": 0.04,
                            "stock_dividend_yield": 0.0, "cash_yield_rate": 0.0},
            "accounts": {"00000000-0000-4000-8000-0000000000b3": {
                "balance": 1_000_000, "account_type": "taxable_brokerage", "name": "Bonds",
                "cost_basis": 1_000_000, "investment_settings": settings}},
        }

    legacy = await client.post("/api/simulate/stateless", json=body({"bond_allocation": 1.0}))
    composed = await client.post("/api/simulate/stateless", json=body({
        "bond_allocation": 1.0, "bond_income_yield": 0.04, "bond_income_mix": {"other": 1.0}}))
    assert legacy.status_code == composed.status_code == 200, composed.text
    first_legacy, first = legacy.json()["yearly_snapshots"][0], composed.json()["yearly_snapshots"][0]
    assert first["taxes"] > first_legacy["taxes"]
    assert any(source["name"] == "Taxable-Account Bond Interest"
               for source in first["cash_flow"]["income_sources"])
