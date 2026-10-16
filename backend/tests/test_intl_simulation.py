"""Country tax regimes in the projection: the test-only pack (QZ), custom regimes and the regime test double."""

import pytest

from coastmath.engine.intl_regime import validate_regime_settings
from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PriorityData,
    ResidencyPeriodData,
)
from tests import intl_double
from tests.engine_support import reconcile
from tests.intl.helpers import intl_job, intl_plan
from tests.intl_support import intl_double_package  # noqa: F401

# The QZ fixture pack (tests/intl_fixture_pack.py) in its default region N: a 10,000
# allowance, then 20% to 50,000 and 40% above (45% from 2027); North adds 5%; a 5%
# social contribution on employment income.
QZ_TAX_ON_100K = 50_000 * .20 + 40_000 * .40
QZ_NORTH_ON_100K = 5_000.0
QZ_SOCIAL_ON_100K = 5_000.0
CUSTOM = {"meta": {"country": "XX", "name": "Elsewhere", "base_year": 2026, "currency": "EUR"},
          "national": [{"id": "income", "label": "Income tax", "category": "income_national",
                        "brackets": [{"lower": 0, "rate": 0.2}]}]}


def _cash(balance=10_000, **extra):
    return AccountInfo(balance=balance, account_type="savings", name="Cash", **extra)


# ---------------------------------------------------------------------------
# A registry pack
# ---------------------------------------------------------------------------

def test_country_plan_pays_only_the_country_tax(fixture_pack):
    result = run_simulation(intl_plan(
        tax_country="QZ", currency="EUR", income_streams=[intl_job()],
        expenses=[ExpenseData(id="e", name="Living", annual_amount=50_000)],
        accounts={"cash": _cash()}, drawdown_order=[DrawdownEntryData(1, "cash")],
        state_code="CA",  # ignored outside the US
    ))
    first = result.yearly_snapshots[0]
    assert first.tax_country == "QZ"
    assert (first.federal_tax, first.state_tax, first.local_tax, first.fica_tax) == (0, 0, 0, 0)
    assert first.national_income_tax == pytest.approx(QZ_TAX_ON_100K)
    assert first.social_contributions == pytest.approx(QZ_SOCIAL_ON_100K)
    assert first.regional_income_tax == pytest.approx(QZ_NORTH_ON_100K)
    assert first.taxes == pytest.approx(QZ_TAX_ON_100K + QZ_NORTH_ON_100K + QZ_SOCIAL_ON_100K)
    assert sum(line.amount for line in first.intl_tax_lines) == pytest.approx(first.taxes)
    assert first.deduction_used == "none"
    # Same-year settlement: no tax balance carried and every dollar reconciles.
    assert first.tax_balance == pytest.approx(0)
    reconcile(result)


def test_partial_opening_year_taxes_only_the_projected_period(fixture_pack):
    result = run_simulation(intl_plan(
        tax_country="QZ", first_year_fraction=0.5, income_streams=[intl_job()],
        accounts={"cash": _cash()}, drawdown_order=[DrawdownEntryData(1, "cash")],
    ))
    first = result.yearly_snapshots[0]
    expected = (50_000 - 10_000) * .20
    assert first.national_income_tax == pytest.approx(expected)
    assert first.taxes == pytest.approx(expected + 2_500 + 2_500)
    reconcile(result)


def test_move_from_the_us_switches_regime_by_the_majority_of_months(fixture_pack):
    def run(move_date):
        move = MilestoneData(id="move", name="Move", trigger_type="date", trigger_date=move_date)
        return run_simulation(intl_plan(
            state_code="TX", milestones=[move], income_streams=[intl_job()],
            residency_periods=[ResidencyPeriodData(state_code=None, country="QZ", start_milestone_id="move")],
            accounts={"cash": _cash()}, drawdown_order=[DrawdownEntryData(1, "cash")],
        ))
    july = {s.year: s for s in run("2027-07-01").yearly_snapshots}
    # Six months each: the later residence wins the tie.
    assert (july[2026].tax_country, july[2027].tax_country, july[2028].tax_country) == ("US", "QZ", "QZ")
    assert july[2026].federal_tax > 0 and july[2026].fica_tax > 0 and july[2026].national_income_tax == 0
    assert july[2027].federal_tax == 0 and july[2027].fica_tax == 0
    assert july[2027].national_income_tax == pytest.approx(50_000 * .20 + 40_000 * .45)  # the 2027 spec
    august = {s.year: s for s in run("2027-08-01").yearly_snapshots}
    assert august[2027].tax_country == "US"
    assert august[2028].tax_country == "QZ"


