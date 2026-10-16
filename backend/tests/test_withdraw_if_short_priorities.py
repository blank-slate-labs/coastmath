"""Withdraw-if-short cash-flow priorities and the reduce-employer-contribution option."""

from __future__ import annotations

import pytest

from coastmath.engine.monte_carlo import run_monte_carlo
from coastmath.engine.simulator import run_simulation
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EmployerMatchData,
    ExpenseData,
    IncomeData,
    LiabilityData,
    PlanData,
    PriorityData,
    SimState,
)
from coastmath.engine.waterfall import allocate_payroll_contributions


def build(accounts, priorities, *, order=(), wages=0.0, expenses=0.0, birth_year=1980, **kw) -> PlanData:
    return PlanData(
        plan_id="00000000-0000-4000-8000-0000000000af", birth_year=birth_year, birth_month=1,
        filing_status="single", life_expectancy=2026 - birth_year + 5, start_year=2026,
        state_code="FL",
        assumptions=AssumptionData(inflation_rate=0, stock_growth_rate=0, bond_return_rate=0, stock_dividend_yield=0),
        accounts=accounts,
        income_streams=[IncomeData(id="job", name="Job", annual_amount=wages)] if wages else [],
        expenses=[ExpenseData(id="living", name="Living", annual_amount=expenses)] if expenses else [],
        priorities=priorities,
        drawdown_order=[DrawdownEntryData(i + 1, aid) for i, aid in enumerate(order)],
        tax_settings={"cash_flow_frequency": "annual"},
        **kw,
    )


def first(plan):
    return run_simulation(plan).yearly_snapshots[0]


def flow(snapshot, rank):
    return next(f for f in snapshot.cash_flow.contributions if f.source == "priority" and f.priority_rank == rank)


def withdrawn(snapshot, account_id):
    return sum(f.amount for f in snapshot.cash_flow.drawdowns if f.account_id == account_id)


def contribution(target, rank=1, amount=3000.0, **kw):
    return PriorityData(rank, target_account_id=target, priority_type="contribution",
                        allocation_mode="amount", allocation_value=amount, **kw)


def test_regression_zero_surplus_401k_goal_is_funded_by_drawdown():
    """Spending uses all pay; the goal is drawn from savings, after spending."""
    accounts = {"sav": AccountInfo(20000, "savings"), "k401": AccountInfo(0, "traditional_401k")}
    base = first(build(accounts, [contribution("k401")], order=["sav"], wages=40000, expenses=45000))
    plan = build({k: AccountInfo(v.balance, v.account_type) for k, v in accounts.items()},
                 [contribution("k401", withdraw_if_short=True)], order=["sav"], wages=40000, expenses=45000)
    snap = first(plan)
    assert base.accounts["k401"] == 0 and flow(base, 1).amount == 0
    assert snap.accounts["k401"] == pytest.approx(3000)
    assert flow(snap, 1).amount == pytest.approx(3000)
    # The extra draw is the deposit, less the tax the pre-tax deferral saves,
    # settled in the same year.
    tax_saved = base.taxes - snap.taxes
    assert tax_saved > 0
    assert base.accounts["sav"] - snap.accounts["sav"] == pytest.approx(3000 - tax_saved, abs=0.01)
    assert snap.rule_funding_shortfall == 0 and snap.unfunded_expenses == 0


def test_spending_deficit_is_funded_before_the_goal():
    accounts = {"sav": AccountInfo(5000, "savings"), "brok": AccountInfo(0, "taxable_brokerage", cost_basis=0)}
    snap = first(build(accounts, [contribution("brok", withdraw_if_short=True)], order=["sav"], expenses=4000))
    assert snap.unfunded_expenses == 0
    assert snap.accounts["brok"] == pytest.approx(1000)
    assert snap.rule_funding_shortfall == pytest.approx(2000)


def test_ira_goal_without_compensation_contributes_nothing():
    accounts = {"sav": AccountInfo(20000, "savings"), "ira": AccountInfo(0, "roth_ira")}
    snap = first(build(accounts, [contribution("ira", amount=7000, withdraw_if_short=True)], order=["sav"]))
    assert snap.accounts["ira"] == 0
    assert snap.accounts["sav"] == pytest.approx(20000)
    assert snap.rule_funding_shortfall == 0
    assert "compensation" in flow(snap, 1).funding_reasons


