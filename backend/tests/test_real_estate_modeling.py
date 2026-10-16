"""Planned purchases, selling costs, rentals, depreciation, passive losses and the
home sale ownership and use test (coastmath.engine.real_estate)."""
import uuid
from dataclasses import asdict, replace

import pytest

from app.engine.plan_converter import plan_to_engine_data
from app.models.account import CurrentAccount
from app.models.plan import Plan
from app.models.real_asset import RealAsset
from coastmath.engine import real_estate
from coastmath.engine.amortization import calculate_fixed_payment
from coastmath.engine.real_estate import (
    RentalYear,
    passive_activity_result,
    special_allowance,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    IncomeData,
    PlanData,
    RealAssetData,
)
from tests.engine_support import by_year


def plan(*assets, income=0.0, cash=1_000_000.0, filing_status="single", **kwargs):
    return PlanData(
        plan_id=str(uuid.uuid4()), birth_year=1980, start_year=2026, life_expectancy=55,
        filing_status=filing_status, assumptions=AssumptionData(0, 0, 0),
        accounts={"cash": AccountInfo(cash, "checking", name="Checking")},
        income_streams=[IncomeData("w", "Wages", income)] if income else [],
        drawdown_order=[DrawdownEntryData(1, "cash")],
        real_assets=list(assets), **kwargs,
    )


def rental(**overrides):
    values = dict(id="r", name="Duplex", current_value=300_000, annual_appreciation_rate=0.0,
                  adjusted_basis=300_000, tax_treatment="rental", rental_income=30_000,
                  building_basis=275_000)
    values.update(overrides)
    return RealAssetData(**values)


# ---------------------------------------------------------------------------
# Planned purchases
# ---------------------------------------------------------------------------


def purchase(**overrides):
    values = dict(id="h", name="Lake house", current_value=400_000, annual_appreciation_rate=0.0,
                  purchase_year=2028, purchase_month=7, purchase_price=400_000,
                  down_payment_rate=0.2, closing_costs=10_000,
                  purchase_loan_rate=0.06, purchase_loan_term_months=360)
    values.update(overrides)
    return RealAssetData(**values)


def test_nothing_exists_before_purchase_and_purchase_creates_loan():
    years = by_year(run_simulation(plan(purchase())))
    for year in (2026, 2027):
        s = years[year]
        assert s.real_assets_value == s.liabilities_balance == s.real_estate_purchases == 0
        assert s.accounts["cash"] == 1_000_000
        assert not any("Lake house" in e.name for e in s.cash_flow.expenses)
    s = years[2028]
    assert s.real_estate_purchases == pytest.approx(90_000)
    assert s.real_assets_value == pytest.approx(400_000)
    r = 0.06 / 12
    payment = calculate_fixed_payment(320_000, 0.06, 360)
    balance = 320_000 * (1 + r) ** 6 - payment * ((1 + r) ** 6 - 1) / r
    assert s.liabilities_balance == pytest.approx(balance, abs=0.05)
    # Down payment, closing costs and six monthly payments leave the account.
    assert 1_000_000 - s.accounts["cash"] == pytest.approx(90_000 + 6 * payment, abs=0.05)
    assert any(e.name == "Lake house purchase (down payment and closing costs)" and e.amount == pytest.approx(90_000)
               for e in s.cash_flow.expenses)
    assert years[2029].liabilities_balance < balance


def test_purchase_without_loan_pays_full_price_and_price_grows_with_appreciation():
    asset = purchase(purchase_loan_rate=None, purchase_loan_term_months=None, down_payment_rate=None,
                     annual_appreciation_rate=0.05, purchase_month=1, closing_costs=0)
    s = by_year(run_simulation(plan(asset)))[2028]
    price = 400_000 * 1.05 ** 2
    assert s.real_estate_purchases == pytest.approx(price)
    assert s.liabilities_balance == 0
    assert s.real_assets_value == pytest.approx(price * 1.05)


