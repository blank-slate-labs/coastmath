"""Account fees (``investment_settings.annual_fee_rate``).

Convention (``SimState.apply_growth``): ``fee = rate * year_fraction *
opening balance``, deducted after growth, never below zero, never on cash.
Fees are not deductible: IRC 67(h) (P.L. 115-97 sec. 11045, made permanent by
P.L. 119-21 sec. 70110) disallows miscellaneous itemized deductions, which
include investment advisory fees and expense ratios (IRC 212).
"""

import copy

import pytest

from coastmath.engine.historical_stress import run_historical_stress_test
from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    PlanData,
    SimState,
    account_fee_rate,
)


def _plan(accounts, *, growth=0.06, fraction=1.0, birth_year=1980, life_expectancy=90):
    return PlanData(
        plan_id="00000000-0000-4000-8000-0000000000fe",
        birth_year=birth_year,
        filing_status="single",
        life_expectancy=life_expectancy,
        start_year=2026,
        first_year_fraction=fraction,
        assumptions=AssumptionData(
            inflation_rate=0.0,
            stock_growth_rate=growth,
            bond_return_rate=0.04,
            stock_dividend_yield=0.0,
            cash_yield_rate=0.0,
        ),
        accounts=accounts,
        drawdown_order=[DrawdownEntryData(rank=i + 1, source_account_id=aid)
                        for i, aid in enumerate(accounts)],
    )


def _fee(rate, **settings):
    return {"annual_fee_rate": rate, **settings}


# ---------------------------------------------------------------------------
# Engine: SimState.apply_growth
# ---------------------------------------------------------------------------

def test_one_percent_fee_on_100k_with_six_percent_growth():
    # 100,000 grows 6% to 106,000; the fee is 1% of the opening 100,000.
    state = SimState(year=2026, accounts={"ira": AccountInfo(
        100_000, "traditional_ira", investment_settings=_fee(0.01))})
    state.apply_growth(0.06)
    assert state.accounts["ira"].balance == pytest.approx(105_000.0)
    assert state.investment_fees_this_year == pytest.approx(1_000.0)


def test_partial_year_fee_is_prorated_like_dividends():
    state = SimState(year=2026, accounts={"ira": AccountInfo(
        100_000, "traditional_ira", investment_settings=_fee(0.01))})
    growth = 1.06 ** 0.5 - 1
    state.apply_growth(growth, fee_year_fraction=0.5)
    assert state.investment_fees_this_year == pytest.approx(500.0)
    assert state.accounts["ira"].balance == pytest.approx(100_000 * (1 + growth) - 500.0)


def test_taxable_fee_reduces_balance_but_not_cost_basis():
    def grown(settings):
        state = SimState(year=2026, accounts={"brokerage": AccountInfo(
            100_000, "taxable_brokerage", cost_basis=50_000, investment_settings=settings)})
        dividends, _ = state.apply_growth(0.04, stock_dividend_yield=0.02)
        return state.accounts["brokerage"], dividends

    without, dividends_without = grown(None)
    with_fee, dividends_with = grown(_fee(0.01))
    # Reinvested 2% dividend adds basis in both cases; the fee does not.
    assert without.cost_basis == pytest.approx(52_000.0)
    assert with_fee.cost_basis == pytest.approx(52_000.0)
    assert dividends_with == pytest.approx(dividends_without)
    assert with_fee.balance == pytest.approx(without.balance - 1_000.0)


def test_cash_accounts_never_pay_a_fee():
    state = SimState(year=2026, accounts={
        "checking": AccountInfo(10_000, "checking", investment_settings=_fee(0.05)),
        "savings": AccountInfo(10_000, "savings", investment_settings=_fee(0.05)),
    })
    state.apply_growth(0.06, cash_yield_rate=0.03)
    assert state.accounts["checking"].balance == 10_000
    assert state.accounts["savings"].balance == 10_000
    assert state.investment_fees_this_year == 0.0
    assert account_fee_rate(state.accounts["checking"]) == 0.0


def test_fee_never_drives_a_balance_negative():
    state = SimState(year=2026, accounts={"crypto": AccountInfo(
        100_000, "cryptocurrency", investment_settings=_fee(0.05))})
    state.apply_growth(-0.99)  # 1,000 left; a 5% fee would be 5,000
    assert state.accounts["crypto"].balance == pytest.approx(0.0, abs=1e-9)
    assert state.accounts["crypto"].balance >= 0.0
    assert state.investment_fees_this_year == pytest.approx(1_000.0)


def test_null_and_zero_fee_leave_growth_unchanged():
    def balance(settings):
        state = SimState(year=2026, accounts={"ira": AccountInfo(
            100_000, "traditional_ira", investment_settings=settings)})
        state.apply_growth(0.06, 0.04, 0.3, stock_dividend_yield=0.02)
        return state.accounts["ira"].balance, state.investment_fees_this_year

    assert balance(None) == balance(_fee(None)) == balance(_fee(0.0))
    assert balance(None)[1] == 0.0


# ---------------------------------------------------------------------------
# Engine: simulation output
# ---------------------------------------------------------------------------

