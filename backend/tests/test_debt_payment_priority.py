"""Ranked debt-payment priority and one-time debt forgiveness."""

from __future__ import annotations

import pytest

from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DebtForgivenessData,
    IncomeData,
    LiabilityData,
    MilestoneData,
    PlanData,
    PriorityData,
)

SAVINGS = PriorityData(2, target_account_id="sav", priority_type="savings")


def debt_priority(rank=1, **kw) -> PriorityData:
    return PriorityData(rank, priority_type="debt_payment", target_liability_id="loan", **kw)


def build(priorities, *, balance=20000.0, forgiveness=None, income=60000.0, **kw) -> PlanData:
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000075", birth_year=1990, birth_month=1,
        filing_status="single", life_expectancy=40, start_year=2026, state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0),
        accounts={"chk": AccountInfo(10000, "checking"), "sav": AccountInfo(0, "savings")},
        income_streams=[IncomeData(id="job", name="Job", annual_amount=income, withholding_percent=0.0)],
        liabilities=[LiabilityData(
            id="loan", name="Car", principal_balance=balance, interest_rate=0.06, term_months=60,
            monthly_payment=386.66, forgiveness=forgiveness)],
        priorities=priorities, tax_settings={"cash_flow_frequency": "annual"}, **kw)


def years(plan, count=4):
    return run_simulation(plan).yearly_snapshots[:count]


def debt_flow(snapshot):
    return [f for f in snapshot.cash_flow.contributions if f.name.startswith("Pay down")]


def test_baseline_without_debt_priority_is_unchanged():
    base = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")]))
    assert [round(s.liabilities_balance, 2) for s in base][:2] == [16463.89, 12709.68]


def test_partial_payoff_reduces_cash_and_principal_exactly_once():
    base = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")]))
    paid = years(build([debt_priority(max_annual_amount=5000), SAVINGS]))
    assert base[0].liabilities_balance - paid[0].liabilities_balance == pytest.approx(5000, abs=0.01)
    assert base[0].accounts["sav"] - paid[0].accounts["sav"] == pytest.approx(5000, abs=0.01)
    flow = debt_flow(paid[0])[0]
    assert flow.amount == pytest.approx(5000)
    assert flow.source == "priority" and flow.priority_rank == 1
    assert flow.account_id is None


def test_next_year_interest_falls_with_the_lower_balance():
    paid = years(build([debt_priority(max_annual_amount=5000), SAVINGS]))
    base = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")]))
    # The payment follows the year's scheduled payment, so year one is unchanged ...
    assert paid[0].liabilities_balance == pytest.approx(base[0].liabilities_balance - 5000, abs=0.01)
    # ... and the next year's scheduled payment retires more principal because
    # less interest accrues on the lower balance.
    base_drop = base[0].liabilities_balance - base[1].liabilities_balance
    paid_drop = paid[0].liabilities_balance - paid[1].liabilities_balance
    assert paid_drop > base_drop


def test_overpayment_is_capped_by_remaining_principal_and_later_years_see_payoff():
    paid = years(build([debt_priority(), SAVINGS], balance=3000.0))
    assert paid[0].liabilities_balance == pytest.approx(0.0, abs=0.01)
    flow = debt_flow(paid[0])[0]
    assert flow.amount < 3000.0 + 0.01
    assert paid[1].liabilities_balance == 0.0
    assert not debt_flow(paid[1]) or debt_flow(paid[1])[0].amount == 0
    if debt_flow(paid[1]):
        assert "loan_paid_off" in debt_flow(paid[1])[0].funding_reasons


def test_competing_priority_receives_only_what_the_debt_rule_leaves():
    base = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")]))
    paid = years(build([debt_priority(max_annual_amount=5000), SAVINGS]))
    assert paid[0].accounts["sav"] == pytest.approx(base[0].accounts["sav"] - 5000, abs=0.01)
    # Cash that did not go to the loan is never invented.
    assert paid[0].accounts["chk"] == base[0].accounts["chk"]