def test_explicit_funding_account_shortfall_is_unfunded():
    p = plan(purchase(purchase_funding_account_id="savings"))
    p.accounts["savings"] = AccountInfo(50_000, "savings", name="Savings")
    years = by_year(run_simulation(p))
    s = years[2028]
    assert s.accounts["savings"] == 0
    assert s.unfunded_expenses == pytest.approx(40_000, abs=0.01)
    # The primary account still pays the loan, not the purchase.
    payment = calculate_fixed_payment(320_000, 0.06, 360)
    assert 1_000_000 - s.accounts["cash"] == pytest.approx(6 * payment, abs=0.05)


def test_past_purchase_date_means_already_owned():
    asset = purchase(purchase_year=2020)
    s = by_year(run_simulation(plan(asset)))[2026]
    assert s.real_estate_purchases == 0 and s.real_assets_value == pytest.approx(400_000)
    assert s.liabilities_balance == 0


# ---------------------------------------------------------------------------
# Selling costs
# ---------------------------------------------------------------------------


def test_selling_costs_reduce_gain_and_proceeds():
    def run(rate):
        asset = RealAssetData("i", "Land", 500_000, annual_appreciation_rate=0.0, adjusted_basis=300_000,
                              tax_treatment="investment", sale_year=2027, sale_month=1,
                              selling_cost_rate=rate)
        return by_year(run_simulation(plan(asset)))[2027]
    with_costs, without = run(0.06), run(0.0)
    expected = calculate(gross_income=0, deductions=0, filing_status="single", capital_gains=170_000,
                         tax_year=2027).capital_gains_tax
    assert with_costs.capital_gains_tax == pytest.approx(expected)
    assert with_costs.capital_gains_tax < without.capital_gains_tax
    assert without.accounts["cash"] - with_costs.accounts["cash"] == pytest.approx(
        30_000 - (without.taxes - with_costs.taxes), abs=0.01)


def test_zero_selling_cost_rate_leaves_existing_sale_unchanged():
    asset = RealAssetData("i", "Land", 500_000, annual_appreciation_rate=0.02, adjusted_basis=300_000,
                          tax_treatment="investment", sale_year=2028, sale_month=4)
    assert run_simulation(plan(asset)).yearly_snapshots == run_simulation(
        plan(replace(asset, selling_cost_rate=0.0))).yearly_snapshots


# ---------------------------------------------------------------------------
# Depreciation
# ---------------------------------------------------------------------------


def test_depreciation_schedule_full_years_and_basis_cap():
    assert real_estate.depreciation_for_year(275_000, 27.5, 0, 0, 12) == pytest.approx(10_000)
    assert real_estate.depreciation_for_year(390_000, 39, 0, 0, 12) == pytest.approx(10_000)
    assert real_estate.depreciation_for_year(275_000, 27.5, 270_000, 0, 12) == pytest.approx(5_000)
    assert real_estate.depreciation_for_year(275_000, 27.5, 275_000, 0, 12) == 0
    years = by_year(run_simulation(plan(rental(prior_depreciation=262_500))))
    assert years[2026].rental_depreciation == pytest.approx(10_000)
    assert years[2027].rental_depreciation == pytest.approx(2_500)
    assert years[2028].rental_depreciation == 0


def test_mid_month_first_year_land_excluded_and_disposition_year():
    asset = purchase(tax_treatment="rental", purchase_month=4, purchase_loan_rate=None,
                     purchase_loan_term_months=None, down_payment_rate=None, closing_costs=0,
                     land_value_rate=0.25, rental_income=0, sale_year=2030, sale_month=7)
    years = by_year(run_simulation(plan(asset)))
    annual = 400_000 * 0.75 / 27.5
    assert years[2028].rental_depreciation == pytest.approx(annual * 8.5 / 12)
    assert years[2029].rental_depreciation == pytest.approx(annual)
    assert years[2030].rental_depreciation == pytest.approx(annual * 6.5 / 12)
    total = annual * (8.5 / 12 + 1 + 6.5 / 12)
    # The sale gain is entirely depreciation (no appreciation).
    assert years[2030].unrecaptured_section_1250_gain == pytest.approx(total)
    nonresidential = by_year(run_simulation(plan(replace(asset, rental_property_class="nonresidential"))))
    assert nonresidential[2029].rental_depreciation == pytest.approx(400_000 * 0.75 / 39)


