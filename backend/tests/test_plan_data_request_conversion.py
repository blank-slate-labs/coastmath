"""request_to_engine_data: each collection and settings block of a stateless plan
request reaches the engine dataclass with its documented unit conversions."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from coastmath.engine.types import PlanData
from coastmath.schemas.plan_data_request import PlanDataRequest, request_to_engine_data

PLAN_ID = "00000000-0000-4000-8000-000000000007"
RETIRE = "00000000-0000-4000-8000-0000000000a1"
MEDICARE = "00000000-0000-4000-8000-0000000000a2"
FI = "00000000-0000-4000-8000-0000000000a3"


def _full_request() -> dict:
    """A US plan that fills every collection and every optional settings block."""
    return {
        "plan_id": PLAN_ID,
        "birth_year": 1975,
        "birth_month": 4,
        "filing_status": "married_filing_jointly",
        "filing_status_changes": [{"year": 2040, "filing_status": "single"},
                                  {"milestone_id": RETIRE, "filing_status": "head_of_household"}],
        "life_expectancy": 92,
        "start_year": 2026,
        "first_year_fraction": 0.75,
        "spouse_birth_year": 1977,
        "spouse_birth_month": 9,
        "spouse_life_expectancy": 94,
        "milestones": [
            {"id": RETIRE, "name": "Retire", "trigger_type": "age", "trigger_value": 60},
            {"id": MEDICARE, "name": "Medicare", "trigger_type": "relative", "relative_to_id": RETIRE,
             "offset_years": 5},
            {"id": FI, "name": "FI", "trigger_type": "conditions", "is_active": False,
             "conditions": {"combinator": "any", "items": [
                 {"kind": "metric", "metric": "account_balance", "account_id": "brokerage", "comparator": ">=",
                  "value_unit": "dollars", "value": 1_000_000},
                 {"kind": "milestone", "milestone_id": RETIRE, "offset_years": 2}]}},
        ],
        "income_streams": [
            {"id": "salary", "name": "Salary", "annual_amount": 150_000, "tax_category": "employment",
             "end_milestone_id": RETIRE, "growth_rate": 3.5, "growth_cap": 250_000,
             "growth_cap_inflation_linked": True, "withholding_percent": 22, "start_month": 2, "end_month": 11,
             "growth_schedule": [{"start_year": 2026, "end_year": 2030, "kind": "percent", "value": 4}]},
            {"id": "pension", "name": "Pension", "annual_amount": 0, "tax_category": "qualified_pension",
             "start_milestone_id": RETIRE, "withholding_percent": None, "is_earned_income": False,
             "pension_formula": {"kind": "final_average", "linked_income_id": "salary",
                                 "benefit_percent_per_year": 1.5, "years_of_service_before_plan": 10}},
            {"id": "ss", "name": "Social Security", "annual_amount": 30_000, "is_social_security": True,
             "tax_category": "social_security", "ss_benefit_basis": "pia", "pia_monthly": 2_800,
             "is_earned_income": False, "owner": "spouse", "claiming_age": 67, "pia_reflects": "current_record",
             "covered_years_to_date": 30, "expected_benefit_percent": 80,
             "ex_spouse": {"pia_monthly": 2_400, "birth_year": 1970, "marriage_years": 12, "divorce_year": 2010}},
            {"id": "bonus", "name": "Bonus", "annual_amount": 10_000, "frequency": "once", "is_self_employed": True},
            {"id": "gig", "name": "Gig", "annual_amount": 5_000, "frequency": "recurring", "recurrence_years": 3,
             "is_active": False},
        ],
        "expenses": [
            {"id": "living", "name": "Living", "annual_amount": 60_000, "growth_rate": 2.5, "growth_cap": 90_000,
             "discretionary_percent": 40, "specific_funding_source_ids": ["checking", "brokerage"],
             "specific_funding_source_id": "checking", "start_month": 3, "end_month": 10},
            {"id": "health", "name": "Health premium", "annual_amount": 6_000, "is_payroll_deduction": True,
             "payroll_tax_treatment": "pre_tax", "payroll_tax_elections": {"fica": True, "state": False},
             "tied_income_id": "salary", "inflation_linked": False},
            {"id": "car", "name": "Car", "annual_amount": 30_000, "recurrence_years": 8,
             "recurrence_growth_rate": 1.5, "category": "essential", "start_milestone_id": RETIRE,
             "end_milestone_id": MEDICARE},
            {"id": "tuition", "name": "Tuition", "annual_amount": 20_000, "qualified_education": True,
             "payroll_tax_elections": {}},
        ],
        "priorities": [
            {"priority_rank": 1, "priority_type": "income_percent", "target_account_id": "k401",
             "source_income_id": "salary",
             "employee_rate": 10, "employer_match": {"tiers": [{"match_percent": 100, "up_to_percent_of_pay": 4}],
                                                      "cap_amount": 10_000},
             "limit_mode": "custom", "custom_annual_limit": 20_000, "reduce_employer_contribution": True},
            {"priority_rank": 2, "priority_type": "contribution", "target_account_id": "brokerage", "withdraw_if_short": True,
             "allocation_mode": "amount", "allocation_value": 5_000, "max_annual_amount": 12_000,
             "target_balance": 500_000, "start_milestone_id": RETIRE, "end_milestone_id": MEDICARE,
             "transfer_frequency": "monthly", "employer_match_rate": 50},
            {"priority_rank": 3, "priority_type": "debt_payment", "target_liability_id": "mortgage",
             "allocation_mode": "remaining"},
            {"priority_rank": 4, "priority_type": "roth_conversion", "source_account_id": "trad",
             "target_account_id": "roth", "conversion_mode": "fill_bracket", "bracket_ceiling_rate": 0.22,
             "magi_cap": 200_000, "use_plan_tax_target": True, "backdoor_roth": True,
             "allocation_mode": "remaining"},
        ],
        "drawdown_order": [{"rank": 1, "source_account_id": "brokerage"}, {"rank": 2}],
        "assumptions": {"inflation_rate": 0.025, "stock_growth_rate": 0.065, "bond_return_rate": 0.035,
                        "stock_dividend_yield": 0.015, "cash_yield_rate": 0.02},
        "assumption_curves": [
            {"curve_type": "inflation", "mode": "fixed", "fixed_rate": 0.03},
            {"curve_type": "stock_growth", "mode": "curve",
             "control_points": [{"x": 0, "y": 0.07}, {"x": 24, "y": 0.05}]},
        ],
        "accounts": {
            "checking": {"balance": 20_000, "account_type": "cash", "name": "Checking", "include_in_liquid": True},
            "brokerage": {"balance": 400_000, "account_type": "taxable", "name": "Brokerage",
                          "cost_basis": 250_000, "owner": "joint", "state_taxed_basis": 260_000,
                          "investment_settings": {"stock_growth_rate": 0.06, "dividend_yield": 0.02,
                                                  "bond_allocation": 0.3}},
            "k401": {"balance": 300_000, "account_type": "traditional_401k", "name": "401k",
                     "withdrawal_lock": {"unlock": "age", "age": 59.5},
                     "distribution_settings": {"separation_year": 2035, "spouse_sole_beneficiary": True}},
            "ira": {"balance": 80_000, "account_type": "traditional_ira", "name": "Inherited IRA",
                    "inherited_year": 2022, "beneficiary_type": "non_edb", "owner": "spouse",
                    "inheritance_settings": {"distribution_method": "ten_year", "decedent_birth_year": 1945,
                                             "decedent_died_after_rbd": True}},
            "trad": {"balance": 120_000, "account_type": "traditional_ira", "name": "IRA"},
            "roth": {"balance": 50_000, "account_type": "roth_ira", "name": "Roth",
                     "roth_settings": {"contribution_basis": 20_000, "first_contribution_year": 2010}},
        },
        "real_assets": [
            {"id": "home", "name": "Home", "current_value": 700_000, "adjusted_basis": 400_000,
             "annual_appreciation_rate": 0.035, "property_tax_rate": 0.011, "maintenance_rate": 0.01,
             "insurance_rate": 0.004, "is_primary_residence": True, "tax_treatment": "personal_use",
             "sale_year": 2050, "sale_month": 6, "owned_since_year": 2015, "primary_residence_since_year": 2015,
             "selling_cost_rate": 0.06},
            {"id": "rental", "name": "Rental", "current_value": 400_000, "annual_property_tax": 4_000,
             "annual_maintenance": 3_000, "tax_treatment": "rental", "auto_liquidate_on_depletion": True,
             "liquidation_target_account_id": "brokerage", "purchase_funding_account_id": "brokerage",
             "purchase_year": 2027, "purchase_month": 5, "purchase_price": 400_000, "down_payment_rate": 0.25,
             "closing_costs": 8_000, "purchase_loan_rate": 6.5, "purchase_loan_term_months": 360,
             "rental_income": 30_000, "rental_income_growth_rate": 0.03, "rental_expense_rate": 0.1,
             "vacancy_rate": 0.05, "rental_property_class": "residential", "land_value_rate": 0.2,
             "qbi_eligible": True, "rental_active_participation": False,
             "rental_use_schedule": [{"year": 2035, "rate": 0.5}, {"year": 2030, "rate": 1.0}]},
        ],
        "liabilities": [
            {"id": "mortgage", "name": "Mortgage", "principal_balance": 350_000, "interest_rate": 6.25,
             "term_months": 300, "linked_asset_id": "home", "extra_payment": 200,
             "payoff_milestone_id": RETIRE},
            {"id": "student", "name": "Student loan", "principal_balance": 40_000, "interest_rate": 5,
             "monthly_payment": 450, "offset_account_id": "checking", "interest_method": "daily",
             "forgiveness": {"year": 2032, "amount": 10_000, "tax_treatment": "declared_exclusion",
                             "excluded_amount": 4_000, "exclusion_basis": "insolvency"}},
            {"id": "pslf", "name": "PSLF", "principal_balance": 60_000, "interest_rate": 4.5,
             "payment_type": "percent", "forgiveness": {"milestone_id": RETIRE}},
            {"id": "tax_bill", "name": "Recurring bill", "principal_balance": 5_000, "interest_rate": 0,
             "recurrence_years": 2, "recurrence_end_year": 2040, "recurrence_end_milestone_id": RETIRE},
        ],
        "sepp_settings": {"enabled": True, "source_account_id": "ira", "method": "fixed_annuitization",
                          "start_age": 52.5, "interest_rate": 0.045, "annual_amount": 12_345},
        "cash_reserve_settings": {"enabled": True, "account_ids": ["checking"], "reserve_amount": 25_000,
                                  "sweep_excess": True},
        "state_code": "NY",
        "local_tax": {"jurisdiction": "ny_new_york_city"},
        "residency_periods": [
            {"state_code": "FL", "start_milestone_id": RETIRE, "end_milestone_id": MEDICARE, "rank": 1},
            {"state_code": "NY", "start_year": 2045, "end_year": 2050, "rank": 2,
             "local_tax": {"jurisdiction": "ny_yonkers"}},
        ],
        "charity_entities": [
            {"id": "daf", "name": "DAF", "entity_type": "daf", "annual_amount": 5_000,
             "source_account_id": None, "funding": "appreciated_shares", "start_milestone_id": RETIRE},
            {"id": "qcd", "name": "QCD", "entity_type": "qcd", "annual_amount": 3_000, "source_account_id": "ira"},
        ],
        "estate_settings": {"step_up_basis_on_death": False, "filing_status_after_death": "single",
                            "federal_estate_exemption": 15_000_000, "state_estate_tax_enabled": True,
                            "state_estate_exemption": 7_000_000, "state_estate_tax_rate": 0.16,
                            "custom_federal_exemption_enabled": True, "portability_election": False,
                            "settlement_cost_fixed": 5_000, "settlement_cost_rate": 0.02,
                            "heir_income_tax_rate": 0.24, "household_lifecycle": "last_survivor_calendar_year_end",
                            "survivor_social_security_policy": "claimed_benefit_at_survivor_fra",
                            "survivor_social_security_eligibility_confirmed": True,
                            "survivor_social_security_eligibility_source": "SSA statement",
                            "heir_capital_gains_rate": 0.15, "estate_selling_cost_percent": 6,
                            "charitable_bequest_percent": 10, "joint_account_step_up": True},
        "healthcare_settings": {"enabled": True, "medical_inflation_rate": 0.05, "aca_enabled": True,
                                "aca_start_milestone_id": RETIRE, "aca_end_milestone_id": MEDICARE,
                                "aca_benchmark_premium_annual": 12_000, "aca_plan_premium_annual": 10_000,
                                "aca_dependents": 1, "magi_prior_year": 180_000,
                                "magi_prior_year_filing_status": "married_filing_jointly"},
        "spending_rules": {"flex_threshold": -0.1, "flex_reduction": 0.15, "lookback_years": 2,
                           "spending_floor": 0.7, "performance_mode": "all_time_high", "interpolation": "linear",
                           "thresholds": [{"threshold": -0.1, "reduction": 0.1},
                                          {"threshold": -0.2, "reduction": 0.25}],
                           "start_milestone_id": RETIRE, "end_milestone_id": MEDICARE,
                           "upside_thresholds": [{"threshold": 0.2, "increase": 0.1}],
                           "flex_scope": ["expenses", "strategy_spending"], "surplus_mode": "spend_leftover"},
        "tax_settings": {"mode": "detailed", "taxable_withholding_rate": 0.1, "tax_deferred_withholding_rate": 0.2,
                         "settlement_lag_years": 1, "cash_flow_frequency": "annual",
                         "withdrawal_cash_flow_frequency": "monthly", "capital_loss_carryforward": 3_000,
                         "blend_drawdown_to_tax_target": True, "medical_expense_deductions": True,
                         "state_529_deduction": True},
        "withdrawal_strategy": {"enabled": True, "method": "guyton_klinger", "initial_rate": 0.045,
                                "start_milestone_id": RETIRE, "minimum": {"unit": "today_dollars", "amount": 40_000}},
    }


def _country_request() -> dict:
    return {
        "plan_id": PLAN_ID, "birth_year": 1975, "start_year": 2026, "tax_country": "qz", "tax_region": "n",
        "currency": "eur",
        "intl_settings": {"starting_room": [{"kind": "QZ:free_saver", "owner": "self", "amount": 25_000}],
                          "prior_year_earned_income": {"self": 90_000}},
        "accounts": {"free": {"balance": 10_000, "account_type": "other", "intl_account_kind": "QZ:free_saver"}},
        "residency_periods": [{"country": "US", "state_code": "WA", "start_year": 2040}],
    }


def _convert(body: dict) -> PlanData:
    return request_to_engine_data(PlanDataRequest.model_validate(body))


@pytest.fixture(scope="module")
def data() -> PlanData:
    return _convert(_full_request())


def test_scalars_and_filing_status_changes(data: PlanData) -> None:
    assert data.plan_id == PLAN_ID
    assert (data.birth_year, data.birth_month, data.filing_status) == (1975, 4, "married_filing_jointly")
    assert (data.life_expectancy, data.start_year, data.first_year_fraction) == (92, 2026, 0.75)
    assert (data.spouse_birth_year, data.spouse_birth_month, data.spouse_life_expectancy) == (1977, 9, 94)
    assert data.filing_status_changes == [
        {"year": 2040, "milestone_id": None, "filing_status": "single"},
        {"year": None, "milestone_id": RETIRE, "filing_status": "head_of_household"},
    ]
    assert (data.state_code, data.tax_country, data.tax_region, data.currency) == ("NY", "US", None, "USD")
    assert data.local_tax == {"jurisdiction": "ny_new_york_city"}
    assert data.intl_settings is None


def test_milestones(data: PlanData) -> None:
    retire, medicare, fi = data.milestones
    assert (retire.id, retire.trigger_type, retire.trigger_value, retire.is_active) == (RETIRE, "age", 60, True)
    assert (medicare.relative_to_id, medicare.offset_years) == (RETIRE, 5)
    assert fi.is_active is False
    assert fi.conditions["combinator"] == "any"
    assert fi.conditions["items"][1] == {"kind": "milestone", "milestone_id": RETIRE, "offset_years": 2}
    assert fi.conditions["deadline"] is None


def test_income_percents_become_decimals(data: PlanData) -> None:
    salary, pension, ss, bonus, gig = data.income_streams
    assert (salary.growth_rate, salary.withholding_percent) == (0.035, 0.22)
    assert (salary.growth_cap, salary.growth_cap_inflation_linked) == (250_000, True)
    assert (salary.start_month, salary.end_month, salary.end_milestone_id) == (2, 11, RETIRE)
    assert salary.growth_schedule == [
        {"start_year": 2026, "end_year": 2030, "kind": "percent", "value": 4.0, "dollars": None}]
    assert salary.ss_benefit_basis == "amount"
    # A null withholding percent means none; a null growth rate follows the plan curve.
    assert (pension.withholding_percent, pension.growth_rate) == (0.0, None)
    assert pension.pension_formula["kind"] == "final_average"
    assert pension.pension_formula["linked_income_id"] == "salary"
    assert pension.pension_formula["years_of_service_before_plan"] == 10.0
    assert (ss.ss_benefit_basis, ss.pia_monthly, ss.claiming_age, ss.owner) == ("pia", 2_800, 67, "spouse")
    assert (ss.pia_reflects, ss.covered_years_to_date, ss.expected_benefit_percent) == ("current_record", 30, 80)
    assert (ss.ex_spouse["pia_monthly"], ss.ex_spouse["divorce_year"], ss.ex_spouse["birth_month"]) == (
        2_400.0, 2010, 1)
    assert (bonus.frequency, bonus.is_self_employed, bonus.pension_formula, bonus.ex_spouse) == (
        "once", True, None, None)
    assert (gig.recurrence_years, gig.is_active, gig.growth_schedule) == (3, False, None)


def test_expense_percents_become_decimals(data: PlanData) -> None:
    living, health, car, tuition = data.expenses
    assert (living.growth_rate, living.growth_cap, living.discretionary_fraction) == (0.025, 90_000, 0.4)
    # The discretionary percent rewrites the category.
    assert living.category == "essential"
    assert (living.specific_funding_source_id, living.specific_funding_source_ids) == (
        "checking", ["checking", "brokerage"])
    assert (health.is_payroll_deduction, health.payroll_tax_treatment, health.tied_income_id) == (
        True, "pre_tax", "salary")
    assert health.payroll_tax_elections == {"state": False, "fica": True}
    assert health.inflation_linked is False
    assert (car.recurrence_years, car.recurrence_growth_rate, car.growth_rate) == (8, 0.015, None)
    # Empty wage-base elections mean the treatment's defaults.
    assert (tuition.payroll_tax_elections, tuition.qualified_education) == (None, True)


def test_priorities(data: PlanData) -> None:
    payroll, saving, debt, conversion = data.priorities
    assert (payroll.employee_rate, payroll.employer_match_rate) == (0.1, 0.0)
    assert (payroll.limit_mode, payroll.custom_annual_limit, payroll.reduce_employer_contribution) == (
        "custom", 20_000, True)
    assert asdict(payroll.employer_match) == {
        "tiers": [{"match_percent": 1.0, "up_to_percent_of_pay": 0.04}],
        "cap_amount": 10_000.0, "nonelective_percent": 0.0, "true_up": True, "roth": False}
    assert (saving.allocation_mode, saving.allocation_value, saving.employer_match_rate) == ("amount", 5_000, 0.5)
    assert (saving.max_annual_amount, saving.target_balance, saving.withdraw_if_short) == (12_000, 500_000, True)
    assert (saving.start_milestone_id, saving.end_milestone_id, saving.transfer_frequency) == (
        RETIRE, MEDICARE, "monthly")
    assert saving.employer_match is None
    assert (debt.target_liability_id, debt.allocation_mode) == ("mortgage", "remaining")
    assert (conversion.conversion_mode, conversion.bracket_ceiling_rate, conversion.magi_cap) == (
        "fill_bracket", 0.22, 200_000)
    assert (conversion.use_plan_tax_target, conversion.backdoor_roth) == (True, True)
    assert [(d.rank, d.source_account_id) for d in data.drawdown_order] == [(1, "brokerage"), (2, None)]


def test_assumptions_and_curves(data: PlanData) -> None:
    assert asdict(data.assumptions) == {
        "inflation_rate": 0.025, "stock_growth_rate": 0.065, "bond_return_rate": 0.035,
        "stock_dividend_yield": 0.015, "cash_yield_rate": 0.02}
    fixed, curve = data.assumption_curves
    assert (fixed.curve_type, fixed.mode, fixed.fixed_rate, fixed.control_points) == ("inflation", "fixed", 0.03, [])
    assert curve.control_points == [{"x": 0, "y": 0.07}, {"x": 24, "y": 0.05}]


def test_accounts_dump_their_settings(data: PlanData) -> None:
    accounts = data.accounts
    assert list(accounts) == ["checking", "brokerage", "k401", "ira", "trad", "roth"]
    assert (accounts["checking"].include_in_liquid, accounts["brokerage"].include_in_liquid) == (True, None)
    brokerage = accounts["brokerage"]
    assert (brokerage.cost_basis, brokerage.state_taxed_basis, brokerage.owner) == (250_000, 260_000, "joint")
    assert brokerage.investment_settings["bond_allocation"] == 0.3
    assert brokerage.investment_settings["qualified_dividend_ratio"] is None
    assert accounts["k401"].withdrawal_lock == {"unlock": "age", "age": 59.5, "milestone_id": None, "year": None}
    assert accounts["k401"].distribution_settings == {"separation_year": 2035, "spouse_sole_beneficiary": True}
    assert (accounts["ira"].inherited_year, accounts["ira"].inheritance_settings["distribution_method"]) == (
        2022, "ten_year")
    # Roth settings keep only the fields the request set.
    assert accounts["roth"].roth_settings == {"contribution_basis": 20_000.0, "first_contribution_year": 2010}
    assert accounts["trad"].inheritance_settings is None and accounts["trad"].roth_settings is None


def test_real_assets_convert_the_loan_rate_and_rental_schedule(data: PlanData) -> None:
    home, rental = data.real_assets
    assert (home.is_primary_residence, home.tax_treatment, home.sale_year, home.sale_month) == (
        True, "personal_use", 2050, 6)
    assert (home.property_tax_rate, home.maintenance_rate, home.insurance_rate) == (0.011, 0.01, 0.004)
    assert (home.selling_cost_rate, home.owned_since_year, home.purchase_month) == (0.06, 2015, 1)
    assert rental.purchase_loan_rate == 0.065
    assert rental.rental_use_schedule == ((2030, 1.0), (2035, 0.5))
    assert (rental.purchase_year, rental.purchase_month, rental.purchase_funding_account_id) == (
        2027, 5, "brokerage")
    assert (rental.auto_liquidate_on_depletion, rental.liquidation_target_account_id) == (True, "brokerage")
    assert (rental.qbi_eligible, rental.rental_active_participation, rental.rental_expenses) == (True, False, 0.0)


def test_liabilities_convert_rate_payment_and_forgiveness(data: PlanData) -> None:
    mortgage, student, pslf, bill = data.liabilities
    assert (mortgage.interest_rate, mortgage.term_months, mortgage.extra_payment) == (0.0625, 300, 200)
    # Resolved from the decimal rate over the term (2308.84 a month).
    assert mortgage.monthly_payment == pytest.approx(2308.8428241026645, rel=1e-12)
    assert (mortgage.linked_asset_id, mortgage.payoff_milestone_id, mortgage.forgiveness) == ("home", RETIRE, None)
    assert (student.interest_rate, student.monthly_payment, student.interest_method) == (0.05, 450.0, "daily")
    assert asdict(student.forgiveness) == {
        "year": 2032, "milestone_id": None, "amount": 10_000.0, "tax_treatment": "declared_exclusion",
        "excluded_amount": 4_000.0, "exclusion_basis": "insolvency"}
    assert student.offset_account_id == "checking"
    assert (pslf.interest_rate, pslf.monthly_payment, pslf.payment_type) == (0.045, None, "percent")
    assert (pslf.forgiveness.milestone_id, pslf.forgiveness.tax_treatment) == (RETIRE, "taxable")
    assert (bill.recurrence_years, bill.recurrence_end_year, bill.recurrence_end_milestone_id) == (2, 2040, RETIRE)


def test_residency_and_charity(data: PlanData) -> None:
    florida, new_york = data.residency_periods
    assert (florida.state_code, florida.start_milestone_id, florida.end_milestone_id, florida.rank) == (
        "FL", RETIRE, MEDICARE, 1)
    assert (florida.local_tax, florida.country) == (None, None)
    assert (new_york.start_year, new_york.end_year, new_york.local_tax) == (2045, 2050, {"jurisdiction": "ny_yonkers"})
    daf, qcd = data.charity_entities
    assert (daf.funding, daf.start_milestone_id, daf.source_account_id) == ("appreciated_shares", RETIRE, None)
    assert (qcd.entity_type, qcd.source_account_id, qcd.funding) == ("qcd", "ira", "cash")


def test_settings_blocks(data: PlanData) -> None:
    assert asdict(data.sepp_settings) == {
        "enabled": True, "source_account_id": "ira", "method": "fixed_annuitization", "start_age": 52.5,
        "interest_rate": 0.045, "annual_amount": 12_345.0}
    assert asdict(data.cash_reserve) == {"account_ids": ("checking",), "amount": 25_000.0, "sweep_excess": True}
    # JSON mode turns the ACA milestone UUIDs into strings.
    assert (data.healthcare_settings["aca_start_milestone_id"], data.healthcare_settings["aca_end_milestone_id"]) == (
        RETIRE, MEDICARE)
    assert data.healthcare_settings["magi_prior_year"] == 180_000.0
    estate = data.estate_settings
    assert (estate.estate_selling_cost_rate, estate.charitable_bequest_rate, estate.heir_capital_gains_rate) == (
        0.06, 0.1, 0.15)
    assert (estate.household_lifecycle, estate.survivor_social_security_eligibility_source) == (
        "last_survivor_calendar_year_end", "SSA statement")
    assert (estate.step_up_basis_on_death, estate.portability_election, estate.joint_account_step_up) == (
        False, False, True)
    assert asdict(data.spending_rules) == {
        "flex_threshold": -0.1, "flex_reduction": 0.15, "lookback_years": 2, "spending_floor": 0.7,
        "performance_mode": "all_time_high", "interpolation": "linear",
        "thresholds": [{"threshold": -0.1, "reduction": 0.1}, {"threshold": -0.2, "reduction": 0.25}],
        "start_milestone_id": RETIRE, "end_milestone_id": MEDICARE,
        "upside_thresholds": [{"threshold": 0.2, "increase": 0.1}],
        "flex_scope": ["expenses", "strategy_spending"], "surplus_mode": "spend_leftover"}
    # Unset optional tax settings are dropped, not sent as None.
    assert data.tax_settings["cash_flow_frequency"] == "annual"
    assert data.tax_settings["withdrawal_cash_flow_frequency"] == "monthly"
    assert (data.tax_settings["medical_expense_deductions"], data.tax_settings["state_529_deduction"]) == (True, True)
    assert "ordinary_income_tax_rate" not in data.tax_settings and "state_brackets" not in data.tax_settings
    strategy = asdict(data.withdrawal_strategy)
    assert (strategy["method"], strategy["initial_rate"], strategy["start_milestone_id"]) == (
        "guyton_klinger", 0.045, RETIRE)
    assert strategy["minimum"] == {"amount": 40_000.0, "unit": "today_dollars"}


def test_country_request_dumps_intl_settings_in_json_mode(fixture_pack) -> None:
    data = _convert(_country_request())
    assert (data.tax_country, data.tax_region, data.currency) == ("QZ", "N", "EUR")
    assert data.intl_settings == {
        "benefits": [], "starting_room": [{"kind": "QZ:free_saver", "owner": "self", "amount": 25_000.0}],
        "prior_year_earned_income": {"self": 90_000.0}, "custom_regime": None, "wealth_tax": None,
        "transaction_tax": None}
    assert data.accounts["free"].intl_account_kind == "QZ:free_saver"
    assert (data.residency_periods[0].country, data.residency_periods[0].state_code) == ("US", "WA")


def test_omitted_blocks_stay_none() -> None:
    data = _convert({"plan_id": PLAN_ID, "birth_year": 1975, "start_year": 2026})
    for name in ("healthcare_settings", "sepp_settings", "cash_reserve", "local_tax", "estate_settings",
                 "spending_rules", "tax_settings", "withdrawal_strategy", "intl_settings"):
        assert getattr(data, name) is None, name
    assert data.filing_status_changes == []
    assert (data.milestones, data.income_streams, data.expenses, data.priorities, data.liabilities) == ([],) * 5
    assert data.accounts == {}
    assert asdict(data.assumptions) == {
        "inflation_rate": 0.03, "stock_growth_rate": 0.07, "bond_return_rate": 0.04,
        "stock_dividend_yield": 0.0, "cash_yield_rate": 0.0}