def test_us_account_withdrawals_are_taxed_by_the_residence_country(fixture_pack):
    result = run_simulation(intl_plan(
        birth_year=1960, life_expectancy=70, tax_country="QZ",
        expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000)],
        accounts={"ira": AccountInfo(balance=1_000_000, account_type="traditional_ira", name="IRA")},
        drawdown_order=[DrawdownEntryData(1, "ira")],
    ))
    first = result.yearly_snapshots[0]
    assert first.federal_tax == 0
    withdrawn = sum(f.amount for f in first.cash_flow.drawdowns)
    assert withdrawn == pytest.approx(40_000 + first.taxes, abs=.05)
    # No US 72(t) tax at 66; the country taxes the withdrawal as income (no social contribution on it).
    assert first.early_withdrawal_penalty == 0
    assert first.social_contributions == 0
    assert first.national_income_tax > 0
    reconcile(result)


def test_social_security_is_a_government_pension_abroad(fixture_pack):
    us = run_simulation(intl_plan(birth_year=1955, life_expectancy=75, income_streams=[IncomeData(
        id="ss", name="Social Security", annual_amount=30_000, is_social_security=True, is_earned_income=False)],
        accounts={"cash": _cash()}, drawdown_order=[DrawdownEntryData(1, "cash")]))
    abroad = run_simulation(intl_plan(birth_year=1955, life_expectancy=75, tax_country="QZ", income_streams=[IncomeData(
        id="ss", name="Social Security", annual_amount=30_000, is_social_security=True, is_earned_income=False)],
        accounts={"cash": _cash()}, drawdown_order=[DrawdownEntryData(1, "cash")]))
    # Not taxable federally at this income; fully taxable as income abroad.
    assert us.yearly_snapshots[0].taxes == 0
    expected = (30_000 - 10_000) * .20
    assert abroad.yearly_snapshots[0].national_income_tax == pytest.approx(expected)


def test_transaction_tax_on_taxable_account_trades(fixture_pack):
    result = run_simulation(intl_plan(
        tax_country="QZ", currency="EUR",
        intl_settings={"transaction_tax": {"rate": 0.001, "account_categories": ["taxable"]}},
        expenses=[ExpenseData(id="e", name="Living", annual_amount=100_000)],
        accounts={"broker": AccountInfo(balance=1_000_000, account_type="taxable_brokerage", name="Broker",
                                        cost_basis=1_000_000)},
        drawdown_order=[DrawdownEntryData(1, "broker")],
    ))
    first = result.yearly_snapshots[0]
    sold = sum(f.amount for f in first.cash_flow.drawdowns)
    assert first.transaction_tax == pytest.approx(sold * .001, rel=1e-6)
    assert first.taxes == pytest.approx(first.transaction_tax)
    assert any(line.category == "transaction" for line in first.intl_tax_lines)
    reconcile(result)


def test_custom_regime_and_wealth_override():
    custom = CUSTOM
    result = run_simulation(intl_plan(
        tax_country="XX", currency="EUR", income_streams=[intl_job()],
        intl_settings={"custom_regime": custom, "wealth_tax": {"rate": 0.01, "allowance": 100_000}},
        accounts={"cash": _cash(500_000)}, drawdown_order=[DrawdownEntryData(1, "cash")],
    ))
    first = result.yearly_snapshots[0]
    assert first.national_income_tax == pytest.approx(20_000)
    # Opening net worth 500,000 above a 100,000 allowance.
    assert first.wealth_tax == pytest.approx(4_000)
    assert first.taxes == pytest.approx(24_000)
    reconcile(result)


def test_monte_carlo_runs_country_plans_through_the_same_path():
    plan = intl_plan(tax_country="XX", intl_settings={"custom_regime": CUSTOM}, income_streams=[intl_job()], accounts={"cash": _cash()},
                 drawdown_order=[DrawdownEntryData(1, "cash")])
    result = run_monte_carlo(plan, n_trials=3, seed=11, max_workers=1)
    assert result.success_rate == 1.0


