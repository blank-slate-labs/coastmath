"""Tests for plan_converter — specifically the cost_basis pass-through (22.3.2).

Why SimState-direct instead of run_simulation: YearSnapshot only surfaces
``capital_gains_tax``, not the raw gain. At the low AGI in this fixture, LTCG
tax is $0 for both the $20k-gain and $0-gain branches, so tax_engine output
cannot distinguish them. Replicating simulator.run_simulation's SimState init
(see simulator.py:~351, which defaults cost_basis=balance when None) gives us
access to ``SimState.capital_gains_this_year`` — the reliable signal that
cost_basis flowed end-to-end from the ORM. Do not "simplify" this back into
``run_simulation`` — the assertion becomes untestable.
"""

import ast
import dataclasses
import datetime
import uuid
from pathlib import Path

import pytest

from app.engine import plan_converter
from app.engine.plan_converter import plan_to_engine_data
from app.models.account import CurrentAccount
from app.models.assumption_curve import AssumptionCurve
from app.models.cash_flow_priority import CashFlowPriority
from app.models.charity import CharityEntity
from app.models.drawdown_order import DrawdownOrder
from app.models.expense import Expense
from app.models.income import IncomeStream
from app.models.liability import Liability
from app.models.milestone import Milestone
from app.models.plan import Plan
from app.models.real_asset import RealAsset
from app.models.residency_period import ResidencyPeriod
from app.models.spouse import Spouse
from coastmath.engine.cost_basis import calculate_gain_on_withdrawal
from coastmath.engine.flex_spending import apply_flex_rules
from coastmath.engine.types import (
    AccountInfo,
    ExpenseData,
    PlanData,
    SimState,
    SpendingRulesData,
)
from coastmath.schemas.plan_data_request import (
    PlanDataRequest,
    request_to_engine_data,
)
from tests.api_support import make_account, make_plan

# ---------------------------------------------------------------------------
# Unit: cost_basis is wired from ORM -> AccountInfo
# ---------------------------------------------------------------------------

class TestPlanConverterCostBasis:
    def test_cost_basis_is_passed_through(self, db_session, test_user):
        plan = make_plan(db_session, test_user)
        acct = make_account(db_session, test_user, balance=250_000, cost_basis=150_000)

        plan_data = plan_to_engine_data(plan, [acct])

        info = plan_data.accounts[str(acct.id)]
        assert isinstance(info, AccountInfo)
        assert info.balance == pytest.approx(250_000.0)
        assert info.cost_basis == pytest.approx(150_000.0)

    def test_null_cost_basis_is_preserved_as_none(self, db_session, test_user):
        """Mirror stateless path: None flows through; simulator defaults to balance."""
        plan = make_plan(db_session, test_user)
        acct = make_account(db_session, test_user, balance=250_000, cost_basis=None)

        plan_data = plan_to_engine_data(plan, [acct])

        info = plan_data.accounts[str(acct.id)]
        assert info.balance == pytest.approx(250_000.0)
        assert info.cost_basis is None


# ---------------------------------------------------------------------------
# Integration: plan_to_engine_data -> SimState init -> withdrawal -> gain
#
# Replicates simulator.run_simulation's SimState init block (the None->balance
# default at simulator.py:~351) so the full ORM -> engine wiring is exercised.
# Uses SimState rather than run_simulation because YearSnapshot exposes only
# capital_gains_tax (which is $0 on $20k LTCG at low AGI in both branches) —
# capital_gains_this_year on SimState is the reliable signal.
# ---------------------------------------------------------------------------

def _init_state_from_plan_data(plan_data) -> SimState:
    return SimState(
        year=plan_data.start_year,
        accounts={
            aid: AccountInfo(
                balance=acct.balance,
                account_type=acct.account_type,
                cost_basis=acct.cost_basis if acct.cost_basis is not None else acct.balance,
                inherited_year=acct.inherited_year,
                owner=acct.owner,
                beneficiary_type=acct.beneficiary_type,
            )
            for aid, acct in plan_data.accounts.items()
        },
    )


class TestPlanConverterCostBasisIntegration:
    def test_250k_brokerage_150k_basis_50k_withdrawal_yields_20k_gain(
        self, db_session, test_user,
    ):
        plan = make_plan(db_session, test_user)
        acct = make_account(db_session, test_user, balance=250_000, cost_basis=150_000)

        plan_data = plan_to_engine_data(plan, [acct])
        state = _init_state_from_plan_data(plan_data)

        # Sanity: SimState carried the ORM basis through
        assert state.accounts[str(acct.id)].cost_basis == pytest.approx(150_000.0)

        state.withdraw_from(str(acct.id), 50_000)

        # gain = 50k * (1 - 150k/250k) = 50k * 0.4 = 20k
        assert state.capital_gains_this_year == pytest.approx(20_000.0)
        assert state.accounts[str(acct.id)].balance == pytest.approx(200_000.0)
        # basis ratio update: 150k * (1 - 50k/250k) = 120k
        assert state.accounts[str(acct.id)].cost_basis == pytest.approx(120_000.0)

    def test_null_cost_basis_defaults_to_balance_zero_gain(
        self, db_session, test_user,
    ):
        """Regression: NULL in DB -> basis defaulted to balance -> no gain on withdrawal."""
        plan = make_plan(db_session, test_user)
        acct = make_account(db_session, test_user, balance=250_000, cost_basis=None)

        plan_data = plan_to_engine_data(plan, [acct])
        # PlanData carries None
        assert plan_data.accounts[str(acct.id)].cost_basis is None

        state = _init_state_from_plan_data(plan_data)
        # SimState init defaulted to balance
        assert state.accounts[str(acct.id)].cost_basis == pytest.approx(250_000.0)

        state.withdraw_from(str(acct.id), 50_000)

        assert state.capital_gains_this_year == pytest.approx(0.0)
        assert state.accounts[str(acct.id)].balance == pytest.approx(200_000.0)

    def test_cost_basis_function_matches_integration_math(self):
        """Direct function call matches what the engine produces."""
        gain, new_basis = calculate_gain_on_withdrawal(50_000, 250_000, 150_000)
        assert gain == pytest.approx(20_000.0)
        assert new_basis == pytest.approx(120_000.0)


# ---------------------------------------------------------------------------
# Unit: spending_floor is wired from ORM -> SpendingRulesData (31.2.3)
# ---------------------------------------------------------------------------

class TestPlanConverterSpendingFloor:
    def test_spending_floor_passed_through(self, db_session, test_user):
        """plan_converter maps spending_floor from JSONB into SpendingRulesData."""
        plan = make_plan(db_session, test_user)
        plan.spending_rules = {
            "flex_threshold": 0.0,
            "flex_reduction": 0.4,
            "spending_floor": 0.5,
        }
        db_session.commit()
        db_session.refresh(plan)

        plan_data = plan_to_engine_data(plan, [])

        assert plan_data.spending_rules is not None
        assert plan_data.spending_rules.spending_floor == pytest.approx(0.5)
        assert plan_data.spending_rules.flex_reduction == pytest.approx(0.4)

    def test_spending_floor_defaults_to_0_8_when_absent(self, db_session, test_user):
        """When spending_floor is not in JSONB, converter uses 0.8 default."""
        plan = make_plan(db_session, test_user)
        plan.spending_rules = {
            "flex_threshold": -0.1,
            "flex_reduction": 0.20,
        }
        db_session.commit()
        db_session.refresh(plan)

        plan_data = plan_to_engine_data(plan, [])

        assert plan_data.spending_rules is not None
        assert plan_data.spending_rules.spending_floor == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Integration: spending_floor affects flex_spending reduction factor (31.2.3)