def test_missing_land_split_omits_depreciation_with_warning():
    result = run_simulation(plan(rental(building_basis=None)))
    assert result.yearly_snapshots[0].rental_depreciation == 0
    assert any("rental depreciation is omitted" in w for w in result.metadata.warnings)


# ---------------------------------------------------------------------------
# Rental income, passive losses, NIIT, QBI
# ---------------------------------------------------------------------------


def test_rental_cash_flow_and_schedule_e_income():
    asset = rental(rental_expenses=4_000, vacancy_rate=0.1, annual_property_tax=3_000)
    s = run_simulation(plan(asset)).yearly_snapshots[0]
    assert s.rental_income == pytest.approx(27_000)
    assert s.rental_expenses == pytest.approx(7_000)
    assert s.rental_depreciation == pytest.approx(10_000)
    assert s.rental_taxable_income == pytest.approx(10_000)
    assert s.fica_tax == 0  # not self-employment income
    names = {flow.name for flow in s.cash_flow.income_sources}
    assert "Duplex rent" in names
    assert any(e.name == "Duplex (rental expenses)" for e in s.cash_flow.expenses)
    # Cash: rent less operating expenses and property tax; depreciation is not cash.
    assert s.accounts["cash"] - 1_000_000 == pytest.approx(27_000 - 7_000 - s.taxes, abs=0.01)
    # Property tax on a rental is a Schedule E expense, not an itemized deduction.
    assert s.deduction_used == "standard"


def test_rental_expense_rate_and_income_growth():
    asset = rental(rental_expense_rate=0.1, rental_income_growth_rate=0.03)
    years = by_year(run_simulation(plan(asset)))
    assert years[2028].rental_income == pytest.approx(30_000 * 1.03 ** 2)
    assert years[2028].rental_expenses == pytest.approx(3_000 * 1.03 ** 2)


@pytest.mark.parametrize(("magi", "allowance"), [(90_000, 25_000), (120_000, 15_000), (150_000, 0), (170_000, 0)])
def test_special_allowance_phase_out(magi, allowance):
    assert special_allowance(magi, "single", False) == pytest.approx(allowance)
    assert special_allowance(magi, "married_filing_jointly", False) == pytest.approx(allowance)


def test_special_allowance_married_filing_separately():
    assert special_allowance(40_000, "married_filing_separately", False) == 0
    assert special_allowance(40_000, "married_filing_separately", True) == pytest.approx(12_500)
    assert special_allowance(60_000, "married_filing_separately", True) == pytest.approx(7_500)


def test_passive_loss_allowance_suspends_excess_and_nets_properties():
    loss = RentalYear("a", rent=10_000, operating=40_000)
    result = passive_activity_result([loss], {}, set(), 90_000, "single")
    assert result.allowed == pytest.approx(-25_000)
    assert result.suspended == {"a": pytest.approx(5_000)}
    gain = RentalYear("b", rent=20_000)
    netted = passive_activity_result([loss, gain], {}, set(), 200_000, "single")
    assert netted.allowed == pytest.approx(0)
    assert netted.suspended == {"a": pytest.approx(10_000)}
    inactive = RentalYear("c", rent=0, operating=10_000, active_participation=False)
    assert passive_activity_result([inactive], {}, set(), 50_000, "single").allowed == 0


def test_suspended_losses_offset_income_then_release_on_sale():
    held = passive_activity_result([RentalYear("a", rent=8_000)], {"a": 20_000}, set(), 300_000, "single")
    assert held.allowed == 0 and held.suspended == {"a": pytest.approx(12_000)}
    sold = passive_activity_result([RentalYear("a", rent=8_000)], {"a": 20_000}, {"a"}, 300_000, "single")
    assert sold.allowed == pytest.approx(-12_000) and sold.suspended == {}
    assert sold.released == pytest.approx(12_000)