def test_us_only_settings_are_rejected_only_when_every_year_is_abroad(fixture_pack):
    abroad = intl_plan(tax_country="QZ", healthcare_settings={"enabled": True, "aca_enabled": True})
    with pytest.raises(ValueError, match="ACA"):
        validate_regime_settings(abroad)
    with pytest.raises(ValueError, match="tax target"):
        validate_regime_settings(intl_plan(tax_country="QZ", tax_settings={"tax_target": {"kind": "irmaa_tier"}}))
    with pytest.raises(ValueError, match="fill a federal bracket"):
        validate_regime_settings(intl_plan(tax_country="QZ", priorities=[PriorityData(
            1, priority_type="roth_conversion", conversion_mode="fill_bracket", bracket_ceiling_rate=.12)]))
    moving = intl_plan(tax_country="QZ", healthcare_settings={"enabled": True, "aca_enabled": True},
                   residency_periods=[ResidencyPeriodData(state_code="TX", country="US", end_year=2030)])
    validate_regime_settings(moving)
    validate_regime_settings(intl_plan(tax_country="QZ", tax_settings={"tax_target": {"kind": "magi", "amount": 1}}))


def test_us_plan_projection_is_unchanged_by_regime_fields():
    plan = intl_plan(income_streams=[intl_job()], state_code="CA", accounts={"cash": _cash()},
                 drawdown_order=[DrawdownEntryData(1, "cash")])
    result = run_simulation(plan).model_dump(mode="json")
    first = result["yearly_snapshots"][0]
    assert first["tax_country"] == "US" and first["intl_tax_lines"] == []
    assert first["state_tax"] > 0 and first["national_income_tax"] == 0