def test_debt_rule_ranked_after_savings_gets_nothing_when_savings_takes_all():
    plan = build([PriorityData(1, target_account_id="sav", priority_type="savings"),
                  PriorityData(2, priority_type="debt_payment", target_liability_id="loan")])
    first = years(plan)[0]
    assert debt_flow(first)[0].amount == 0
    assert "earlier_rules" in debt_flow(first)[0].funding_reasons


def test_zero_surplus_pays_nothing_and_never_draws_cash():
    plan = build([debt_priority(), SAVINGS], income=0.0)
    first = years(plan)[0]
    flows = debt_flow(first)
    assert not flows or flows[0].amount == 0
    assert first.accounts["chk"] <= 10000
    assert first.liabilities_balance >= 0


def test_amount_mode_scales_with_a_partial_first_year():
    full = years(build([debt_priority(allocation_mode="amount", allocation_value=6000), SAVINGS]))
    part = years(build([debt_priority(allocation_mode="amount", allocation_value=6000), SAVINGS],
                       first_year_fraction=0.5))
    assert debt_flow(full[0])[0].requested_amount == pytest.approx(6000)
    assert debt_flow(part[0])[0].requested_amount == pytest.approx(3000)
    assert debt_flow(part[1])[0].requested_amount == pytest.approx(6000)


def test_percentage_mode_takes_a_share_of_surplus():
    paid = years(build([debt_priority(allocation_mode="percentage", allocation_value=10), SAVINGS]))
    flow = debt_flow(paid[0])[0]
    assert flow.amount > 0
    assert flow.requested_amount == pytest.approx(flow.amount)


def test_debt_balance_never_negative_across_horizon():
    snapshots = run_simulation(build([debt_priority(), SAVINGS], balance=5000.0)).yearly_snapshots
    assert all(s.liabilities_balance >= 0 for s in snapshots)


# --------------------------------------------------------------- forgiveness

def test_year_forgiveness_is_taxable_income_without_cash():
    base = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")]))
    forgiven = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                           forgiveness=DebtForgivenessData(year=2027)))
    assert forgiven[0].debt_forgiven == 0
    assert forgiven[1].debt_forgiven > 0
    assert forgiven[1].debt_forgiveness_taxable == pytest.approx(forgiven[1].debt_forgiven)
    assert forgiven[1].liabilities_balance < base[1].liabilities_balance
    assert forgiven[1].federal_tax > base[1].federal_tax
    # No cash arrives with the forgiveness: the cash held at the start of the
    # forgiveness year is unchanged by the event itself.
    assert forgiven[0].accounts == base[0].accounts
    assert forgiven[1].accounts["chk"] == base[1].accounts["chk"]


def test_forgiveness_runs_once():
    snaps = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                        forgiveness=DebtForgivenessData(year=2027, amount=2000.0)))
    assert [round(s.debt_forgiven, 2) for s in snaps] == [0.0, 2000.0, 0.0, 0.0]


def test_declared_exclusion_removes_taxable_amount_but_keeps_debt_reduction():
    kw = dict(year=2027, amount=2000.0)
    taxable = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                          forgiveness=DebtForgivenessData(**kw)))[1]
    excluded = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                           forgiveness=DebtForgivenessData(
                               **kw, tax_treatment="declared_exclusion", excluded_amount=2000.0,
                               exclusion_basis="insolvency")))[1]
    partial = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                          forgiveness=DebtForgivenessData(
                              **kw, tax_treatment="declared_exclusion", excluded_amount=500.0)))[1]
    assert taxable.debt_forgiveness_taxable == pytest.approx(2000.0)
    assert excluded.debt_forgiven == pytest.approx(2000.0)
    assert excluded.debt_forgiveness_taxable == 0.0
    assert partial.debt_forgiveness_taxable == pytest.approx(1500.0)
    assert excluded.federal_tax < taxable.federal_tax
    assert excluded.liabilities_balance == pytest.approx(taxable.liabilities_balance)


def test_forgiveness_is_capped_by_the_outstanding_balance():
    snap = years(build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                       forgiveness=DebtForgivenessData(year=2026, amount=1e9)))[0]
    assert snap.debt_forgiven <= 20000.0
    assert snap.liabilities_balance == pytest.approx(0.0, abs=0.01)