def test_simulated_passive_loss_phase_out_and_release_on_sale():
    asset = rental(rental_income=12_000, rental_expenses=20_000, sale_year=2029, sale_month=1)
    years = by_year(run_simulation(plan(asset, income=120_000)))
    # Net loss 18,000; MAGI 120,000 allows 15,000.
    assert years[2026].rental_taxable_income == pytest.approx(-15_000)
    assert years[2026].suspended_passive_losses == pytest.approx(3_000)
    high = by_year(run_simulation(plan(asset, income=300_000)))
    assert high[2026].rental_taxable_income == 0
    assert high[2028].suspended_passive_losses == pytest.approx(3 * 18_000)
    # A January sale owns no rental months but takes a half month of
    # depreciation (mid-month convention); every suspended loss is released.
    sale = high[2029]
    assert sale.suspended_passive_losses == 0
    assert sale.rental_depreciation == pytest.approx(10_000 * 0.5 / 12)
    assert sale.rental_taxable_income == pytest.approx(-3 * 18_000 - 10_000 * 0.5 / 12)


def test_opening_suspended_loss_is_used_against_rental_income():
    years = by_year(run_simulation(plan(rental(suspended_passive_loss=25_000), income=300_000)))
    # Net income 20,000 per year absorbs the carryforward over two years.
    assert years[2026].rental_taxable_income == 0
    assert years[2026].suspended_passive_losses == pytest.approx(5_000)
    assert years[2027].rental_taxable_income == pytest.approx(15_000)
    assert years[2027].suspended_passive_losses == 0


def test_net_rental_income_is_net_investment_income():
    without = by_year(run_simulation(plan(income=300_000)))[2026]
    with_rental = by_year(run_simulation(plan(rental(), income=300_000)))[2026]
    assert with_rental.niit_tax - without.niit_tax == pytest.approx(0.038 * 20_000)


def test_qbi_only_for_flagged_rentals():
    plain = run_simulation(plan(rental(), income=60_000)).yearly_snapshots[0]
    qbi = run_simulation(plan(rental(qbi_eligible=True), income=60_000)).yearly_snapshots[0]
    # 20% of the 20,000 net rental income, all in the 22% bracket.
    assert plain.federal_tax - qbi.federal_tax == pytest.approx(0.20 * 20_000 * 0.22)


# ---------------------------------------------------------------------------
# Sale taxation and unrecaptured section 1250 gain
# ---------------------------------------------------------------------------


# 2026 single: $16,100 standard deduction; 10/12/22/24% brackets end at
# 12,400/50,400/105,700/201,775; the 0% and 15% LTCG bands end at 49,450 and 545,500.
@pytest.mark.parametrize("ordinary, expected", [
    # TI 3,900: recapture at 10% to 12,400 and 12% to 43,900 (850 + 3,780); the
    # other 60,000 at 0% to 49,450 and 15% on 54,450 (8,167.50).
    (20_000, 850 + 3_780 + 8_167.50),
    # TI 133,900: recapture all in the 24% bracket (to 173,900 < 201,775), then 15%.
    (150_000, 0.24 * 40_000 + 0.15 * 60_000),
    # TI 583,900 is above the 24% bracket: recapture at 25%, the rest at 20%.
    (600_000, 0.25 * 40_000 + 0.20 * 60_000),
])
def test_unrecaptured_gain_taxed_at_most_25_percent(ordinary, expected):
    base = calculate(gross_income=ordinary, deductions=0, filing_status="single", capital_gains=100_000,
                     tax_year=2026)
    mixed = calculate(gross_income=ordinary, deductions=0, filing_status="single", capital_gains=100_000,
                      tax_year=2026, unrecaptured_section_1250_gain=40_000)
    assert mixed.unrecaptured_section_1250_gain == 40_000
    assert mixed.federal == base.federal
    assert 0 <= mixed.capital_gains_tax - base.capital_gains_tax <= 0.25 * 40_000 + 1e-6
    assert mixed.capital_gains_tax == pytest.approx(expected)