# ---------------------------------------------------------------------------

class TestSpendingFloorIntegration:
    def test_floor_not_binding(self):
        """reduction=0.4, floor=0.5 -> factor=0.6 (floor not binding)."""
        rules = SpendingRulesData(
            flex_threshold=0.0,
            flex_reduction=0.4,
            spending_floor=0.5,
        )
        plan_data = PlanData(
            plan_id="test",
            birth_year=1990,
            filing_status="single",
            life_expectancy=95,
            start_year=2025,
            spending_rules=rules,
        )
        state = SimState(year=2026, accounts={})
        # Add two years of negative returns to trigger flex rules
        state.return_history = [-0.05, -0.05]

        expenses = [
            ExpenseData(id="e1", name="Dining", annual_amount=10_000, category="discretionary"),
        ]

        result = apply_flex_rules(expenses, plan_data, state, 2026)

        # factor = max(1.0 - 0.4, 0.5) = max(0.6, 0.5) = 0.6
        assert result[0].annual_amount == pytest.approx(6_000.0)

    def test_floor_binding(self):
        """reduction=0.4, floor=0.8 -> factor=0.8 (floor clamps)."""
        rules = SpendingRulesData(
            flex_threshold=0.0,
            flex_reduction=0.4,
            spending_floor=0.8,
        )
        plan_data = PlanData(
            plan_id="test",
            birth_year=1990,
            filing_status="single",
            life_expectancy=95,
            start_year=2025,
            spending_rules=rules,
        )
        state = SimState(year=2026, accounts={})
        state.return_history = [-0.05, -0.05]

        expenses = [
            ExpenseData(id="e1", name="Dining", annual_amount=10_000, category="discretionary"),
        ]

        result = apply_flex_rules(expenses, plan_data, state, 2026)

        # factor = max(1.0 - 0.4, 0.8) = max(0.6, 0.8) = 0.8
        assert result[0].annual_amount == pytest.approx(8_000.0)


class TestAdvancedSpendingRulesConverters:
    def test_persisted_jsonb_maps_to_engine_rules(self, db_session, test_user):
        plan = make_plan(db_session, test_user)
        plan.spending_rules = {
            "flex_threshold": -0.1,
            "flex_reduction": 0.2,
            "performance_mode": "all_time_high",
            "interpolation": "linear",
            "thresholds": [{"threshold": -0.1, "reduction": 0.2}],
            "start_milestone_id": "retirement",
            "end_milestone_id": "longevity",
        }
        db_session.commit()
        db_session.refresh(plan)

        rules = plan_to_engine_data(plan, []).spending_rules
        assert rules is not None
        assert rules.performance_mode == "all_time_high"
        assert rules.interpolation == "linear"
        assert rules.thresholds[0].reduction == pytest.approx(0.2)
        assert rules.start_milestone_id == "retirement"

    def test_stateless_request_maps_the_same_jsonb_shape(self):
        request = PlanDataRequest(
            plan_id=uuid.uuid4(),
            birth_year=1990,
            start_year=2026,
            life_expectancy=95,
            milestones=[{"id": "retirement", "name": "Retirement", "trigger_type": "age", "trigger_value": 65}],
            spending_rules={
                "flex_threshold": -0.1,
                "flex_reduction": 0.2,
                "performance_mode": "all_time_high",
                "interpolation": "linear",
                "thresholds": [{"threshold": -0.1, "reduction": 0.2}],
                "start_milestone_id": "retirement",
            },
        )
        rules = request_to_engine_data(request).spending_rules
        assert rules is not None
        assert rules.performance_mode == "all_time_high"
        assert rules.thresholds[0].threshold == pytest.approx(-0.1)
        assert rules.start_milestone_id == "retirement"


# ---------------------------------------------------------------------------
# Characterisation: a plan with every relationship and setting populated
# converts to exactly the recorded PlanData.
# ---------------------------------------------------------------------------