# ---------------------------------------------------------------------------
# Test double (account kinds, benefits, estate rules)
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("intl_double_package")
class TestCountryAccountKinds:
    def test_shared_limit_and_deductible_contributions(self):
        result = run_simulation(intl_plan(
            tax_country="ZZ", income_streams=[intl_job()],
            accounts={"cash": _cash(), "saver": AccountInfo(0, "other", name="Saver", intl_account_kind="ZZ:saver"),
                      "partner": AccountInfo(0, "other", name="Partner", intl_account_kind="ZZ:partner_saver")},
            priorities=[PriorityData(1, target_account_id="saver", allocation_mode="amount", allocation_value=6_000),
                        PriorityData(2, target_account_id="partner", allocation_mode="amount", allocation_value=6_000)],
            drawdown_order=[DrawdownEntryData(1, "cash")],
        ))
        first = result.yearly_snapshots[0]
        assert first.accounts["saver"] == pytest.approx(6_000)
        # The shared group's 10,000 leaves 4,000 for the second kind.
        assert first.accounts["partner"] == pytest.approx(4_000)
        # 20% on income less deductible contributions, 5% social contribution on wages.
        assert first.national_income_tax == pytest.approx(.2 * (100_000 - 10_000))
        assert first.social_contributions == pytest.approx(5_000)
        reconcile(result)

    def test_percent_of_earnings_limit_contribution_tax_bonus_and_earnings_tax(self):
        result = run_simulation(intl_plan(
            tax_country="ZZ", income_streams=[intl_job(40_000)],
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.10, bond_return_rate=0.0,
                                       stock_dividend_yield=0.0, cash_yield_rate=0.0),
            accounts={"cash": _cash(), "free": AccountInfo(10_000, "other", name="Free", intl_account_kind="ZZ:free",
                                                           investment_settings={"bond_allocation": 0.0})},
            priorities=[PriorityData(1, target_account_id="free")],
            drawdown_order=[DrawdownEntryData(1, "cash")],
        ))
        first = result.yearly_snapshots[0]
        flows = [f for f in first.cash_flow.contributions if f.account_id == "free"]
        # 10% of 40,000 earned income (cap 5,000) is the room.
        assert sum(f.amount for f in flows) == pytest.approx(4_000)
        # Growth 1,000 on the opening 10,000 less 10% earnings tax; mid-year
        # contribution growth is the only other movement; 15% contribution
        # tax and a 25% bonus (cap 1,000) stay inside the account.
        balance = first.accounts["free"]
        assert balance >= 10_000 + 900 + 4_000 * (1 - .15 + .25) - .01
        # Tax inside the account is not part of the year's taxes.
        assert first.national_income_tax == pytest.approx(.2 * 40_000)
        reconcile(result)

    def test_access_penalty_tax_free_fraction_and_cap(self):
        result = run_simulation(intl_plan(
            birth_year=1970, life_expectancy=70, tax_country="ZZ",
            expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000)],
            accounts={"saver": AccountInfo(500_000, "other", name="Saver", intl_account_kind="ZZ:saver")},
            drawdown_order=[DrawdownEntryData(1, "saver")],
        ))
        by_year = {s.year: s for s in result.yearly_snapshots}
        early = by_year[2026]  # age 56, before the access age of 60
        withdrawn = sum(f.amount for f in early.cash_flow.drawdowns)
        assert early.early_withdrawal_penalty == pytest.approx(withdrawn * .2, rel=1e-6)
        # A quarter is tax free, until 20,000 of tax-free withdrawals is used.
        assert early.national_income_tax == pytest.approx(.2 * withdrawn * .75, rel=1e-6)
        later = by_year[2030]  # age 60
        assert later.early_withdrawal_penalty == 0
        taxed = sum(f.amount for f in later.cash_flow.drawdowns)
        free_used = sum(sum(f.amount for f in by_year[y].cash_flow.drawdowns) * .25 for y in range(2026, 2030))
        remaining_free = max(0.0, 20_000 - free_used)
        assert later.national_income_tax == pytest.approx(.2 * (taxed - min(taxed * .25, remaining_free)), rel=1e-6)
        reconcile(result)

    @pytest.mark.parametrize("user_lock_year", [None, 2033])
    def test_kind_without_penalty_is_locked_until_its_access_age(self, user_lock_year):
        lock = {"unlock": "year", "year": user_lock_year} if user_lock_year else None
        result = run_simulation(intl_plan(
            birth_year=1970, life_expectancy=66, tax_country="ZZ",
            expenses=[ExpenseData(id="e", name="Living", annual_amount=40_000)],
            accounts={"preserved": AccountInfo(500_000, "other", name="Preserved", intl_account_kind="ZZ:preserved",
                                               withdrawal_lock=lock),
                      "cash": _cash(1_000_000)},
            drawdown_order=[DrawdownEntryData(1, "preserved"), DrawdownEntryData(2, "cash")],
        ))
        by_year = {s.year: s for s in result.yearly_snapshots}

        def drawn(year, account_id):
            return sum(f.amount for f in by_year[year].cash_flow.drawdowns if f.account_id == account_id)

        # Access age 60 (2030) and no penalty: locked before it, so the next
        # account in the drawdown order funds the spending in full.
        unlocked = user_lock_year or 2030
        for year in range(2026, unlocked):
            assert drawn(year, "preserved") == 0, year
            assert drawn(year, "cash") == pytest.approx(40_000), year
            assert by_year[year].accounts["preserved"] == pytest.approx(500_000), year
            assert by_year[year].unfunded_expenses == 0, year
        # The engine's own lock ending at 60 does not release a user lock
        # that still holds; withdrawals resume once both have ended.
        assert drawn(unlocked, "preserved") > 0
        assert drawn(unlocked, "cash") == 0
        assert all(s.early_withdrawal_penalty == 0 for s in result.yearly_snapshots)
        reconcile(result)

    def test_conversion_and_minimum_withdrawal(self):
        result = run_simulation(intl_plan(
            birth_year=1955, life_expectancy=85, tax_country="ZZ",
            accounts={"cash": _cash(), "saver": AccountInfo(100_000, "other", name="Saver", intl_account_kind="ZZ:saver")},
            drawdown_order=[DrawdownEntryData(1, "cash")],
        ))
        first = result.yearly_snapshots[0]  # age 71: converted to the income kind, 5% minimum
        assert first.cash_flow.income_sources[0].source == "rmd"
        assert first.cash_flow.income_sources[0].amount == pytest.approx(5_000)
        assert first.accounts["saver"] == pytest.approx(95_000)
        # The converted kind has no tax-free fraction: the whole minimum is income.
        assert first.national_income_tax == pytest.approx(1_000)
        reconcile(result)

    def test_kind_withdrawals_are_ordinary_income_in_a_us_year(self):
        result = run_simulation(intl_plan(
            birth_year=1955, life_expectancy=80,
            residency_periods=[ResidencyPeriodData(state_code=None, country="ZZ", start_year=2040)],
            accounts={"cash": _cash(), "saver": AccountInfo(100_000, "other", name="Saver", intl_account_kind="ZZ:saver")},
            drawdown_order=[DrawdownEntryData(1, "cash")],
        ))
        first = result.yearly_snapshots[0]
        assert first.tax_country == "US"
        assert first.cash_flow.income_sources[0].amount == pytest.approx(5_000)
        assert first.federal_tax == 0  # 5,000 is below the standard deduction
        assert first.taxes == pytest.approx(0)