def test_unrecaptured_gain_uses_ordinary_rates_through_24_percent_bracket():
    # IRC 1(h)(1)(A)(ii)(I) and (E): recapture is taxed at ordinary rates up to the
    # top of the 24% bracket, not only up to the top of the 0% LTCG band.
    # MFJ 2026: 22% to 211,400, 24% to 403,550, 15% LTCG band to 613,700.
    # Ordinary TI 150,000, gain 300,000 of which 100,000 is recapture:
    # 22% x 61,400 + 24% x 38,600 = 22,772, plus 15% x 200,000 = 30,000.
    mfj = calculate(gross_income=150_000 + 32_200, deductions=0, capital_gains=300_000,
                    filing_status="married_filing_jointly", state_code="FL", tax_year=2026,
                    unrecaptured_section_1250_gain=100_000)
    assert mfj.taxable_income == pytest.approx(150_000)
    assert mfj.capital_gains_tax == pytest.approx(22_772 + 30_000)
    # Straddling the 24% top (single): ordinary TI 190,000, recapture 40,000:
    # 24% x 11,775 = 2,826 and 25% x 28,225 = 7,056.25, plus 15% x 60,000 = 9,000.
    single = calculate(gross_income=190_000 + 16_100, deductions=0, capital_gains=100_000,
                       filing_status="single", state_code="FL", tax_year=2026,
                       unrecaptured_section_1250_gain=40_000)
    assert single.capital_gains_tax == pytest.approx(2_826 + 7_056.25 + 9_000)


def test_rental_sale_recapture_in_22_percent_bracket_taxed_at_ordinary_rates():
    # Single, salary 90,000; rental sold July 2027 with 12,613.64 of depreciation
    # (225,000 / 27.5 for 2026 plus 6.5/12 of it for 2027). Ordinary TI
    # 92,568.18 - 16,100 = 76,468.18; recapture brings it to 89,081.82, all in
    # the 22% bracket: 1,240 + 4,560 + 22% x 38,681.82 = 14,310.00. The 100,000
    # adjusted net capital gain is at 15% = 15,000.
    asset = rental(current_value=400_000, adjusted_basis=300_000, building_basis=None, land_value_rate=0.25,
                   rental_income=24_000, rental_expenses=6_000, annual_property_tax=4_000,
                   sale_year=2027, sale_month=7)
    sale = by_year(run_simulation(plan(asset, income=90_000)))[2027]
    assert sale.unrecaptured_section_1250_gain == pytest.approx(12_613.64, abs=0.01)
    assert sale.federal_tax + sale.capital_gains_tax == pytest.approx(29_310.00, abs=0.01)


def test_no_unrecaptured_gain_keeps_tax_identical():
    for ordinary in (0, 50_000, 400_000):
        a = calculate(gross_income=ordinary, deductions=0, filing_status="married_filing_jointly",
                      capital_gains=80_000, qualified_dividends=5_000, tax_year=2026)
        b = calculate(gross_income=ordinary, deductions=0, filing_status="married_filing_jointly",
                      capital_gains=80_000, qualified_dividends=5_000, tax_year=2026,
                      unrecaptured_section_1250_gain=0.0)
        assert a == b


def test_rental_sale_recapture_and_ordinary_loss():
    asset = rental(rental_income=0, current_value=400_000, sale_year=2028, sale_month=1)
    years = by_year(run_simulation(plan(asset, income=200_000)))
    depreciation = 10_000 * 2 + 10_000 * 0.5 / 12
    assert years[2028].unrecaptured_section_1250_gain == pytest.approx(depreciation)
    loss_asset = rental(rental_income=0, current_value=250_000, sale_year=2027, sale_month=1)
    control = rental(rental_income=0, current_value=250_000, tax_treatment="investment",
                     sale_year=2027, sale_month=1)
    loss = by_year(run_simulation(plan(loss_asset, income=200_000)))[2027]
    assert loss.unrecaptured_section_1250_gain == 0
    capital = by_year(run_simulation(plan(control, income=200_000)))[2027]
    # A net section 1231 loss is ordinary, so it is worth more than a capital loss.
    assert loss.federal_tax < capital.federal_tax