def test_partial_funding_records_shortfall_without_failing_the_plan():
    accounts = {"sav": AccountInfo(2000, "savings"), "brok": AccountInfo(0, "taxable_brokerage", cost_basis=0)}
    result = run_simulation(build(accounts, [contribution("brok", withdraw_if_short=True)], order=["sav"]))
    snap = result.yearly_snapshots[0]
    assert snap.accounts["brok"] == pytest.approx(2000)
    assert snap.rule_funding_shortfall == pytest.approx(1000)
    assert "withdrawal_shortfall" in flow(snap, 1).funding_reasons
    assert snap.unfunded_expenses == 0
    assert result.metadata.failure_year is None and result.metadata.success
    # Every later year has nothing left to draw.
    assert result.yearly_snapshots[1].rule_funding_shortfall == pytest.approx(3000)


def test_withdrawal_locks_are_respected():
    accounts = {
        "locked": AccountInfo(50000, "savings", withdrawal_lock={"unlock": "year", "year": 2030}),
        "brok": AccountInfo(0, "taxable_brokerage", cost_basis=0),
    }
    snap = first(build(accounts, [contribution("brok", withdraw_if_short=True)], order=["locked"]))
    assert snap.accounts["locked"] == pytest.approx(50000)
    assert snap.accounts["brok"] == 0
    assert snap.rule_funding_shortfall == pytest.approx(3000)


def test_drawdown_tax_is_settled_in_the_same_year():
    accounts = {"ira": AccountInfo(100000, "traditional_ira"),
                "chk": AccountInfo(0, "checking"),
                "brok": AccountInfo(0, "taxable_brokerage", cost_basis=0)}
    plan = build(accounts, [contribution("brok", amount=40000, withdraw_if_short=True)],
                 order=["chk", "ira"], birth_year=1960)
    snap = first(plan)
    assert snap.accounts["brok"] == pytest.approx(40000)
    assert snap.taxes > 0
    # The IRA pays the goal and the tax its own withdrawal causes.
    assert withdrawn(snap, "ira") == pytest.approx(40000 + snap.taxes, abs=0.05)
    assert snap.rule_funding_shortfall == 0 and snap.unfunded_expenses == 0


def test_never_draws_from_the_target_or_its_limit_siblings():
    accounts = {"trad": AccountInfo(50000, "traditional_ira"), "roth": AccountInfo(0, "roth_ira"),
                "sav": AccountInfo(1000, "savings")}
    plan = build(accounts, [contribution("roth", amount=5000, withdraw_if_short=True)],
                 order=["trad", "roth", "sav"], wages=10000, expenses=10000 * 0.9235, birth_year=1960)
    snap = first(plan)
    assert withdrawn(snap, "trad") == 0 and withdrawn(snap, "roth") == 0
    assert snap.rule_funding_shortfall > 0


def test_withdraw_if_short_runs_ahead_of_optional_rules():
    accounts = {"chk": AccountInfo(0, "checking"), "sav": AccountInfo(0, "savings"),
                "brok": AccountInfo(0, "taxable_brokerage", cost_basis=0)}
    optional = PriorityData(1, target_account_id="sav", priority_type="contribution")
    goal = contribution("brok", rank=2, amount=5000, withdraw_if_short=True)
    snap = first(build(accounts, [optional, goal], order=["chk"], wages=20000))
    assert flow(snap, 2).amount == pytest.approx(5000)
    assert flow(snap, 1).amount == pytest.approx(snap.net_cash_flow - 5000, abs=0.01)
    # The rule keeps its own rank in the ledger.
    assert flow(snap, 2).priority_rank == 2
    # Without the option, rank 1 takes the whole surplus.
    plain = first(build({k: AccountInfo(v.balance, v.account_type, cost_basis=v.cost_basis) for k, v in accounts.items()},
                        [optional, contribution("brok", rank=2, amount=5000)], order=["chk"], wages=20000))
    assert flow(plain, 2).amount == 0


def test_contribution_limits_still_bind():
    accounts = {"sav": AccountInfo(50000, "savings"), "ira": AccountInfo(0, "traditional_ira")}
    snap = first(build(accounts, [contribution("ira", amount=20000, withdraw_if_short=True)],
                       order=["sav"], wages=30000, expenses=40000))
    assert snap.accounts["ira"] == pytest.approx(7500)
    assert snap.rule_funding_shortfall == 0


def test_debt_payment_goal_draws_from_savings():
    accounts = {"sav": AccountInfo(10000, "savings")}
    loan = LiabilityData(id="loan", name="Car", principal_balance=20000, interest_rate=0.0,
                         term_months=60, monthly_payment=0.0)
    rule = PriorityData(1, priority_type="debt_payment", target_liability_id="loan",
                        allocation_mode="amount", allocation_value=4000, withdraw_if_short=True)
    snap = first(build(accounts, [rule], order=["sav"], liabilities=[loan]))
    assert snap.liabilities_balance == pytest.approx(16000)
    assert snap.accounts["sav"] == pytest.approx(6000)


