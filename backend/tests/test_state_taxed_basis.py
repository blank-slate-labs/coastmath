"""Recovery of retirement contributions a state taxed when they were made.

Pennsylvania (cost recovery), Massachusetts (contributions recovered first)
and New Jersey (IRA worksheet pro-rata) exclude previously taxed
contributions from distributions. Sources: `_sources` in `tax_brackets_2026.json`.
"""

import pytest

from coastmath.engine.simulator import (
    _state_taxed_contributions_by_account,
    run_simulation,
)
from coastmath.engine.state_retirement_exclusion import RetirementIncome
from coastmath.engine.state_taxed_basis import (
    basis_distributions,
    basis_recovery_by_account,
    commit_year,
    recovery_method,
)
from coastmath.engine.tax_engine import calculate
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    ExpenseData,
    PlanData,
    SimState,
)

PA_RATE = 0.0307


def _state(distributed=10_000.0, basis=None, balance=90_000.0):
    state = SimState(year=2026, accounts={"ira": AccountInfo(balance=balance, account_type="traditional_ira")})
    state.retirement_distributions_this_year = {"ira": distributed}
    state.state_taxed_basis = {"ira": basis or {}}
    return state


def test_methods_come_from_data():
    assert recovery_method("PA") == "cost_recovery"
    assert recovery_method("MA") == "cost_recovery"
    assert recovery_method("NJ") == "pro_rata"
    assert recovery_method("CA") is None


def test_cost_recovery_takes_basis_first():
    assert basis_recovery_by_account(_state(basis={"PA": 25_000}), "PA") == {"ira": 10_000}
    assert basis_recovery_by_account(_state(basis={"PA": 4_000}), "PA") == {"ira": 4_000}


def test_new_jersey_pro_rata_uses_year_end_value_plus_distributions():
    # $10,000 x $25,000 / ($90,000 + $10,000) = $2,500.
    assert basis_recovery_by_account(_state(basis={"NJ": 25_000}), "NJ") == {"ira": pytest.approx(2_500)}


def test_recovery_only_in_the_state_that_taxed_the_contributions():
    state = _state(basis={"PA": 25_000})
    assert basis_recovery_by_account(state, "NJ") == {}
    assert basis_distributions(state, "NJ") == 0.0
    assert basis_distributions(state, "PA") == 10_000


def test_commit_consumes_then_adds_basis():
    state = _state(basis={"PA": 25_000})
    commit_year(state, "PA", {"ira": 10_000}, {"ira": 7_500, "k401": 3_000})
    assert state.state_taxed_basis == {"ira": {"PA": 22_500}, "k401": {"PA": 3_000}}


def test_state_add_back_split_by_account_matches_the_total():
    state = SimState(year=2026, accounts={
        "ira": AccountInfo(balance=0, account_type="traditional_ira"),
        "k401": AccountInfo(balance=0, account_type="traditional_401k"),
        "b403": AccountInfo(balance=0, account_type="traditional_403b"),
    })
    state.waterfall_retirement_contributions_this_year = {"ira": 6_000}
    payroll = {"k401": 10_000, "b403": 5_000}
    employer_403b = {"b403": 2_000}
    # Pennsylvania adds back every plan; $1,500 of the IRA was not deducted federally.
    assert _state_taxed_contributions_by_account("PA", state, payroll, employer_403b, 1_500) == {
        "ira": pytest.approx(4_500), "k401": 10_000, "b403": 5_000}
    # New Jersey: IRAs plus 403(b) deferrals and W-2 employer 403(b) money; not 401(k).
    assert _state_taxed_contributions_by_account("NJ", state, payroll, employer_403b, 0) == {
        "ira": 6_000, "b403": 7_000}
    # Massachusetts: IRAs only.
    assert _state_taxed_contributions_by_account("MA", state, payroll, employer_403b, 0) == {"ira": 6_000}
    assert _state_taxed_contributions_by_account("CA", state, payroll, employer_403b, 0) == {}