def test_milestone_forgiveness_fires_in_the_year_reached():
    plan = build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                 forgiveness=DebtForgivenessData(milestone_id="m"),
                 milestones=[MilestoneData("m", "Date", "date", trigger_date="2028-03-01")])
    snaps = years(plan)
    assert [s.debt_forgiven > 0 for s in snaps] == [False, False, True, False]


def test_milestone_reached_before_plan_start_is_not_applied_and_warns():
    plan = build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                 forgiveness=DebtForgivenessData(milestone_id="m"),
                 milestones=[MilestoneData("m", "Date", "date", trigger_date="2020-03-01")])
    result = run_simulation(plan)
    assert all(s.debt_forgiven == 0 for s in result.yearly_snapshots)
    assert any("forgiveness" in w for w in result.metadata.warnings)


def test_missing_milestone_never_fires():
    plan = build([PriorityData(1, target_account_id="sav", priority_type="savings")],
                 forgiveness=DebtForgivenessData(milestone_id="age_never"),
                 milestones=[MilestoneData("age_never", "Old", "age", trigger_value=200)])
    assert all(s.debt_forgiven == 0 for s in years(plan, 10))


def simple_interest_loan(forgiveness) -> PlanData:
    """$10,000 at 12% simple interest with no payments: $1,200 accrues a year."""
    return PlanData(
        plan_id="00000000-0000-4000-8000-000000000076", birth_year=1960, birth_month=1,
        filing_status="single", life_expectancy=69, start_year=2026, state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0),
        accounts={"chk": AccountInfo(100000, "checking")},
        liabilities=[LiabilityData(
            id="loan", name="Loan", principal_balance=10000.0, interest_rate=0.12,
            monthly_payment=0.0, interest_method="simple", forgiveness=forgiveness)],
        tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0, "capital_gains_tax_rate": 0})


def test_full_forgiveness_cancels_accrued_simple_interest():
    snaps = years(simple_interest_loan(DebtForgivenessData(year=2027)), 3)
    assert snaps[0].liabilities_balance == pytest.approx(11200.0, abs=0.01)
    assert snaps[1].debt_forgiven == pytest.approx(11200.0, abs=0.01)
    # Cancelled interest is part of the reportable cancelled debt.
    assert snaps[1].debt_forgiveness_taxable == pytest.approx(11200.0, abs=0.01)
    assert snaps[1].liabilities_balance == pytest.approx(0.0, abs=0.01)
    assert snaps[2].liabilities_balance == pytest.approx(0.0, abs=0.01)


def test_full_forgiveness_with_declared_exclusion_excludes_interest_too():
    snap = years(simple_interest_loan(DebtForgivenessData(
        year=2027, tax_treatment="declared_exclusion", exclusion_basis="other_declared")), 2)[1]
    assert snap.debt_forgiven == pytest.approx(11200.0, abs=0.01)
    assert snap.debt_forgiveness_taxable == 0.0
    assert snap.liabilities_balance == pytest.approx(0.0, abs=0.01)


def test_partial_forgiveness_cancels_accrued_interest_before_principal():
    snap = years(simple_interest_loan(DebtForgivenessData(year=2027, amount=500.0)), 2)[1]
    assert snap.debt_forgiven == pytest.approx(500.0)
    # $700 unpaid interest stays, principal stays $10,000 and accrues $1,200.
    assert snap.liabilities_balance == pytest.approx(11900.0, abs=0.01)


def test_forgiveness_cap_includes_accrued_simple_interest():
    snap = years(simple_interest_loan(DebtForgivenessData(year=2027, amount=1e9)), 2)[1]
    assert snap.debt_forgiven == pytest.approx(11200.0, abs=0.01)
    assert snap.liabilities_balance == pytest.approx(0.0, abs=0.01)


def test_full_forgiveness_of_monthly_interest_loan_cancels_the_balance():
    snaps = years(build([], forgiveness=DebtForgivenessData(year=2027)), 3)
    assert snaps[1].debt_forgiven == pytest.approx(snaps[0].liabilities_balance)
    assert snaps[1].liabilities_balance == 0.0
    assert snaps[2].liabilities_balance == 0.0