def _uid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def _populated_plan(db_session, test_user):
    plan_id, retire, ss_start, payoff, inactive, relative = (_uid(n) for n in (1, 10, 11, 12, 13, 14))
    cash, brokerage, k401, roth, inherited = (_uid(n) for n in (20, 21, 22, 23, 24))
    salary, pension, social_security = (_uid(n) for n in (30, 31, 32))
    home, rental, mortgage, student_loan = (_uid(n) for n in (40, 41, 42, 43))

    plan = Plan(
        id=plan_id, user_id=test_user.id, name="Characterisation", plan_type="NOW",
        snapshot_conditions={}, birth_year=1980, birth_month=7,
        filing_status="married_filing_jointly", state_code="CA",
        local_tax={"kind": "flat", "rate": 1.5},
        tax_country="US", tax_region="CA", currency="USD",
        intl_settings={"treaty": "none", "pension_scheme": "us"},
        life_expectancy=92,
        filing_status_changes=[{"year": 2050, "filing_status": "single"}],
        sepp_settings={"enabled": True, "source_account_id": str(k401), "method": "rmd",
                       "start_age": 52.5, "interest_rate": 0.045, "annual_amount": 18_000},
        spending_rules={
            "flex_threshold": -0.1, "flex_reduction": 0.25, "lookback_years": 2,
            "spending_floor": 0.7, "performance_mode": "all_time_high", "interpolation": "linear",
            "thresholds": [{"threshold": -0.1, "reduction": 0.1}, {"threshold": -0.2, "reduction": 0.3},
                           {"threshold": None, "reduction": 0.5}, "junk"],
            "upside_thresholds": [{"threshold": 0.2, "increase": 0.05}, {"threshold": 0.3}],
            "start_milestone_id": str(retire), "end_milestone_id": str(payoff),
            "flex_scope": ["expenses", "contributions"], "surplus_mode": "spend",
        },
        tax_settings={"target_bracket": 0.22, "itemize": True},
        estate_settings={
            "household_lifecycle": "survivor", "survivor_social_security_policy": "auto",
            "survivor_social_security_eligibility_confirmed": True,
            "survivor_social_security_eligibility_source": "user",
            "step_up_basis_on_death": False, "filing_status_after_death": "qualifying_surviving_spouse",
            "federal_estate_exemption": 7_000_000, "state_estate_tax_enabled": True,
            "state_estate_exemption": 2_000_000, "state_estate_tax_rate": 0.16,
            "custom_federal_exemption_enabled": True, "portability_election": False,
            "settlement_cost_fixed": 5_000, "settlement_cost_rate": 0.02,
            "heir_income_tax_rate": 0.24, "heir_capital_gains_rate": None,
            "estate_selling_cost_percent": 6, "charitable_bequest_percent": 10,
            "joint_account_step_up": True,
        },
        healthcare_settings={"pre_medicare": "aca", "premium": 9_000},
        withdrawal_strategy={"enabled": True, "method": "guyton_klinger", "initial_rate": 0.045,
                             "start_milestone_id": str(retire), "start_age": None,
                             "minimum": {"amount": 40_000}, "maximum": {"amount": 150_000, "unit": "nominal"}},
        cash_reserve_settings={"enabled": True, "account_ids": [str(cash)], "reserve_amount": 25_000,
                               "sweep_excess": True},
    )
    db_session.add(plan)
    db_session.flush()

    db_session.add_all([
        CurrentAccount(id=cash, user_id=test_user.id, name="Cash", account_type="savings",
                       balance=30_000, owner="joint", include_in_liquid=True),
        CurrentAccount(id=brokerage, user_id=test_user.id, name="Brokerage", account_type="taxable_brokerage",
                       balance=250_000, cost_basis=150_000, state_taxed_basis=160_000, owner="self",
                       investment_settings={"allocation": {"stocks": 80, "bonds": 20}}),
        CurrentAccount(id=k401, user_id=test_user.id, name="401k", account_type="traditional_401k",
                       balance=400_000, owner="self",
                       withdrawal_lock={"until_age": 55},
                       distribution_settings={"rmd": True}),
        CurrentAccount(id=roth, user_id=test_user.id, name="Roth", account_type="roth_ira",
                       balance=90_000, owner="spouse", roth_settings={"contribution_basis": 40_000}),
        CurrentAccount(id=inherited, user_id=test_user.id, name="Inherited IRA", account_type="traditional_ira",
                       balance=120_000, owner="self", inherited_year=2022, beneficiary_type="edb",
                       inheritance_settings={"decedent_rmd_started": True}, intl_account_kind="us_ira"),
    ])
    db_session.add_all([
        Milestone(id=retire, plan_id=plan_id, name="Retirement", trigger_type="age", trigger_value=60,
                  sort_order=0),
        Milestone(id=ss_start, plan_id=plan_id, name="Social Security", trigger_type="date",
                  trigger_date=datetime.date(2047, 7, 1), sort_order=1),
        Milestone(id=payoff, plan_id=plan_id, name="Coast", trigger_type="expense_multiple",
                  metric="liquid_net_worth", expense_multiple=25, sort_order=2),
        Milestone(id=inactive, plan_id=plan_id, name="Sabbatical", trigger_type="conditions",
                  conditions={"all": [{"metric": "age", "op": ">=", "value": 50}]}, is_active=False,
                  sort_order=3),
        Milestone(id=relative, plan_id=plan_id, name="Five after retiring", trigger_type="relative",
                  relative_to_id=retire, offset_years=5, sort_order=4),
    ])
    db_session.add_all([
        IncomeStream(id=salary, plan_id=plan_id, name="Salary", annual_amount=150_000,
                     end_milestone_id=retire, growth_rate=3, growth_cap=200_000,
                     growth_cap_inflation_linked=True, withholding_percent=22, start_month=3,
                     tax_category="employment", owner="self",
                     growth_schedule=[{"year": 2030, "rate": 2}]),
        IncomeStream(id=pension, plan_id=plan_id, name="Pension", annual_amount=0,
                     start_milestone_id=retire, is_earned_income=False, owner="spouse",
                     frequency="once", recurrence_years=None,
                     pension_formula={"multiplier": 1.5, "years": 25, "final_salary": 120_000},
                     is_active=False),
        IncomeStream(id=social_security, plan_id=plan_id, name="Social Security", annual_amount=30_000,
                     start_milestone_id=ss_start, end_month=11, is_social_security=True,
                     is_earned_income=False, claiming_age=67, ss_benefit_basis="pia",
                     pia_reflects="current_record", covered_years_to_date=22, pia_monthly=2_800,
                     expected_benefit_percent=80, is_self_employed=True,
                     ex_spouse={"pia_monthly": 1_900, "divorce_year": 2015}),
    ])
    db_session.flush()
    db_session.add_all([
        Expense(id=_uid(50), plan_id=plan_id, name="Living", annual_amount=60_000, inflation_linked=True,
                category="essential", discretionary_percent=25, specific_funding_source_id=cash,
                specific_funding_source_ids=[str(cash), str(brokerage)], start_month=2, end_month=10),
        Expense(id=_uid(51), plan_id=plan_id, name="Health premiums", annual_amount=4_800,
                inflation_linked=False, is_payroll_deduction=True, payroll_tax_treatment="after_tax",
                payroll_tax_elections={"fica": False, "state": True}, tied_income_id=salary,
                growth_rate=5, growth_cap=8_000, growth_cap_inflation_linked=True,
                end_milestone_id=retire),
        Expense(id=_uid(52), plan_id=plan_id, name="Tuition", annual_amount=20_000, inflation_linked=True,
                recurrence_years=4, recurrence_growth_rate=3, qualified_education=True,
                start_milestone_id=relative, payroll_tax_elections={}),
    ])
    db_session.add_all([
        CashFlowPriority(id=_uid(60), plan_id=plan_id, priority_rank=1, priority_type="pre_tax_contribution",
                         allocation_mode="remaining", target_account_id=k401, source_income_id=salary,
                         employee_rate=10, employer_match_rate=4,
                         employer_match={"tiers": [{"match_percent": 100, "up_to_percent_of_pay": 4}],
                                         "cap_amount": 8_000, "roth": True},
                         limit_mode="custom", custom_annual_limit=20_000, reduce_employer_contribution=True,
                         end_milestone_id=retire),
        CashFlowPriority(id=_uid(61), plan_id=plan_id, priority_rank=2, priority_type="contribution",
                         allocation_mode="amount", allocation_value=7_000, target_account_id=roth,
                         max_annual_amount=7_000, backdoor_roth=True, withdraw_if_short=True,
                         transfer_frequency="monthly"),
        CashFlowPriority(id=_uid(62), plan_id=plan_id, priority_rank=3, priority_type="transfer",
                         allocation_mode="percentage", allocation_value=50, target_account_id=cash,
                         source_account_id=brokerage, target_balance=40_000),
        CashFlowPriority(id=_uid(63), plan_id=plan_id, priority_rank=4, priority_type="roth_conversion",
                         allocation_mode="remaining", source_account_id=k401, target_account_id=roth,
                         conversion_mode="fill_bracket", bracket_ceiling_rate=0.22, magi_cap=200_000,
                         use_plan_tax_target=True, start_milestone_id=retire, end_milestone_id=ss_start),
        CashFlowPriority(id=_uid(64), plan_id=plan_id, priority_rank=5, priority_type="debt_payment",
                         allocation_mode="remaining", target_liability_id=mortgage),
    ])
    db_session.add_all([
        DrawdownOrder(id=_uid(70), plan_id=plan_id, rank=1, source_account_id=cash),
        DrawdownOrder(id=_uid(71), plan_id=plan_id, rank=2, source_account_id=brokerage),
        DrawdownOrder(id=_uid(72), plan_id=plan_id, rank=3, source_account_id=None),
    ])
    db_session.add_all([
        AssumptionCurve(id=_uid(80), plan_id=plan_id, curve_type="inflation", mode="fixed", fixed_rate=0.03,
                        control_points=[]),
        AssumptionCurve(id=_uid(81), plan_id=plan_id, curve_type="market_return", mode="curve",
                        fixed_rate=0.065, control_points=[{"year": 2030, "rate": 0.07}, {"year": 2060, "rate": 0.05}]),
        AssumptionCurve(id=_uid(82), plan_id=plan_id, curve_type="bond_return", mode="fixed", fixed_rate=None,
                        control_points=[]),
        AssumptionCurve(id=_uid(83), plan_id=plan_id, curve_type="cash_yield", mode="fixed", fixed_rate=0.02,
                        control_points=[]),
        AssumptionCurve(id=_uid(84), plan_id=plan_id, curve_type="wage_growth", mode="fixed", fixed_rate=0.5,
                        control_points=[]),
    ])
    db_session.add_all([
        RealAsset(id=home, plan_id=plan_id, name="Home", current_value=800_000, adjusted_basis=500_000,
                  annual_appreciation_rate=0.03, annual_property_tax=8_000, annual_maintenance=6_000,
                  property_tax_rate=0.011, maintenance_rate=0.01, insurance_rate=0.004,
                  is_primary_residence=True, tax_treatment="personal_use",
                  sale_year=2055, sale_month=6, auto_liquidate_on_depletion=True,
                  liquidation_target_account_id=brokerage),
        RealAsset(id=rental, plan_id=plan_id, name="Duplex", current_value=0, annual_appreciation_rate=0.025,
                  annual_property_tax=0, annual_maintenance=0, is_primary_residence=False,
                  tax_treatment="rental", auto_liquidate_on_depletion=False, sale_month=1,
                  purchase_year=2030, purchase_month=4, purchase_price=600_000, down_payment_rate=0.25,
                  closing_costs=12_000, purchase_funding_account_id=brokerage, purchase_loan_rate=6.5,
                  purchase_loan_term_months=360, selling_cost_rate=0.06, rental_income=48_000,
                  rental_income_growth_rate=0.02, rental_expense_rate=0.3, vacancy_rate=0.05,
                  rental_property_class="residential", land_value_rate=0.2, qbi_eligible=True,
                  rental_active_participation=True, suspended_passive_loss=3_000,
                  rental_use_rate=1.0, rental_use_schedule=[{"year": 2040, "rate": 0.5}]),
    ])
    db_session.flush()
    db_session.add_all([
        Liability(id=mortgage, plan_id=plan_id, name="Mortgage", principal_balance=420_000, interest_rate=5.5,
                  term_months=300, payment_type="fixed", extra_payment=200, offset_account_id=cash,
                  linked_asset_id=home, payoff_milestone_id=payoff, interest_method="daily"),
        Liability(id=student_loan, plan_id=plan_id, name="Student loan", principal_balance=30_000,
                  interest_rate=4, monthly_payment=None, payment_type="percent_of_balance", extra_payment=0,
                  forgiveness={"milestone_id": str(relative), "amount": 10_000, "tax_treatment": "excluded",
                               "excluded_amount": 10_000, "exclusion_basis": "pslf"},
                  recurrence_years=10, recurrence_end_year=2060, recurrence_end_milestone_id=ss_start),
    ])
    db_session.add(Spouse(id=_uid(90), plan_id=plan_id, name="Sam", birth_year=1982, birth_month=2,
                          life_expectancy=95, income_streams=[]))
    db_session.add_all([
        CharityEntity(id=_uid(100), plan_id=plan_id, name="Local DAF", entity_type="daf", annual_amount=5_000,
                      start_milestone_id=retire, end_milestone_id=ss_start, source_account_id=brokerage,
                      funding="appreciated_shares"),
        CharityEntity(id=_uid(101), plan_id=plan_id, name="QCD", entity_type="qcd", annual_amount=2_000,
                      source_account_id=inherited, funding="cash"),
    ])
    db_session.add_all([
        ResidencyPeriod(id=_uid(110), plan_id=plan_id, state_code="CA", rank=0, end_milestone_id=retire,
                        local_tax={"kind": "flat", "rate": 1.0}),
        ResidencyPeriod(id=_uid(111), plan_id=plan_id, state_code=None, country="PT", region="LIS", rank=1,
                        start_milestone_id=retire, start_year=2041, end_year=2060),
    ])
    db_session.commit()
    db_session.refresh(plan)
    accounts = db_session.query(CurrentAccount).order_by(CurrentAccount.name).all()
    return plan, accounts