def test_recovery_reduces_state_income():
    base = dict(gross_income=0, deductions=0, filing_status="single", state_code="PA", rmd_income=20_000)
    without = calculate(**base)
    recovered = calculate(**base, state_contribution_basis_recovery=8_000,
                          state_contribution_basis_distributions=20_000)
    assert recovered.state_contribution_basis_recovery == pytest.approx(8_000)
    assert without.state - recovered.state == pytest.approx(PA_RATE * 8_000)
    # Federal tax is unchanged: the basis is a state-only concept.
    assert recovered.federal == pytest.approx(without.federal)


def test_no_double_exclusion_with_the_pennsylvania_retirement_exclusion():
    # At 65 Pennsylvania exempts IRA distributions entirely, so nothing is left to recover.
    persons = [RetirementIncome(age=65, amounts={"ira": 20_000})]
    result = calculate(gross_income=0, deductions=0, filing_status="single", state_code="PA",
                       rmd_income=20_000, holder_age=65, retirement_income=persons,
                       state_contribution_basis_recovery=8_000, state_contribution_basis_distributions=20_000)
    assert result.state_retirement_exclusion == pytest.approx(20_000)
    assert result.state_contribution_basis_recovery == 0.0
    assert result.state == 0.0


def test_new_jersey_recovers_only_what_the_pension_exclusion_leaves_taxable():
    # NJ 62+: $90,000 of IRA income, exclusion capped at $75,000 single for income
    # at or below $100,000. Of the $15,000 left taxable, $10,000 is recovered basis.
    persons = [RetirementIncome(age=66, amounts={"ira": 90_000})]
    base = dict(gross_income=0, deductions=0, filing_status="single", state_code="NJ",
                rmd_income=90_000, holder_age=66, retirement_income=persons)
    without = calculate(**base)
    result = calculate(**base, state_contribution_basis_recovery=10_000,
                       state_contribution_basis_distributions=90_000)
    assert result.state_retirement_exclusion == pytest.approx(75_000)
    assert result.state_contribution_basis_recovery == pytest.approx(10_000)
    assert result.state < without.state
    capped = calculate(**base, state_contribution_basis_recovery=40_000,
                       state_contribution_basis_distributions=90_000)
    assert capped.state_contribution_basis_recovery == pytest.approx(15_000)
    assert capped.state == 0.0


def _pa_plan(basis, age_birth_year=1976, state_code="PA"):
    return PlanData(
        plan_id="00000000-0000-0000-0000-0000000000b2", birth_year=age_birth_year, birth_month=1,
        filing_status="single", life_expectancy=55, start_year=2026, state_code=state_code,
        assumptions=AssumptionData(inflation_rate=0.0, stock_growth_rate=0.0, bond_return_rate=0.0),
        accounts={"ira": AccountInfo(balance=200_000, account_type="traditional_ira", name="IRA",
                                     state_taxed_basis=basis)},
        expenses=[ExpenseData(id="e", name="Living", annual_amount=20_000, inflation_linked=False)],
        drawdown_order=[DrawdownEntryData(1, "ira")],
    )


def test_simulated_early_withdrawal_recovers_opening_basis_in_pennsylvania():
    # Age 50: Pennsylvania taxes the early IRA distribution except the basis.
    years = run_simulation(_pa_plan(None)).yearly_snapshots
    distributed = years[0].gross_income
    assert years[0].state_tax == pytest.approx(PA_RATE * distributed, abs=0.01)
    recovered = run_simulation(_pa_plan(15_000)).yearly_snapshots
    # Cost recovery: the first $15,000 of distributions is basis.
    assert recovered[0].state_tax == pytest.approx(PA_RATE * (recovered[0].gross_income - 15_000), abs=0.01)
    # The basis is used up, so later distributions are fully taxed again.
    assert recovered[1].state_tax == pytest.approx(PA_RATE * recovered[1].gross_income, abs=0.01)


def test_basis_from_another_state_is_not_recovered():
    taxed = run_simulation(_pa_plan(None, state_code="NY")).yearly_snapshots[0].state_tax
    assert run_simulation(_pa_plan(15_000, state_code="NY")).yearly_snapshots[0].state_tax == pytest.approx(taxed)
