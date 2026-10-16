"""Tax-engine hooks for the statutory state deduction rules evaluator.

The evaluator's statutory results are tested with its own module. These tests
replace it with a stub that follows the shared context/result contract, and
check the integration: opt-in and coverage gating, what the context carries,
how each result component changes the state base, preserved Ohio exemption
tiers, the federal SALT / state federal-tax feedback and surfaced caveats.
"""
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from coastmath.engine import state_rules_bridge
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_adjustments import ResolvedAdjustment, YearAdjustments
from coastmath.engine.tax_engine import _state_tax_details, calculate
from coastmath.engine.types import AccountInfo, AssumptionData, IncomeData, PlanData


@dataclass(frozen=True)
class ItemizedCategories:
    state_local_income_tax: float = 0.0
    real_estate_tax: float = 0.0
    personal_property_tax: float = 0.0
    mortgage_interest: float = 0.0
    charitable_cash: float = 0.0
    charitable_property: float = 0.0
    medical_expenses: float = 0.0
    other: float = 0.0


@dataclass(frozen=True)
class StateDeductionContext:
    state_code: str
    tax_year: int
    inflation_factor: float
    filing_status: str
    holder_age: int | None
    spouse_age: int | None
    dependent_count: int
    federal_agi: float
    state_agi: float
    itemized: ItemizedCategories
    federal_itemized_elected: bool
    federal_itemized_total: float
    federal_standard_deduction: float
    federal_income_tax_liability: float
    federal_income_tax_paid: float | None = None
    federal_income_tax_refund_received: float | None = None


@dataclass(frozen=True)
class StateDeductionResult:
    supported: bool
    coverage: str
    use_itemized: bool
    deduction: float
    exemption_deduction: float
    federal_tax_subtraction: float
    nonrefundable_credit: float
    source_year: int
    diagnostics: tuple[str, ...] = ()


@dataclass
class Stub:
    supported: frozenset = frozenset({"GA", "OH"})
    rule: object = None
    contexts: list = field(default_factory=list)

    def module(self):
        def evaluate(ctx):
            self.contexts.append(ctx)
            return self.rule(ctx)

        return SimpleNamespace(
            ItemizedCategories=ItemizedCategories, StateDeductionContext=StateDeductionContext,
            StateDeductionResult=StateDeductionResult, evaluate_state_deductions=evaluate,
            state_rule_coverage=lambda code: "supported" if code in self.supported else "unverified",
        )


def result(deduction=0.0, exemption=0.0, subtraction=0.0, credit=0.0, diagnostics=()):
    return StateDeductionResult(True, "supported", False, deduction, exemption, subtraction, credit, 2025,
                                tuple(diagnostics))


@pytest.fixture
def stub(monkeypatch):
    rules = Stub(rule=lambda ctx: result(20_000))
    module = rules.module()
    monkeypatch.setattr(state_rules_bridge, "evaluator", lambda: module)
    return rules


ON = {"state_deduction_rules": True}
WAGES = dict(gross_income=150_000.0, deductions=0.0, filing_status="single", tax_year=2026,
             earned_income=150_000.0, holder_age=50)


def test_rules_run_only_when_opted_in_and_supported(stub):
    off = calculate(**WAGES, state_code="GA")
    assert stub.contexts == [] and off.state_deduction_coverage == ""
    unverified = calculate(**WAGES, state_code="NC", settings=ON)
    assert stub.contexts == []
    assert unverified.state == calculate(**WAGES, state_code="NC").state
    assert unverified.state_deduction_coverage == "unverified"
    assert any("NC" in note for note in unverified.tax_adjustment_diagnostics)
    custom = calculate(**WAGES, state_code="GA", settings={**ON, "state_brackets": [[999_999_999, .05]]})
    assert stub.contexts == [] and custom.state_deduction_coverage == "legacy"
    supported = calculate(**WAGES, state_code="GA", settings=ON)
    assert supported.state_deduction_coverage == "supported" and len(stub.contexts) == 1


def test_missing_rules_module_keeps_every_state_legacy(monkeypatch):
    monkeypatch.setattr(state_rules_bridge, "evaluator", lambda: None)
    assert state_rules_bridge.coverage("GA") == "legacy"
    with_flag = calculate(**WAGES, state_code="GA", settings=ON)
    assert with_flag.state == calculate(**WAGES, state_code="GA").state