class TestPlanConverterCharacterisation:
    def test_populated_plan_converts_to_recorded_plan_data(self, db_session, test_user):
        plan, accounts = _populated_plan(db_session, test_user)
        data = plan_to_engine_data(plan, accounts, today=datetime.date(2026, 9, 26))

        assert dataclasses.asdict(data) == POPULATED_PLAN_DATA


def test_converter_reads_model_attributes_directly():
    """Every attribute the converter reads exists on its model, so a getattr
    default would only turn a misspelled or renamed column into a silent None."""
    tree = ast.parse(Path(plan_converter.__file__).read_text())
    defaulted = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) == 3
    ]
    assert defaulted == []


# Recorded from plan_to_engine_data before the module was split into per-entity
# builders. Update it only for an intended conversion change.
POPULATED_PLAN_DATA = {
    'plan_id': '00000000-0000-0000-0000-000000000001',
    'birth_year': 1980,
    'filing_status': 'married_filing_jointly',
    'life_expectancy': 92,
    'start_year': 2026,
    'birth_month': 7,
    'filing_status_changes': [{'year': 2050, 'filing_status': 'single'}],
    'first_year_fraction': 0.26575342465753427,
    'milestones': [{'id': '00000000-0000-0000-0000-00000000000a',
                    'name': 'Retirement',
                    'trigger_type': 'age',
                    'trigger_value': 60.0,
                    'trigger_date': None,
                    'metric': None,
                    'expense_multiple': None,
                    'relative_to_id': None,
                    'offset_years': 0,
                    'conditions': None,
                    'resolved_month': None,
                    'is_active': True},
                   {'id': '00000000-0000-0000-0000-00000000000b',
                    'name': 'Social Security',
                    'trigger_type': 'date',
                    'trigger_value': None,
                    'trigger_date': '2047-07-01',
                    'metric': None,
                    'expense_multiple': None,
                    'relative_to_id': None,
                    'offset_years': 0,
                    'conditions': None,
                    'resolved_month': None,
                    'is_active': True},
                   {'id': '00000000-0000-0000-0000-00000000000c',
                    'name': 'Coast',
                    'trigger_type': 'expense_multiple',
                    'trigger_value': None,
                    'trigger_date': None,
                    'metric': 'liquid_net_worth',
                    'expense_multiple': 25.0,
                    'relative_to_id': None,
                    'offset_years': 0,
                    'conditions': None,
                    'resolved_month': None,
                    'is_active': True},
                   {'id': '00000000-0000-0000-0000-00000000000d',
                    'name': 'Sabbatical',
                    'trigger_type': 'conditions',
                    'trigger_value': None,
                    'trigger_date': None,
                    'metric': None,
                    'expense_multiple': None,
                    'relative_to_id': None,
                    'offset_years': 0,
                    'conditions': {'all': [{'metric': 'age', 'op': '>=', 'value': 50}]},
                    'resolved_month': None,
                    'is_active': False},
                   {'id': '00000000-0000-0000-0000-00000000000e',
                    'name': 'Five after retiring',
                    'trigger_type': 'relative',
                    'trigger_value': None,
                    'trigger_date': None,
                    'metric': None,
                    'expense_multiple': None,
                    'relative_to_id': '00000000-0000-0000-0000-00000000000a',
                    'offset_years': 5,
                    'conditions': None,
                    'resolved_month': None,
                    'is_active': True}],
    'income_streams': [{'id': '00000000-0000-0000-0000-00000000001e',
                        'name': 'Salary',
                        'annual_amount': 150000.0,
                        'is_active': True,
                        'start_milestone_id': None,
                        'end_milestone_id': '00000000-0000-0000-0000-00000000000a',
                        'growth_rate': 0.03,
                        'growth_cap': 200000.0,
                        'growth_cap_inflation_linked': True,
                        'withholding_percent': 0.22,
                        'start_month': 3,
                        'end_month': None,
                        'is_social_security': False,
                        'is_earned_income': True,
                        'is_self_employed': False,
                        'owner': 'self',
                        'claiming_age': None,
                        'tax_category': 'employment',
                        'pay_interruption': None,
                        'frequency': 'recurring',
                        'recurrence_years': None,
                        'pension_formula': None,
                        'pia_reflects': 'continued_work',
                        'covered_years_to_date': 35,
                        'ss_benefit_basis': 'amount',
                        'pia_monthly': None,
                        'expected_benefit_percent': None,
                        'ss_worker_income_id': None,
                        'ss_spousal_reduction': None,
                        'ss_aux_offset': None,
                        'growth_schedule': [{'year': 2030, 'rate': 2}],
                        'ex_spouse': None},
                       {'id': '00000000-0000-0000-0000-00000000001f',
                        'name': 'Pension',
                        'annual_amount': 0.0,
                        'is_active': False,
                        'start_milestone_id': '00000000-0000-0000-0000-00000000000a',
                        'end_milestone_id': None,
                        'growth_rate': None,
                        'growth_cap': None,
                        'growth_cap_inflation_linked': False,
                        'withholding_percent': 0.0,
                        'start_month': None,
                        'end_month': None,
                        'is_social_security': False,
                        'is_earned_income': False,
                        'is_self_employed': False,
                        'owner': 'spouse',
                        'claiming_age': None,
                        'tax_category': None,
                        'pay_interruption': None,
                        'frequency': 'once',
                        'recurrence_years': None,
                        'pension_formula': {'multiplier': 1.5, 'years': 25, 'final_salary': 120000},
                        'pia_reflects': 'continued_work',
                        'covered_years_to_date': 35,
                        'ss_benefit_basis': 'amount',
                        'pia_monthly': None,
                        'expected_benefit_percent': None,
                        'ss_worker_income_id': None,
                        'ss_spousal_reduction': None,
                        'ss_aux_offset': None,
                        'growth_schedule': None,
                        'ex_spouse': None},
                       {'id': '00000000-0000-0000-0000-000000000020',
                        'name': 'Social Security',
                        'annual_amount': 30000.0,
                        'is_active': True,
                        'start_milestone_id': '00000000-0000-0000-0000-00000000000b',
                        'end_milestone_id': None,
                        'growth_rate': None,
                        'growth_cap': None,
                        'growth_cap_inflation_linked': False,
                        'withholding_percent': 0.0,
                        'start_month': None,
                        'end_month': 11,
                        'is_social_security': True,
                        'is_earned_income': False,
                        'is_self_employed': True,
                        'owner': 'self',
                        'claiming_age': 67,
                        'tax_category': None,
                        'pay_interruption': None,
                        'frequency': 'recurring',
                        'recurrence_years': None,
                        'pension_formula': None,
                        'pia_reflects': 'current_record',
                        'covered_years_to_date': 22,
                        'ss_benefit_basis': 'pia',
                        'pia_monthly': 2800.0,
                        'expected_benefit_percent': 80.0,
                        'ss_worker_income_id': None,
                        'ss_spousal_reduction': None,
                        'ss_aux_offset': None,
                        'growth_schedule': None,
                        'ex_spouse': {'pia_monthly': 1900, 'divorce_year': 2015}}],
    'expenses': [{'id': '00000000-0000-0000-0000-000000000032',
                  'name': 'Living',
                  'annual_amount': 60000.0,
                  'start_milestone_id': None,
                  'end_milestone_id': None,
                  'inflation_linked': True,
                  'is_payroll_deduction': False,
                  'tied_income_id': None,
                  'specific_funding_source_id': '00000000-0000-0000-0000-000000000014',
                  'start_month': 2,
                  'end_month': 10,
                  'category': 'essential',
                  'growth_rate': None,
                  'growth_cap': None,
                  'growth_cap_inflation_linked': False,
                  'recurrence_years': None,
                  'recurrence_growth_rate': 0.0,
                  'payroll_tax_treatment': 'pre_tax',
                  'specific_funding_source_ids': ['00000000-0000-0000-0000-000000000014',
                                                  '00000000-0000-0000-0000-000000000015'],
                  'discretionary_fraction': 0.25,
                  'qualified_education': False,
                  'payroll_tax_elections': None},
                 {'id': '00000000-0000-0000-0000-000000000033',
                  'name': 'Health premiums',
                  'annual_amount': 4800.0,
                  'start_milestone_id': None,
                  'end_milestone_id': '00000000-0000-0000-0000-00000000000a',
                  'inflation_linked': False,
                  'is_payroll_deduction': True,
                  'tied_income_id': '00000000-0000-0000-0000-00000000001e',
                  'specific_funding_source_id': None,
                  'start_month': None,
                  'end_month': None,
                  'category': None,
                  'growth_rate': 0.05,
                  'growth_cap': 8000.0,
                  'growth_cap_inflation_linked': True,
                  'recurrence_years': None,
                  'recurrence_growth_rate': 0.0,
                  'payroll_tax_treatment': 'after_tax',
                  'specific_funding_source_ids': None,
                  'discretionary_fraction': None,
                  'qualified_education': False,
                  'payroll_tax_elections': {'fica': False, 'state': True}},
                 {'id': '00000000-0000-0000-0000-000000000034',
                  'name': 'Tuition',
                  'annual_amount': 20000.0,
                  'start_milestone_id': '00000000-0000-0000-0000-00000000000e',
                  'end_milestone_id': None,
                  'inflation_linked': True,
                  'is_payroll_deduction': False,
                  'tied_income_id': None,
                  'specific_funding_source_id': None,
                  'start_month': None,
                  'end_month': None,
                  'category': None,
                  'growth_rate': None,
                  'growth_cap': None,
                  'growth_cap_inflation_linked': False,
                  'recurrence_years': 4,
                  'recurrence_growth_rate': 0.03,
                  'payroll_tax_treatment': 'pre_tax',
                  'specific_funding_source_ids': None,
                  'discretionary_fraction': None,
                  'qualified_education': True,
                  'payroll_tax_elections': None}],
    'priorities': [{'priority_rank': 1,
                    'target_account_id': '00000000-0000-0000-0000-000000000016',
                    'max_annual_amount': None,
                    'priority_type': 'pre_tax_contribution',
                    'source_account_id': None,
                    'source_income_id': '00000000-0000-0000-0000-00000000001e',
                    'employee_rate': 0.1,
                    'employer_match_rate': 0.04,
                    'target_balance': None,
                    'allocation_mode': 'remaining',
                    'allocation_value': None,
                    'conversion_mode': 'fixed',
                    'bracket_ceiling_rate': None,
                    'magi_cap': None,
                    'start_milestone_id': None,
                    'end_milestone_id': '00000000-0000-0000-0000-00000000000a',
                    'backdoor_roth': False,
                    'use_plan_tax_target': False,
                    'employer_match': {'tiers': [{'match_percent': 1.0, 'up_to_percent_of_pay': 0.04}],
                                       'cap_amount': 8000.0,
                                       'nonelective_percent': 0.0,
                                       'true_up': True,
                                       'roth': True},
                    'limit_mode': 'custom',
                    'custom_annual_limit': 20000.0,
                    'target_liability_id': None,
                    'withdraw_if_short': False,
                    'reduce_employer_contribution': True,
                    'transfer_frequency': 'annual'},
                   {'priority_rank': 2,
                    'target_account_id': '00000000-0000-0000-0000-000000000017',
                    'max_annual_amount': 7000.0,
                    'priority_type': 'contribution',
                    'source_account_id': None,
                    'source_income_id': None,
                    'employee_rate': 0.0,
                    'employer_match_rate': 0.0,
                    'target_balance': None,
                    'allocation_mode': 'amount',
                    'allocation_value': 7000.0,
                    'conversion_mode': 'fixed',
                    'bracket_ceiling_rate': None,
                    'magi_cap': None,
                    'start_milestone_id': None,
                    'end_milestone_id': None,
                    'backdoor_roth': True,
                    'use_plan_tax_target': False,
                    'employer_match': None,
                    'limit_mode': 'irs',
                    'custom_annual_limit': None,
                    'target_liability_id': None,
                    'withdraw_if_short': True,
                    'reduce_employer_contribution': False,
                    'transfer_frequency': 'monthly'},
                   {'priority_rank': 3,
                    'target_account_id': '00000000-0000-0000-0000-000000000014',
                    'max_annual_amount': None,
                    'priority_type': 'transfer',
                    'source_account_id': '00000000-0000-0000-0000-000000000015',
                    'source_income_id': None,
                    'employee_rate': 0.0,
                    'employer_match_rate': 0.0,
                    'target_balance': 40000.0,
                    'allocation_mode': 'percentage',
                    'allocation_value': 50.0,
                    'conversion_mode': 'fixed',
                    'bracket_ceiling_rate': None,
                    'magi_cap': None,
                    'start_milestone_id': None,
                    'end_milestone_id': None,
                    'backdoor_roth': False,
                    'use_plan_tax_target': False,
                    'employer_match': None,
                    'limit_mode': 'irs',
                    'custom_annual_limit': None,
                    'target_liability_id': None,
                    'withdraw_if_short': False,
                    'reduce_employer_contribution': False,
                    'transfer_frequency': 'annual'},
                   {'priority_rank': 4,
                    'target_account_id': '00000000-0000-0000-0000-000000000017',
                    'max_annual_amount': None,
                    'priority_type': 'roth_conversion',
                    'source_account_id': '00000000-0000-0000-0000-000000000016',
                    'source_income_id': None,
                    'employee_rate': 0.0,
                    'employer_match_rate': 0.0,
                    'target_balance': None,
                    'allocation_mode': 'remaining',
                    'allocation_value': None,
                    'conversion_mode': 'fill_bracket',
                    'bracket_ceiling_rate': 0.22,
                    'magi_cap': 200000.0,
                    'start_milestone_id': '00000000-0000-0000-0000-00000000000a',
                    'end_milestone_id': '00000000-0000-0000-0000-00000000000b',
                    'backdoor_roth': False,
                    'use_plan_tax_target': True,
                    'employer_match': None,
                    'limit_mode': 'irs',
                    'custom_annual_limit': None,
                    'target_liability_id': None,
                    'withdraw_if_short': False,
                    'reduce_employer_contribution': False,
                    'transfer_frequency': 'annual'},
                   {'priority_rank': 5,
                    'target_account_id': None,
                    'max_annual_amount': None,
                    'priority_type': 'debt_payment',
                    'source_account_id': None,
                    'source_income_id': None,
                    'employee_rate': 0.0,
                    'employer_match_rate': 0.0,
                    'target_balance': None,
                    'allocation_mode': 'remaining',
                    'allocation_value': None,
                    'conversion_mode': 'fixed',
                    'bracket_ceiling_rate': None,
                    'magi_cap': None,
                    'start_milestone_id': None,
                    'end_milestone_id': None,
                    'backdoor_roth': False,
                    'use_plan_tax_target': False,
                    'employer_match': None,
                    'limit_mode': 'irs',
                    'custom_annual_limit': None,
                    'target_liability_id': '00000000-0000-0000-0000-00000000002a',
                    'withdraw_if_short': False,
                    'reduce_employer_contribution': False,
                    'transfer_frequency': 'annual'}],
    'drawdown_order': [{'rank': 1, 'source_account_id': '00000000-0000-0000-0000-000000000014'},
                       {'rank': 2, 'source_account_id': '00000000-0000-0000-0000-000000000015'},
                       {'rank': 3, 'source_account_id': None}],
    'assumptions': {'inflation_rate': 0.03,
                    'stock_growth_rate': 0.065,
                    'bond_return_rate': 0.04,
                    'stock_dividend_yield': 0.0,
                    'cash_yield_rate': 0.02},
    'assumption_curves': [{'curve_type': 'inflation',
                           'mode': 'fixed',
                           'fixed_rate': 0.03,
                           'control_points': []},
                          {'curve_type': 'market_return',
                           'mode': 'curve',
                           'fixed_rate': 0.065,
                           'control_points': [{'year': 2030, 'rate': 0.07}, {'year': 2060, 'rate': 0.05}]},
                          {'curve_type': 'bond_return',
                           'mode': 'fixed',
                           'fixed_rate': None,
                           'control_points': []},
                          {'curve_type': 'cash_yield',
                           'mode': 'fixed',
                           'fixed_rate': 0.02,
                           'control_points': []},
                          {'curve_type': 'wage_growth',
                           'mode': 'fixed',
                           'fixed_rate': 0.5,
                           'control_points': []}],
    'accounts': {'00000000-0000-0000-0000-000000000016': {'balance': 400000.0,
                                                          'account_type': 'traditional_401k',
                                                          'cost_basis': None,
                                                          'inherited_year': None,
                                                          'owner': 'self',
                                                          'beneficiary_type': 'non_edb',
                                                          'name': '401k',
                                                          'inheritance_settings': None,
                                                          'roth_settings': None,
                                                          'investment_settings': None,
                                                          'withdrawal_lock': {'until_age': 55},
                                                          'distribution_settings': {'rmd': True},
                                                          'state_taxed_basis': None,
                                                          'intl_account_kind': None,
                                                          'include_in_liquid': None},
                 '00000000-0000-0000-0000-000000000015': {'balance': 250000.0,
                                                          'account_type': 'taxable_brokerage',
                                                          'cost_basis': 150000.0,
                                                          'inherited_year': None,
                                                          'owner': 'self',
                                                          'beneficiary_type': 'non_edb',
                                                          'name': 'Brokerage',
                                                          'inheritance_settings': None,
                                                          'roth_settings': None,
                                                          'investment_settings': {'allocation': {'stocks': 80,
                                                                                                 'bonds': 20}},
                                                          'withdrawal_lock': None,
                                                          'distribution_settings': None,
                                                          'state_taxed_basis': 160000.0,
                                                          'intl_account_kind': None,
                                                          'include_in_liquid': None},
                 '00000000-0000-0000-0000-000000000014': {'balance': 30000.0,
                                                          'account_type': 'savings',
                                                          'cost_basis': None,
                                                          'inherited_year': None,
                                                          'owner': 'joint',
                                                          'beneficiary_type': 'non_edb',
                                                          'name': 'Cash',
                                                          'inheritance_settings': None,
                                                          'roth_settings': None,
                                                          'investment_settings': None,
                                                          'withdrawal_lock': None,
                                                          'distribution_settings': None,
                                                          'state_taxed_basis': None,
                                                          'intl_account_kind': None,
                                                          'include_in_liquid': True},
                 '00000000-0000-0000-0000-000000000018': {'balance': 120000.0,
                                                          'account_type': 'traditional_ira',
                                                          'cost_basis': None,
                                                          'inherited_year': 2022,
                                                          'owner': 'self',
                                                          'beneficiary_type': 'edb',
                                                          'name': 'Inherited IRA',
                                                          'inheritance_settings': {'decedent_rmd_started': True},
                                                          'roth_settings': None,
                                                          'investment_settings': None,
                                                          'withdrawal_lock': None,
                                                          'distribution_settings': None,
                                                          'state_taxed_basis': None,
                                                          'intl_account_kind': 'us_ira',
                                                          'include_in_liquid': None},
                 '00000000-0000-0000-0000-000000000017': {'balance': 90000.0,
                                                          'account_type': 'roth_ira',
                                                          'cost_basis': None,
                                                          'inherited_year': None,
                                                          'owner': 'spouse',
                                                          'beneficiary_type': 'non_edb',
                                                          'name': 'Roth',
                                                          'inheritance_settings': None,
                                                          'roth_settings': {'contribution_basis': 40000},
                                                          'investment_settings': None,
                                                          'withdrawal_lock': None,
                                                          'distribution_settings': None,
                                                          'state_taxed_basis': None,
                                                          'intl_account_kind': None,
                                                          'include_in_liquid': None}},
    'real_assets': [{'id': '00000000-0000-0000-0000-000000000028',
                     'name': 'Home',
                     'current_value': 800000.0,
                     'annual_appreciation_rate': 0.03,
                     'annual_property_tax': 8000.0,
                     'annual_maintenance': 6000.0,
                     'property_tax_rate': 0.011,
                     'maintenance_rate': 0.01,
                     'insurance_rate': 0.004,
                     'sale_year': 2055,
                     'sale_month': 6,
                     'is_primary_residence': True,
                     'auto_liquidate_on_depletion': True,
                     'liquidation_target_account_id': '00000000-0000-0000-0000-000000000015',
                     'adjusted_basis': 500000.0,
                     'tax_treatment': 'personal_use',
                     'purchase_year': None,
                     'purchase_month': 1,
                     'purchase_price': None,
                     'down_payment_amount': None,
                     'down_payment_rate': None,
                     'closing_costs': 0.0,
                     'purchase_funding_account_id': None,
                     'purchase_loan_rate': None,
                     'purchase_loan_term_months': None,
                     'selling_cost_rate': 0.0,
                     'rental_income': 0.0,
                     'rental_income_growth_rate': None,
                     'rental_expenses': 0.0,
                     'rental_expense_rate': None,
                     'vacancy_rate': 0.0,
                     'rental_property_class': 'residential',
                     'land_value_rate': None,
                     'building_basis': None,
                     'prior_depreciation': 0.0,
                     'qbi_eligible': False,
                     'rental_active_participation': True,
                     'suspended_passive_loss': 0.0,
                     'owned_since_year': None,
                     'owned_since_month': None,
                     'primary_residence_since_year': None,
                     'primary_residence_since_month': None,
                     'rental_use_rate': None,
                     'rental_use_schedule': ()},
                    {'id': '00000000-0000-0000-0000-000000000029',
                     'name': 'Duplex',
                     'current_value': 0.0,
                     'annual_appreciation_rate': 0.025,
                     'annual_property_tax': 0.0,
                     'annual_maintenance': 0.0,
                     'property_tax_rate': None,
                     'maintenance_rate': None,
                     'insurance_rate': None,
                     'sale_year': None,
                     'sale_month': 1,
                     'is_primary_residence': False,
                     'auto_liquidate_on_depletion': False,
                     'liquidation_target_account_id': None,
                     'adjusted_basis': None,
                     'tax_treatment': 'rental',
                     'purchase_year': 2030,
                     'purchase_month': 4,
                     'purchase_price': 600000.0,
                     'down_payment_amount': None,
                     'down_payment_rate': 0.25,
                     'closing_costs': 12000.0,
                     'purchase_funding_account_id': '00000000-0000-0000-0000-000000000015',
                     'purchase_loan_rate': 0.065,
                     'purchase_loan_term_months': 360,
                     'selling_cost_rate': 0.06,
                     'rental_income': 48000.0,
                     'rental_income_growth_rate': 0.02,
                     'rental_expenses': 0.0,
                     'rental_expense_rate': 0.3,
                     'vacancy_rate': 0.05,
                     'rental_property_class': 'residential',
                     'land_value_rate': 0.2,
                     'building_basis': None,
                     'prior_depreciation': 0.0,
                     'qbi_eligible': True,
                     'rental_active_participation': True,
                     'suspended_passive_loss': 3000.0,
                     'owned_since_year': None,
                     'owned_since_month': None,
                     'primary_residence_since_year': None,
                     'primary_residence_since_month': None,
                     'rental_use_rate': 1.0,
                     'rental_use_schedule': ((2040, 0.5),)}],
    'liabilities': [{'id': '00000000-0000-0000-0000-00000000002a',
                     'name': 'Mortgage',
                     'principal_balance': 420000.0,
                     'interest_rate': 0.055,
                     'term_months': 300,
                     'monthly_payment': 2582.230191187803,
                     'payment_type': 'fixed',
                     'extra_payment': 200.0,
                     'offset_account_id': '00000000-0000-0000-0000-000000000014',
                     'linked_asset_id': '00000000-0000-0000-0000-000000000028',
                     'payoff_milestone_id': '00000000-0000-0000-0000-00000000000c',
                     'forgiveness': None,
                     'interest_method': 'daily',
                     'recurrence_years': None,
                     'recurrence_end_year': None,
                     'recurrence_end_milestone_id': None},
                    {'id': '00000000-0000-0000-0000-00000000002b',
                     'name': 'Student loan',
                     'principal_balance': 30000.0,
                     'interest_rate': 0.04,
                     'term_months': None,
                     'monthly_payment': None,
                     'payment_type': 'percent_of_balance',
                     'extra_payment': 0.0,
                     'offset_account_id': None,
                     'linked_asset_id': None,
                     'payoff_milestone_id': None,
                     'forgiveness': {'year': None,
                                     'milestone_id': '00000000-0000-0000-0000-00000000000e',
                                     'amount': 10000.0,
                                     'tax_treatment': 'excluded',
                                     'excluded_amount': 10000.0,
                                     'exclusion_basis': 'pslf'},
                     'interest_method': 'monthly',
                     'recurrence_years': 10,
                     'recurrence_end_year': 2060,
                     'recurrence_end_milestone_id': '00000000-0000-0000-0000-00000000000b'}],
    'spouse_birth_year': 1982,
    'spouse_birth_month': 2,
    'spouse_life_expectancy': 95,
    'sepp_settings': {'enabled': True,
                      'source_account_id': '00000000-0000-0000-0000-000000000016',
                      'method': 'rmd',
                      'start_age': 52.5,
                      'interest_rate': 0.045,
                      'annual_amount': 18000.0},
    'cash_reserve': {'account_ids': ('00000000-0000-0000-0000-000000000014',),
                     'amount': 25000.0,
                     'sweep_excess': True},
    'state_code': 'CA',
    'local_tax': {'kind': 'flat', 'rate': 1.5},
    'residency_periods': [{'state_code': 'CA',
                           'start_milestone_id': None,
                           'end_milestone_id': '00000000-0000-0000-0000-00000000000a',
                           'start_year': None,
                           'end_year': None,
                           'rank': 0,
                           'local_tax': {'kind': 'flat', 'rate': 1.0},
                           'country': None,
                           'region': None},
                          {'state_code': None,
                           'start_milestone_id': '00000000-0000-0000-0000-00000000000a',
                           'end_milestone_id': None,
                           'start_year': 2041,
                           'end_year': 2060,
                           'rank': 1,
                           'local_tax': None,
                           'country': 'PT',
                           'region': 'LIS'}],
    'charity_entities': [{'id': '00000000-0000-0000-0000-000000000064',
                          'name': 'Local DAF',
                          'entity_type': 'daf',
                          'annual_amount': 5000.0,
                          'start_milestone_id': '00000000-0000-0000-0000-00000000000a',
                          'end_milestone_id': '00000000-0000-0000-0000-00000000000b',
                          'source_account_id': '00000000-0000-0000-0000-000000000015',
                          'funding': 'appreciated_shares'},
                         {'id': '00000000-0000-0000-0000-000000000065',
                          'name': 'QCD',
                          'entity_type': 'qcd',
                          'annual_amount': 2000.0,
                          'start_milestone_id': None,
                          'end_milestone_id': None,
                          'source_account_id': '00000000-0000-0000-0000-000000000018',
                          'funding': 'cash'}],
    'estate_settings': {'step_up_basis_on_death': False,
                        'filing_status_after_death': 'qualifying_surviving_spouse',
                        'federal_estate_exemption': 7000000.0,
                        'state_estate_tax_enabled': True,
                        'state_estate_exemption': 2000000.0,
                        'state_estate_tax_rate': 0.16,
                        'custom_federal_exemption_enabled': True,
                        'portability_election': False,
                        'settlement_cost_fixed': 5000.0,
                        'settlement_cost_rate': 0.02,
                        'heir_income_tax_rate': 0.24,
                        'household_lifecycle': 'survivor',
                        'survivor_social_security_policy': 'auto',
                        'survivor_social_security_eligibility_confirmed': True,
                        'survivor_social_security_eligibility_source': 'user',
                        'heir_capital_gains_rate': 0.0,
                        'estate_selling_cost_rate': 0.06,
                        'charitable_bequest_rate': 0.1,
                        'joint_account_step_up': True},
    'spending_rules': {'flex_threshold': -0.1,
                       'flex_reduction': 0.25,
                       'lookback_years': 2,
                       'spending_floor': 0.7,
                       'performance_mode': 'all_time_high',
                       'interpolation': 'linear',
                       'thresholds': [{'threshold': -0.1, 'reduction': 0.1},
                                      {'threshold': -0.2, 'reduction': 0.3}],
                       'start_milestone_id': '00000000-0000-0000-0000-00000000000a',
                       'end_milestone_id': '00000000-0000-0000-0000-00000000000c',
                       'upside_thresholds': [{'threshold': 0.2, 'increase': 0.05}],
                       'flex_scope': ['expenses', 'contributions'],
                       'surplus_mode': 'spend'},
    'tax_settings': {'target_bracket': 0.22, 'itemize': True},
    'healthcare_settings': {'pre_medicare': 'aca', 'premium': 9000},
    'withdrawal_strategy': {'method': 'guyton_klinger',
                            'initial_rate': 0.045,
                            'start_milestone_id': '00000000-0000-0000-0000-00000000000a',
                            'start_age': None,
                            'upper_guardrail': 1.2,
                            'lower_guardrail': 0.8,
                            'guardrail_adjustment': 0.1,
                            'guardrail_freeze_years': 15,
                            'floor': -0.025,
                            'ceiling': 0.05,
                            'fixed_amount': 0.0,
                            'fixed_amount_inflation_adjusted': True,
                            'vpw_stock_return': 0.05,
                            'vpw_bond_return': 0.019,
                            'ratchet_threshold': 1.5,
                            'ratchet_increase': 0.1,
                            'ratchet_cooldown_years': 3,
                            'clyatt_floor': 0.95,
                            'minimum': {'amount': 40000.0, 'unit': 'today_dollars'},
                            'maximum': {'amount': 150000.0, 'unit': 'nominal'},
                            'income_handling': 'replace_expenses'},
    'tax_country': 'US',
    'tax_region': 'CA',
    'currency': 'USD',
    'intl_settings': {'treaty': 'none', 'pension_scheme': 'us'},
}
