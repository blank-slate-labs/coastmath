"""Tests for percent-to-decimal unit conversion in the two PlanData paths.

Task 31.2.4: Ensures growth_rate and withholding_percent are converted from
wire-format percent (e.g. 3 = 3%) to engine-format decimal fraction (0.03)
in both the stateless (request_to_engine_data) and DB (plan_converter) paths.
"""

from __future__ import annotations

import uuid

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    IncomeData,
    PlanData,
)
from coastmath.schemas.plan_data_request import (
    AssumptionRequest,
    ExpenseRequest,
    IncomeRequest,
    MilestoneRequest,
    PlanDataRequest,
    PriorityRequest,
    RealAssetRequest,
    TaxSettingsRequest,
    request_to_engine_data,
)

# ---------------------------------------------------------------------------
# request_to_engine_data: percent → decimal conversion
# ---------------------------------------------------------------------------


class TestRequestToEngineConversion:
    """Verify that request_to_engine_data divides percent fields by 100."""

    def _make_request(self, **income_overrides) -> PlanDataRequest:
        income_defaults = dict(
            id="inc1",
            name="Salary",
            annual_amount=100_000,
            growth_rate=0.0,
            withholding_percent=0.0,
        )
        income_defaults.update(income_overrides)
        return PlanDataRequest(
            plan_id=uuid.uuid4(),
            birth_year=1990,
            start_year=2025,
            income_streams=[IncomeRequest(**income_defaults)],
        )

    def test_growth_rate_percent_to_decimal(self):
        """growth_rate=3 (3%) on the wire → 0.03 in engine IncomeData."""
        req = self._make_request(growth_rate=3.0)
        plan = request_to_engine_data(req)
        assert plan.income_streams[0].growth_rate == pytest.approx(0.03)

    def test_withholding_percent_to_decimal(self):
        """withholding_percent=20 (20%) on the wire → 0.20 in engine IncomeData."""
        req = self._make_request(withholding_percent=20.0)
        plan = request_to_engine_data(req)
        assert plan.income_streams[0].withholding_percent == pytest.approx(0.20)

    def test_zero_values_stay_zero(self):
        """Zero percent stays zero after division."""
        req = self._make_request(growth_rate=0.0, withholding_percent=0.0)
        plan = request_to_engine_data(req)
        assert plan.income_streams[0].growth_rate == 0.0
        assert plan.income_streams[0].withholding_percent == 0.0

    def test_combined_conversion(self):
        """Both fields convert correctly in the same request."""
        req = self._make_request(growth_rate=5.0, withholding_percent=25.0)
        plan = request_to_engine_data(req)
        assert plan.income_streams[0].growth_rate == pytest.approx(0.05)
        assert plan.income_streams[0].withholding_percent == pytest.approx(0.25)

    def test_math_inputs_reach_engine(self):
        request = PlanDataRequest(
            plan_id=uuid.uuid4(),
            birth_year=1990,
            start_year=2026,
            first_year_fraction=0.25,
            milestones=[
                MilestoneRequest(
                    id="fi",
                    name="FI",
                    trigger_type="expense_multiple",
                    metric="liquid_net_worth",
                    expense_multiple=20,
                ),
            ],
            income_streams=[
                IncomeRequest(
                    id="salary",
                    name="Salary",
                    annual_amount=120_000,
                    growth_rate=3.5,
                    growth_cap=170_000,
                    growth_cap_inflation_linked=True,
                ),
            ],
            expenses=[
                ExpenseRequest(
                    id="roof",
                    name="Roof replacement",
                    annual_amount=40_000,
                    inflation_linked=False,
                    growth_rate=5,
                    growth_cap=60_000,
                    growth_cap_inflation_linked=True,
                    recurrence_years=15,
                    recurrence_growth_rate=10,
                ),
            ],
            priorities=[
                PriorityRequest(
                    priority_rank=1,
                    target_account_id="401k",
                    priority_type="income_percent",
                    source_income_id="salary",
                    employee_rate=12,
                    employer_match_rate=5,
                    target_balance=40_000,
                ),
            ],
            assumptions=AssumptionRequest(
                inflation_rate=0.03,
                stock_growth_rate=0.055,
                bond_return_rate=0.05,
                stock_dividend_yield=0.02,
                cash_yield_rate=0.0005,
            ),
            real_assets=[
                RealAssetRequest(
                    id="car",
                    name="Car",
                    current_value=22_000,
                    annual_appreciation_rate=-0.12,
                    property_tax_rate=0.015,
                    maintenance_rate=0.03,
                    insurance_rate=0.02,
                    sale_year=2037,
                    sale_month=1,
                ),
            ],
            tax_settings=TaxSettingsRequest(
                mode="flat",
                ordinary_income_tax_rate=0.24,
                capital_gains_tax_rate=0.20,
                taxable_withholding_rate=0.12,
                tax_deferred_withholding_rate=0.22,
                settlement_lag_years=1,
                cash_flow_frequency="monthly",
                withdrawal_cash_flow_frequency="annual",
            ),
        )

        plan = request_to_engine_data(request)

        assert plan.first_year_fraction == pytest.approx(0.25)
        assert plan.milestones[0].expense_multiple == 20
        assert plan.income_streams[0].growth_rate == pytest.approx(0.035)
        assert plan.income_streams[0].growth_cap == 170_000
        assert plan.income_streams[0].growth_cap_inflation_linked is True
        assert plan.expenses[0].growth_rate == pytest.approx(0.05)
        assert plan.expenses[0].growth_cap_inflation_linked is True
        assert plan.expenses[0].recurrence_growth_rate == pytest.approx(0.10)
        assert plan.priorities[0].employee_rate == pytest.approx(0.12)
        assert plan.priorities[0].employer_match_rate == pytest.approx(0.05)
        assert plan.assumptions.stock_dividend_yield == pytest.approx(0.02)
        assert plan.assumptions.cash_yield_rate == pytest.approx(0.0005)
        assert plan.real_assets[0].property_tax_rate == pytest.approx(0.015)
        assert plan.real_assets[0].sale_year == 2037
        assert plan.tax_settings == {
            "ca_dependents_by_year": {},
            "oh_dependents_by_year": {},
            "dependent_birth_years": [],
            "mode": "flat",
            "ordinary_income_tax_rate": 0.24,
            "capital_gains_tax_rate": 0.20,
            "taxable_withholding_rate": 0.12,
            "tax_deferred_withholding_rate": 0.22,
            "settlement_lag_years": 1,
            "cash_flow_frequency": "monthly",
            "withdrawal_cash_flow_frequency": "annual",
            "capital_loss_carryforward": 0,
            "mfs_lived_apart_all_year": False,
            "hsa_coverage": [],
            "state_payroll_coverage": [],
            "state_payroll_paid_year_to_date": {},
            "state_payroll_wages_year_to_date": {},
        }


# ---------------------------------------------------------------------------
# Simulator-level: withholding_percent produces correct tax_withheld
# ---------------------------------------------------------------------------


class TestWithholdingSimulator:
    """Verify the engine correctly withholds based on decimal fraction."""

    def test_withholding_amount(self):
        """$100k income with withholding_percent=0.20 → $20k withheld."""
        plan = PlanData(
            plan_id="00000000-0000-4000-8000-000000000099",
            birth_year=1990,
            filing_status="single",
            life_expectancy=92,
            start_year=2025,
            assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0),
            income_streams=[
                IncomeData(
                    id="job",
                    name="Job",
                    annual_amount=100_000,
                    withholding_percent=0.20,
                ),
            ],
            accounts={"chk": AccountInfo(balance=10_000, account_type="checking")},
        )
        result = run_simulation(plan)
        snap = result.yearly_snapshots[0]
        cf = snap.cash_flow
        assert cf is not None
        assert cf.tax_withheld == pytest.approx(20_000)