# ---------------------------------------------------------------------------
# Home sale exclusion ownership and use test
# ---------------------------------------------------------------------------


def home(**overrides):
    values = dict(id="home", name="Home", current_value=600_000, annual_appreciation_rate=0.0,
                  adjusted_basis=400_000, is_primary_residence=True, tax_treatment="personal_use",
                  sale_year=2026, sale_month=7)
    values.update(overrides)
    return RealAssetData(**values)


def test_section_121_met_not_met_and_unknown():
    met = run_simulation(plan(home(owned_since_year=2018, owned_since_month=3)))
    assert met.yearly_snapshots[0].capital_gains_tax == 0
    assert not any("home sale exclusion assumes" in w for w in met.metadata.warnings)
    short = run_simulation(plan(home(owned_since_year=2025, owned_since_month=1)))
    assert short.yearly_snapshots[0].capital_gains_tax == pytest.approx(
        calculate(gross_income=0, deductions=0, filing_status="single", capital_gains=200_000,
                  tax_year=2026).capital_gains_tax)
    assert any("less than 2 of the 5 years" in w for w in short.metadata.warnings)
    moved_in_late = run_simulation(plan(home(owned_since_year=2018, primary_residence_since_year=2025,
                                             primary_residence_since_month=6)))
    assert moved_in_late.yearly_snapshots[0].capital_gains_tax > 0
    unknown = run_simulation(plan(home()))
    assert unknown.yearly_snapshots[0].capital_gains_tax == 0
    assert any("home sale exclusion assumes" in w for w in unknown.metadata.warnings)


def test_section_121_test_boundaries():
    asset = home(owned_since_year=2024, owned_since_month=7)
    assert real_estate.section_121_test(asset, 2026, 7) is True
    assert real_estate.section_121_test(asset, 2026, 6) is False
    assert real_estate.section_121_test(home(), 2026, 6) is None
    assert real_estate.section_121_test(home(), 2026, 6, purchased_at=(2023, 1)) is True


def test_home_bought_in_plan_uses_purchase_date_for_section_121():
    bought = home(purchase_year=2027, purchase_month=1, purchase_price=500_000, current_value=500_000,
                  adjusted_basis=None, annual_appreciation_rate=0.1, sale_year=2028, sale_month=6)
    result = run_simulation(plan(bought))
    assert by_year(result)[2028].capital_gains_tax > 0
    assert not any("home sale exclusion assumes" in w for w in result.metadata.warnings)
    held = run_simulation(plan(replace(bought, sale_year=2029, sale_month=1)))
    assert by_year(held)[2029].capital_gains_tax == 0