def test_monte_carlo_trial_with_withdraw_if_short_rule_does_not_fail_on_shortfall():
    accounts = {"sav": AccountInfo(2000, "savings"), "brok": AccountInfo(10000, "taxable_brokerage", cost_basis=10000)}
    plan = build(accounts, [contribution("sav", amount=3000, withdraw_if_short=True)], order=["brok"])
    det = run_simulation(plan)
    assert det.metadata.success
    mc = run_monte_carlo(plan, n_trials=3, seed=11, max_workers=1)
    assert mc.success_rate == 1.0


def _payroll_state(accounts):
    state = SimState(accounts=accounts, year=2026)
    state.compensation_by_owner = {"self": 30000}
    state.owner_ages = {"self": 46}
    return state


def test_reduce_employer_contribution_scales_a_flat_rate():
    def run(reduce):
        accounts = {"k401": AccountInfo(0, "traditional_401k"), "k457": AccountInfo(0, "traditional_457b")}
        state = _payroll_state(accounts)
        rules = [
            PriorityData(1, target_account_id="k401", priority_type="income_percent",
                         source_income_id="job", employee_rate=0.8),
            PriorityData(2, target_account_id="k457", priority_type="income_percent",
                         source_income_id="job", employee_rate=0.5, employer_match_rate=0.1,
                         reduce_employer_contribution=reduce),
        ]
        results = allocate_payroll_contributions(rules, {"job": 30000}, state, 46)
        return next(r for r in results if r.target_account_id == "k457")
    full, reduced = run(False), run(True)
    # Pay left after the first rule funds 6,000 of the 15,000 elected.
    assert full.employee_amount == reduced.employee_amount == pytest.approx(6000)
    assert full.employer_amount == pytest.approx(3000)
    assert reduced.employer_amount == pytest.approx(3000 * 6000 / 15000)


def test_reduce_employer_contribution_is_a_no_op_for_a_tiered_match_and_limits():
    def run(reduce, match=None, rate=0.0):
        state = _payroll_state({"k401": AccountInfo(0, "traditional_401k")})
        rule = PriorityData(1, target_account_id="k401", priority_type="income_percent",
                            source_income_id="job", employee_rate=0.9, employer_match_rate=rate,
                            employer_match=match, reduce_employer_contribution=reduce)
        return allocate_payroll_contributions([rule], {"job": 30000}, state, 46)[0]
    # A limit cut (402(g) and compensation) is not a pay shortfall.
    assert run(True, rate=0.05).employer_amount == pytest.approx(run(False, rate=0.05).employer_amount)
    match = EmployerMatchData(tiers=[])
    match.nonelective_percent = 0.03
    assert run(True, match=match).employer_amount == pytest.approx(run(False, match=match).employer_amount)


def _roth_goal_plan(expenses):
    accounts = {"chk": AccountInfo(0, "checking"),
                "brok": AccountInfo(200_000, "taxable_brokerage", cost_basis=0),
                "roth": AccountInfo(0, "roth_ira")}
    return build(accounts, [contribution("roth", amount=7500, withdraw_if_short=True)],
                 order=["brok"], wages=150_000, expenses=expenses)


def test_roth_ira_income_test_is_rechecked_after_the_goal_withdrawal():
    # Wages of 150,000 leave the single filer below the 2026 Roth IRA
    # phase-out, so the goal is queued at the full 7,500. Drawing the unmet
    # part from a zero-basis brokerage adds capital gains to modified AGI,
    # which lowers the limit: only the eligible part is deposited and the
    # rest of the cash raised stays in checking.
    snap = first(_roth_goal_plan(110_000))
    assert 0 < snap.accounts["roth"] < 7500
    assert snap.accounts["roth"] + snap.accounts["chk"] == pytest.approx(7500, abs=0.01)
    assert flow(snap, 1).amount == pytest.approx(snap.accounts["roth"])
    assert "contribution eligibility / annual limit" in flow(snap, 1).limited_by
    assert snap.rule_funding_shortfall == 0
    kept = [f for f in snap.cash_flow.contributions if f.source == "default_sink" and f.account_id == "chk"]
    assert sum(f.amount for f in kept) == pytest.approx(snap.accounts["chk"])


def test_roth_ira_income_test_counts_the_spending_deficit_withdrawals():
    # The spending deficit is drawn first and its gains push modified AGI
    # above the phase-out, so nothing is withdrawn for the goal.
    snap = first(_roth_goal_plan(140_000))
    assert snap.accounts["roth"] == 0
    assert snap.rule_funding_shortfall == 0
    assert snap.accounts["chk"] == 0