def test_context_separates_raw_categories_federal_result_and_income_tax_liability(stub):
    items = {"salt": 60_000.0, "property_tax": 9_000.0, "mortgage_interest": 25_000.0}
    adjustments = YearAdjustments((ResolvedAdjustment("o", "o", "deduction", "state", "itemized", amount=1_234),))
    taxed = calculate(**WAGES, state_code="GA", settings={**ON, "dependent_birth_years": [2010, 2020, 2000]},
                      itemized_deductions=items, charitable_deduction=2_000, medical_expenses=7_000,
                      net_investment_income=300_000, capital_gains=300_000, adjustments=adjustments)
    ctx = stub.contexts[-1]
    # Raw amounts before the federal SALT cap and the medical AGI floor.
    assert ctx.itemized.state_local_income_tax == 60_000 and ctx.itemized.real_estate_tax == 9_000
    assert ctx.itemized.mortgage_interest == 25_000 and ctx.itemized.charitable_cash == 2_000
    assert ctx.itemized.medical_expenses == 7_000 and ctx.itemized.other == pytest.approx(1_234)
    assert ctx.federal_itemized_elected and ctx.federal_itemized_total == pytest.approx(taxed.deduction_amount)
    assert ctx.federal_itemized_total < 60_000 + 9_000 + 25_000
    # Regular tax, AMT and capital gains tax; never payroll tax or NIIT.
    assert taxed.niit > 0 and taxed.fica_tax > 0
    assert ctx.federal_income_tax_liability == pytest.approx(taxed.federal + taxed.capital_gains_tax)
    assert ctx.federal_income_tax_paid is None and ctx.federal_income_tax_refund_received is None
    assert ctx.federal_agi == pytest.approx(taxed.modified_agi)
    assert ctx.dependent_count == 2 and ctx.filing_status == "single" and ctx.holder_age == 50


def test_result_components_replace_the_built_in_deduction():
    agi = 100_000.0
    legacy = _state_tax_details(agi, "GA", tax_year=2026)
    assert legacy.taxable == pytest.approx(agi - 15_000)
    seen = []

    def rule(state_agi, before_exclusions):
        seen.append((state_agi, before_exclusions))
        return result(deduction=20_000, exemption=3_000, subtraction=4_000)

    replaced = _state_tax_details(agi, "GA", tax_year=2026, deduction_rule=rule)
    assert seen == [(agi, agi)]
    assert replaced.taxable == pytest.approx(agi - 27_000)
    unsupported = _state_tax_details(agi, "GA", tax_year=2026, deduction_rule=lambda *_: StateDeductionResult(
        False, "legacy", False, 0, 0, 0, 0, 2025))
    assert unsupported.taxable == legacy.taxable and unsupported.rule is None


def test_rules_credit_is_nonrefundable():
    agi = 60_000.0
    legacy = _state_tax_details(agi, "GA", tax_year=2026)
    credited = _state_tax_details(agi, "GA", tax_year=2026,
                                  deduction_rule=lambda *_: result(deduction=15_000, credit=500))
    assert credited.tax == pytest.approx(legacy.tax - 500)
    floored = _state_tax_details(agi, "GA", tax_year=2026,
                                 deduction_rule=lambda *_: result(deduction=15_000, credit=1e9))
    assert floored.tax == 0 and floored.refund == 0


def test_ohio_exemption_tiers_stay_in_place():
    kwargs = dict(tax_year=2026, oh_exemption_eligible_owners=["self"])
    legacy = _state_tax_details(50_000.0, "OH", **kwargs)
    ruled = _state_tax_details(50_000.0, "OH", **kwargs, deduction_rule=lambda *_: result())
    no_exemption = _state_tax_details(50_000.0, "OH", tax_year=2026, deduction_rule=lambda *_: result())
    assert ruled.taxable == pytest.approx(legacy.taxable)
    assert ruled.taxable < no_exemption.taxable


def test_federal_salt_and_state_federal_tax_subtraction_reach_a_fixed_point(stub):
    # The state deducts all federal income tax; the federal return deducts
    # state tax as SALT. Iterate the way the projection does (<= 5 passes).
    stub.rule = lambda ctx: result(deduction=5_000, subtraction=ctx.federal_income_tax_liability)
    items = {"property_tax": 12_000.0, "mortgage_interest": 30_000.0}
    estimate, deltas = 0.0, []
    for _ in range(5):
        taxed = calculate(**WAGES, state_code="GA", settings=ON,
                          itemized_deductions={**items, "salt": estimate})
        deltas.append(abs(taxed.state - estimate))
        if deltas[-1] < 1.0:
            break
        estimate = taxed.state
    assert deltas[-1] < 1.0
    ctx = stub.contexts[-1]
    assert taxed.state_federal_tax_subtraction == pytest.approx(ctx.federal_income_tax_liability)
    assert taxed.deduction_used == "itemized"


def test_projection_opt_in_surfaces_rule_diagnostics_and_changes_only_opted_plans(stub):
    stub.rule = lambda ctx: result(deduction=30_000, diagnostics=("Federal tax paid estimated from liability.",))
    plan = dict(plan_id="00000000-0000-0000-0000-0000000000b1", birth_year=1970, start_year=2026,
                life_expectancy=60, filing_status="single", state_code="GA",
                income_streams=[IncomeData("w", "Wages", 120_000, growth_rate=0.0, withholding_percent=.25)],
                accounts={"cash": AccountInfo(10_000, "checking")},
                assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0,
                                           stock_dividend_yield=0))
    base = run_simulation(PlanData(**plan, tax_settings={"cash_flow_frequency": "annual"}))
    assert stub.contexts == []
    ruled = run_simulation(PlanData(**plan, tax_settings={"cash_flow_frequency": "annual", **ON}))
    assert ruled.yearly_snapshots[0].state_tax < base.yearly_snapshots[0].state_tax
    assert "Federal tax paid estimated from liability." in ruled.metadata.warnings