@pytest.mark.usefixtures("intl_double_package")
class TestBenefitsAndEstate:
    def test_benefit_starts_at_age_prorated_and_is_passed_to_the_evaluator(self):
        result = run_simulation(intl_plan(
            birth_year=1961, birth_month=7, life_expectancy=70, tax_country="ZZ", income_streams=[intl_job(80_000)],
            intl_settings={"benefits": [{"rule": "ZZ:pension", "owner": "self", "start_age": 66,
                                         "params": {"annual_amount": 12_000}}]},
            accounts={"cash": _cash()}, drawdown_order=[DrawdownEntryData(1, "cash")],
        ))
        by_year = {s.year: s for s in result.yearly_snapshots}
        def paid(year):
            return sum(f.amount for f in by_year[year].cash_flow.income_sources if f.name == "Testland pension")
        assert paid(2026) == 0
        assert paid(2027) == pytest.approx(6_000)  # from the July birthday
        assert paid(2028) == pytest.approx(12_000)
        evaluated = [inputs for kind, inputs in intl_double.CALLS
                     if kind == "evaluate" and inputs.year == 2028][-1]
        assert evaluated.people[0].benefit_amounts == {"ZZ:pension": pytest.approx(12_000)}
        # 15% recovery once other taxable income exceeds 50,000.
        assert by_year[2028].benefit_recovery_tax == pytest.approx(1_800)
        assert by_year[2028].national_income_tax == pytest.approx(.2 * 92_000)
        reconcile(result)

    def test_milestone_start_and_survivor_context(self):
        retire = MilestoneData(id="retire", name="Retire", trigger_type="date", trigger_date="2027-04-01")
        result = run_simulation(intl_plan(
            birth_year=1960, life_expectancy=75, spouse_birth_year=1960, spouse_life_expectancy=70,
            spouse_birth_month=1, filing_status="married_filing_jointly", tax_country="ZZ", milestones=[retire],
            intl_settings={"benefits": [
                {"rule": "ZZ:pension", "owner": "self", "start_milestone_id": "retire",
                 "params": {"annual_amount": 10_000}},
                {"rule": "ZZ:pension", "owner": "spouse", "start_age": 66, "params": {"annual_amount": 5_000}}]},
            accounts={"cash": _cash()}, drawdown_order=[DrawdownEntryData(1, "cash")],
        ))
        by_year = {s.year: s for s in result.yearly_snapshots}
        def paid(year):
            return sum(f.amount for f in by_year[year].cash_flow.income_sources if f.name == "Testland pension")
        assert paid(2026) == pytest.approx(5_000)  # spouse only (66 in 2026)
        assert paid(2027) == pytest.approx(5_000 + 10_000 * 9 / 12)  # April milestone
        # The spouse dies at the start of 2030; the survivor gets 60% of the
        # spouse's last benefit on top of their own from the next year.
        assert paid(2031) == pytest.approx(10_000 + .6 * 5_000)
        contexts = [ctx for kind, ctx in intl_double.CALLS if kind == "benefit" and ctx.year == 2031]
        assert contexts and contexts[-1].spouse_alive is False
        reconcile(result)

    def test_estate_rule_at_a_first_death_and_at_the_end(self):
        result = run_simulation(intl_plan(
            birth_year=1960, life_expectancy=72, spouse_birth_year=1960, spouse_life_expectancy=68,
            filing_status="married_filing_jointly", tax_country="ZZ",
            accounts={"cash": AccountInfo(600_000, "savings", name="Cash", owner="joint")},
            drawdown_order=[DrawdownEntryData(1, "cash")],
        ))
        by_year = {s.year: s for s in result.yearly_snapshots}
        death = by_year[2028]
        estate_lines = [line for line in death.intl_tax_lines if line.category == "estate"]
        assert len(estate_lines) == 1 and estate_lines[0].person == "spouse"
        # The spouse's half of the opening net worth, 10% above 100,000.
        assert estate_lines[0].amount == pytest.approx(.1 * (300_000 - 100_000))
        assert death.taxes == pytest.approx(estate_lines[0].amount)
        legacy = result.metadata.net_legacy
        assert legacy.federal_estate_tax == 0
        assert legacy.estate_tax == pytest.approx(.1 * (legacy.gross_estate - 100_000))
        reconcile(result)