def test_simulation_reports_fees_and_keeps_growth_net():
    plan = _plan({
        "ira": AccountInfo(100_000, "traditional_ira", investment_settings=_fee(0.01)),
        "roth": AccountInfo(100_000, "roth_ira"),
    })
    first = run_simulation(plan).yearly_snapshots[0]
    assert first.accounts["ira"] == pytest.approx(105_000.0)
    assert first.accounts["roth"] == pytest.approx(106_000.0)
    assert first.investment_fees == pytest.approx(1_000.0)
    # investment_growth stays the net change, so net worth still reconciles.
    assert first.investment_growth == pytest.approx(11_000.0)
    # The fee is not deductible and so creates no tax effect.
    assert first.taxes == pytest.approx(run_simulation(_plan({
        "ira": AccountInfo(100_000, "traditional_ira"),
        "roth": AccountInfo(100_000, "roth_ira"),
    })).yearly_snapshots[0].taxes)


def test_no_fee_simulation_is_identical_and_reports_zero():
    accounts = {"ira": AccountInfo(100_000, "traditional_ira"),
                "brokerage": AccountInfo(50_000, "taxable_brokerage", cost_basis=40_000)}
    base = run_simulation(_plan(copy.deepcopy(accounts)))
    explicit = copy.deepcopy(accounts)
    for account in explicit.values():
        account.investment_settings = _fee(None)
    nulled = run_simulation(_plan(explicit))
    assert all(s.investment_fees == 0.0 for s in base.yearly_snapshots)
    assert [s.accounts for s in base.yearly_snapshots] == [s.accounts for s in nulled.yearly_snapshots]


def test_monte_carlo_median_is_lower_with_a_fee_under_the_same_seed():
    def median(settings):
        plan = _plan({"ira": AccountInfo(500_000, "traditional_ira", investment_settings=settings)},
                     birth_year=1960, life_expectancy=75)
        return run_monte_carlo(plan, n_trials=20, seed=11, max_workers=1).median_final_net_worth

    assert median(_fee(0.01)) < median(None)


def test_historical_stress_applies_the_same_fee():
    def replay(settings):
        plan = _plan({"ira": AccountInfo(500_000, "traditional_ira", investment_settings=settings)},
                     birth_year=1960, life_expectancy=75)
        return run_historical_stress_test(plan, 2000)["simulation_result"].yearly_snapshots

    with_fee, without = replay(_fee(0.01)), replay(None)
    assert all(s.investment_fees > 0 for s in with_fee)
    assert with_fee[-1].net_worth < without[-1].net_worth


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

async def _create(client, settings):
    return await client.post("/api/accounts", json={
        "name": "Advised IRA", "account_type": "traditional_ira", "balance": 100_000,
        "investment_settings": settings,
    })


@pytest.mark.anyio
async def test_fee_round_trips_and_native_style_put_preserves_it(client):
    created = await _create(client, {"annual_fee_rate": 0.0125})
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["investment_settings"]["annual_fee_rate"] == 0.0125
    listed = await client.get("/api/accounts")
    row = next(r for r in listed.json() if r["id"] == account["id"])
    assert row["investment_settings"]["annual_fee_rate"] == 0.0125

    # The shipped native editor sends only the keys it knows.
    native = {"stock_growth_rate": 0.05, "dividend_yield": 0.02, "bond_allocation": 0.4}
    updated = await client.put(f"/api/accounts/{account['id']}", json={"investment_settings": native})
    assert updated.status_code == 200, updated.text
    assert updated.json()["investment_settings"]["annual_fee_rate"] == 0.0125

    cleared = await client.put(f"/api/accounts/{account['id']}",
                               json={"investment_settings": {**native, "annual_fee_rate": None}})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["investment_settings"]["annual_fee_rate"] is None


@pytest.mark.anyio
async def test_persisted_simulation_reports_investment_fees(client):
    plan = (await client.post("/api/plans", json={
        "name": "Fees", "birth_year": 1980, "plan_type": "NOW"})).json()
    assert (await _create(client, {"annual_fee_rate": 0.01})).status_code == 201
    response = await client.post(f"/api/plans/{plan['id']}/simulate")
    assert response.status_code == 200, response.text
    snapshots = response.json()["yearly_snapshots"]
    assert snapshots[0]["investment_fees"] > 0


@pytest.mark.anyio
@pytest.mark.parametrize(("rate", "reason"), [
    (0.06, "less than or equal to 0.05"),
    (-0.001, "greater than or equal to 0"),
])
async def test_out_of_range_fee_uses_the_shared_error_envelope(client, rate, reason):
    response = await _create(client, {"annual_fee_rate": rate})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert any(d["field"] == "investment_settings.annual_fee_rate" and reason in d["reason"]
               for d in error["details"]), error

    created = await _create(client, None)
    update = await client.put(f"/api/accounts/{created.json()['id']}",
                              json={"investment_settings": {"annual_fee_rate": rate}})
    assert update.status_code == 422
    assert update.json()["error"]["code"] == "VALIDATION_ERROR"