# ---------------------------------------------------------------------------
# Persistence and API
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_round_trip_simulation_and_validation(client, db_session):
    p = (await client.post("/api/plans", json={
        "name": "Synthetic rental", "birth_year": 1980, "plan_type": "FIXED_DATE",
        "start_date": "2026-01-01", "filing_status": "single", "life_expectancy": 60,
    })).json()
    url = f"/api/plans/{p['id']}"
    account = (await client.post("/api/accounts", json={
        "name": "Checking", "account_type": "checking", "balance": 500000, "plan_id": p["id"],
    }))
    assert account.status_code in (200, 201), account.text
    account_id = account.json()["id"]
    await client.post(f"{url}/incomes", json={"name": "Wages", "annual_amount": 90000})
    payload = {
        "name": "Duplex", "current_value": 350000, "annual_appreciation_rate": 0.02,
        "tax_treatment": "rental", "purchase_year": 2027, "purchase_month": 4,
        "purchase_price": 350000, "down_payment_rate": 0.25, "closing_costs": 7000,
        "purchase_funding_account_id": account_id, "purchase_loan_rate": 6.5,
        "purchase_loan_term_months": 360, "selling_cost_rate": 0.06, "rental_income": 30000,
        "rental_expense_rate": 0.1, "vacancy_rate": 0.05, "rental_property_class": "residential",
        "land_value_rate": 0.2, "qbi_eligible": True, "rental_active_participation": True,
        "suspended_passive_loss": 1000, "sale_year": 2035, "sale_month": 6,
    }
    created = await client.post(f"{url}/real-assets", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    for key, value in payload.items():
        assert body[key] == value, key
    asset_url = f"{url}/real-assets/{body['id']}"
    reloaded = (await client.get(url)).json()["real_assets"][0]
    assert reloaded["purchase_loan_rate"] == 6.5 and reloaded["qbi_eligible"] is True
    db_session.expire_all()
    engine = plan_to_engine_data(db_session.get(Plan, uuid.UUID(p["id"])),
                                 [db_session.get(CurrentAccount, uuid.UUID(account_id))])
    asset = engine.real_assets[0]
    assert asset.purchase_loan_rate == pytest.approx(0.065)
    assert asset.purchase_funding_account_id == account_id
    simulated = await client.post(f"{url}/simulate")
    assert simulated.status_code == 200, simulated.text
    snapshots = {s["year"]: s for s in simulated.json()["yearly_snapshots"]}
    assert snapshots[2026]["real_assets_value"] == 0
    # Today's-dollar price and closing costs grow with appreciation to April 2027.
    assert snapshots[2027]["real_estate_purchases"] == pytest.approx((350000 * 0.25 + 7000) * 1.02 ** 1.25)
    assert snapshots[2028]["rental_income"] > 0 and snapshots[2028]["rental_depreciation"] > 0
    assert snapshots[2035]["unrecaptured_section_1250_gain"] > 0
    # Stateless requests carry the loan rate in percent, like liabilities.
    request = asdict(engine)
    request["real_assets"][0]["purchase_loan_rate"] = 6.5
    stateless = await client.post("/api/simulate/stateless", json=request)
    assert stateless.status_code == 200, stateless.text
    assert stateless.json()["yearly_snapshots"] == simulated.json()["yearly_snapshots"]
    # Partial edits keep the other fields; invalid combinations are rejected.
    assert (await client.put(asset_url, json={"name": "Renamed"})).json()["rental_income"] == 30000
    for bad in ({"purchase_price": None}, {"down_payment_amount": 1000},
                {"purchase_loan_term_months": None}, {"sale_year": 2026},
                {"is_primary_residence": True}, {"rental_property_class": "hotel"},
                {"vacancy_rate": 1.5}):
        response = await client.put(asset_url, json={"tax_treatment": "rental", **bad})
        assert response.status_code == 422, (bad, response.text)
    assert (await client.get(asset_url)).json()["purchase_price"] == 350000
    # The funding account cannot be deleted while the property refers to it.
    assert (await client.delete(f"/api/accounts/{account_id}")).status_code == 409


@pytest.mark.anyio
async def test_planned_sale_year_before_the_plan_start_is_refused(client, db_session):
    """An asset sold before the plan starts is not held, so its sale year is refused."""
    p = (await client.post("/api/plans", json={
        "name": "Sold home", "birth_year": 1980, "plan_type": "FIXED_DATE",
        "start_date": "2026-10-01", "filing_status": "single", "life_expectancy": 90,
    })).json()
    url = f"/api/plans/{p['id']}/real-assets"
    refused = await client.post(url, json={"name": "Home", "current_value": 500000, "sale_year": 2020})
    assert refused.status_code == 422, refused.text
    assert "before the plan starts (2026)" in refused.json()["error"]["message"]
    created = await client.post(url, json={"name": "Home", "current_value": 500000, "sale_year": 2026})
    assert created.status_code == 201, created.text
    asset_url = f"{url}/{created.json()['id']}"
    assert (await client.put(asset_url, json={"sale_year": 2020})).status_code == 422
    # A sale year saved before this rule never blocks an unrelated edit.
    db_session.get(RealAsset, uuid.UUID(created.json()["id"])).sale_year = 2020
    db_session.commit()
    kept = await client.put(asset_url, json={"current_value": 510000, "sale_year": 2020})
    assert kept.status_code == 200, kept.text
