"""Tax suggestions: candidate applicability and the improvement filter."""

import copy

import pytest

from coastmath.engine import tax_suggestions as ts
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_strategy import pre_tax_discount_rate
from coastmath.engine.tax_suggestions import (
    build_suggestion_candidates,
    suggest_tax_strategies,
)
from coastmath.engine.types import (
    AccountInfo,
    AssumptionData,
    DrawdownEntryData,
    EstateSettingsData,
    ExpenseData,
    IncomeData,
    MilestoneData,
    PlanData,
    PriorityData,
)

PLAN_ID = "00000000-0000-0000-0000-0000000000a1"


def plan(salary=250_000, accounts=None, priorities=None, **kwargs) -> PlanData:
    data = dict(
        plan_id=PLAN_ID, birth_year=1980, filing_status="single", life_expectancy=90, start_year=2026,
        accounts=accounts if accounts is not None else {
            "cash": AccountInfo(20_000, "checking"),
            "brok": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000),
        },
        income_streams=[IncomeData("wage", "Salary", salary, end_milestone_id="ret")] if salary else [],
        milestones=[MilestoneData(id="ret", name="Retire", trigger_type="age", trigger_value=55)],
        expenses=[ExpenseData("living", "Living", 60_000)],
        priorities=priorities if priorities is not None else [PriorityData(1, "brok", priority_type="contribution")],
        drawdown_order=[DrawdownEntryData(1, "cash"), DrawdownEntryData(2, "brok")],
    )
    data.update(kwargs)
    return PlanData(**data)


def with_accounts(**extra) -> dict:
    return {"cash": AccountInfo(20_000, "checking"),
            "brok": AccountInfo(100_000, "taxable_brokerage", cost_basis=100_000), **extra}


def candidate_keys(p: PlanData) -> list[str]:
    return [c.key for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p)))]


# --- Max 401(k) ------------------------------------------------------------

def test_max_401k_applies_with_wages_and_room():
    p = plan(accounts=with_accounts(k=AccountInfo(50_000, "traditional_401k")))
    candidates = build_suggestion_candidates(p, run_simulation(copy.deepcopy(p)))
    max_401k = next(c for c in candidates if c.key == "max_401k")
    [rule] = max_401k.rules
    assert (rule.change, rule.priority_type, rule.target_account_id, rule.source_income_id) == (
        "add", "pre_tax_contribution", "k", "wage")
    assert rule.priority_rank == 2


def test_max_401k_goes_ahead_of_an_after_tax_rule():
    # An uncapped after-tax rule ranked first would take the 415(c) room before the deferral.
    accounts = with_accounts(rk=AccountInfo(0, "roth_401k"))
    rules = [PriorityData(1, "rk", priority_type="after_tax_401k", source_income_id="wage"),
             PriorityData(2, "brok", priority_type="contribution")]
    p = plan(accounts=accounts, priorities=rules)
    max_401k = next(c for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p))) if c.key == "max_401k")
    [rule] = max_401k.rules
    assert rule.priority_rank == 1
    ranks = {q.priority_type: q.priority_rank for q in max_401k.priorities}
    assert ranks == {"pre_tax_contribution": 1, "after_tax_401k": 2, "contribution": 3}


def test_max_401k_into_a_roth_401k_only_gains_the_tax_the_brokerage_would_pay():
    # Regression: a $0 gain from Max 401(k) into a Roth 401(k) here is correct, not a bug.
    p = plan(accounts=with_accounts(rk=AccountInfo(0, "roth_401k")))
    base = run_simulation(copy.deepcopy(p))
    candidate = next(c for c in build_suggestion_candidates(p, base) if c.key == "max_401k")
    scenario = copy.deepcopy(p)
    scenario.priorities = copy.deepcopy(candidate.priorities)
    moved = run_simulation(scenario)
    # The deferral moves money from the brokerage into the Roth 401(k)...
    assert moved.yearly_snapshots[0].accounts["rk"] > 24_000
    assert moved.yearly_snapshots[-1].accounts["brok"] < base.yearly_snapshots[-1].accounts["brok"]
    # ...but Roth deferrals are taxed like wages, and at a 0% dividend yield the
    # brokerage's only tax is on sales, whose gains here stay in the 0% bracket.
    assert sum(s.capital_gains_tax for s in base.yearly_snapshots) == 0
    assert sum(s.taxes for s in moved.yearly_snapshots) == pytest.approx(sum(s.taxes for s in base.yearly_snapshots), abs=0.01)
    assert moved.yearly_snapshots[-1].net_worth == pytest.approx(base.yearly_snapshots[-1].net_worth, abs=0.01)
    assert "max_401k" not in [s.key for s in suggest_tax_strategies(p)]

    # Taxed dividends give the brokerage a drag the Roth avoids.
    p.assumptions = AssumptionData(stock_dividend_yield=0.015)
    [max_401k] = [s for s in suggest_tax_strategies(p) if s.key == "max_401k"]
    assert max_401k.lifetime_tax_change < 0 and max_401k.end_net_worth_change > 0
    assert max_401k.rules[0].target_account_id == "rk"


def test_max_401k_does_not_apply_without_wages():
    assert "max_401k" not in candidate_keys(plan(salary=0, accounts=with_accounts(k=AccountInfo(50_000, "traditional_401k"))))


def test_max_401k_does_not_apply_when_rules_reach_the_limit():
    accounts = with_accounts(k=AccountInfo(50_000, "traditional_401k"))
    uncapped = [PriorityData(1, "k", priority_type="pre_tax_contribution"), PriorityData(2, "brok", priority_type="contribution")]
    assert "max_401k" not in candidate_keys(plan(accounts=accounts, priorities=uncapped))
    # 10% of $250,000 is above the $24,500 deferral limit at 46.
    percent = [PriorityData(1, "k", priority_type="income_percent", source_income_id="wage", employee_rate=0.10),
               PriorityData(2, "brok", priority_type="contribution")]
    assert "max_401k" not in candidate_keys(plan(accounts=accounts, priorities=percent))
    # 5% ($12,500) leaves room, so the suggestion fills the same account.
    percent[0].employee_rate = 0.05
    p = plan(accounts=accounts, priorities=percent)
    candidate = next(c for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p))) if c.key == "max_401k")
    assert candidate.rules[0].target_account_id == "k" and candidate.rules[0].priority_rank == 3


# --- Backdoor Roth -----------------------------------------------------------

def test_backdoor_roth_applies_above_the_phaseout_before_the_catch_all_rule():
    p = plan(accounts=with_accounts(r=AccountInfo(10_000, "roth_ira")))
    candidate = next(c for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p))) if c.key == "backdoor_roth")
    [rule] = candidate.rules
    assert (rule.change, rule.priority_type, rule.target_account_id, rule.backdoor_roth, rule.priority_rank) == (
        "add", "contribution", "r", True, 1)
    # The brokerage catch-all moves down one.
    assert sorted((q.priority_rank, q.target_account_id) for q in candidate.priorities) == [(1, "r"), (2, "brok")]


def test_backdoor_roth_updates_an_existing_roth_ira_rule():
    rules = [PriorityData(1, "r", priority_type="contribution"), PriorityData(2, "brok", priority_type="contribution")]
    p = plan(accounts=with_accounts(r=AccountInfo(10_000, "roth_ira")), priorities=rules)
    candidate = next(c for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p))) if c.key == "backdoor_roth")
    assert [(r.change, r.priority_rank, r.backdoor_roth) for r in candidate.rules] == [("update", 1, True)]
    assert len(candidate.priorities) == 2 and not p.priorities[0].backdoor_roth  # the plan itself is untouched


def test_backdoor_roth_does_not_apply_below_the_phaseout_or_when_one_exists():
    accounts = with_accounts(r=AccountInfo(10_000, "roth_ira"))
    assert "backdoor_roth" not in candidate_keys(plan(salary=90_000, accounts=accounts))
    existing = [PriorityData(1, "r", priority_type="contribution", backdoor_roth=True),
                PriorityData(2, "brok", priority_type="contribution")]
    assert "backdoor_roth" not in candidate_keys(plan(accounts=accounts, priorities=existing))
    assert "backdoor_roth" not in candidate_keys(plan())  # no Roth IRA


# --- Max HSA ----------------------------------------------------------------

def test_max_hsa_applies_with_an_hsa_and_earned_income():
    p = plan(accounts=with_accounts(h=AccountInfo(2_000, "hsa")))
    candidate = next(c for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p))) if c.key == "max_hsa")
    assert [(r.priority_type, r.target_account_id) for r in candidate.rules] == [("pre_tax_contribution", "h")]


def test_max_hsa_does_not_apply_when_coverage_is_ineligible_or_already_maxed():
    accounts = with_accounts(h=AccountInfo(2_000, "hsa"))
    ineligible = {"hsa_coverage": [{"owner": "self", "start_year": 2026, "coverage": "ineligible"}]}
    assert "max_hsa" not in candidate_keys(plan(accounts=accounts, tax_settings=ineligible))
    maxed = [PriorityData(1, "h", priority_type="pre_tax_contribution"), PriorityData(2, "brok", priority_type="contribution")]
    assert "max_hsa" not in candidate_keys(plan(accounts=accounts, priorities=maxed))
    assert "max_hsa" not in candidate_keys(plan(salary=0, accounts=accounts))


# --- Mega backdoor Roth -------------------------------------------------------

def test_mega_backdoor_applies_after_the_payroll_rules_from_the_largest_w2_wages():
    rules = [PriorityData(1, "k", priority_type="income_percent", source_income_id="wage", employee_rate=0.05),
             PriorityData(2, "brok", priority_type="contribution")]
    p = plan(accounts=with_accounts(k=AccountInfo(0, "traditional_401k"), rk=AccountInfo(0, "roth_401k")),
             priorities=rules)
    p.income_streams.append(IncomeData("side", "Side job", 20_000, end_milestone_id="ret"))
    candidate = next(c for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p))) if c.key == "mega_backdoor")
    [rule] = candidate.rules
    assert (rule.change, rule.priority_type, rule.target_account_id, rule.source_income_id, rule.priority_rank) == (
        "add", "after_tax_401k", "rk", "wage", 2)
    # Uncapped, and the surplus rule moves down one.
    assert next(q for q in candidate.priorities if q.priority_type == "after_tax_401k").max_annual_amount is None
    assert sorted((q.priority_rank, q.target_account_id) for q in candidate.priorities) == [(1, "k"), (2, "rk"), (3, "brok")]


def test_mega_backdoor_does_not_apply_without_a_roth_401k_w2_wages_or_when_a_rule_exists():
    roth_401k = with_accounts(rk=AccountInfo(0, "roth_401k"))
    assert "mega_backdoor" in candidate_keys(plan(accounts=roth_401k))
    assert "mega_backdoor" not in candidate_keys(plan(accounts=with_accounts(k=AccountInfo(0, "traditional_401k"))))
    self_employed = plan(accounts=roth_401k)
    self_employed.income_streams[0].is_self_employed = True
    assert "mega_backdoor" not in candidate_keys(self_employed)
    existing = [PriorityData(1, "rk", priority_type="after_tax_401k", source_income_id="wage", max_annual_amount=5_000),
                PriorityData(2, "brok", priority_type="contribution")]
    assert "mega_backdoor" not in candidate_keys(plan(accounts=roth_401k, priorities=existing))


# --- Roth conversions ---------------------------------------------------------

def test_roth_conversions_apply_with_a_funded_pre_tax_account_and_a_roth_for_the_same_owner():
    p = plan(accounts=with_accounts(ira=AccountInfo(400_000, "traditional_ira"), r=AccountInfo(0, "roth_ira")))
    conversions = [c for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p))) if c.key == "roth_conversion"]
    assert [c.rules[0].bracket_ceiling_rate for c in conversions] == ts.ROTH_CONVERSION_CEILINGS
    assert {(c.rules[0].source_account_id, c.rules[0].target_account_id, c.rules[0].conversion_mode) for c in conversions} == {
        ("ira", "r", "fill_bracket")}


def test_roth_conversions_do_not_apply_without_a_matching_roth_flat_tax_or_an_existing_rule():
    assert "roth_conversion" not in candidate_keys(plan(accounts=with_accounts(
        ira=AccountInfo(400_000, "traditional_ira"), r=AccountInfo(0, "roth_ira", owner="spouse"))))
    accounts = with_accounts(ira=AccountInfo(400_000, "traditional_ira"), r=AccountInfo(0, "roth_ira"))
    assert "roth_conversion" not in candidate_keys(plan(accounts=accounts, tax_settings={"mode": "flat", "ordinary_income_tax_rate": 0.2}))
    existing = [PriorityData(1, "r", priority_type="roth_conversion", source_account_id="ira", max_annual_amount=10_000),
                PriorityData(2, "brok", priority_type="contribution")]
    assert "roth_conversion" not in candidate_keys(plan(accounts=accounts, priorities=existing))


# --- 0% gain harvesting ---------------------------------------------------------

def test_gain_harvest_applies_to_taxable_gains_with_known_basis():
    p = plan(accounts={"cash": AccountInfo(20_000, "checking"),
                       "brok": AccountInfo(300_000, "taxable_brokerage", cost_basis=100_000)})
    candidate = next(c for c in build_suggestion_candidates(p, run_simulation(copy.deepcopy(p))) if c.key == "gain_harvest")
    [rule] = candidate.rules
    assert (rule.priority_type, rule.source_account_id, rule.conversion_mode, rule.bracket_ceiling_rate) == (
        "gain_harvest", "brok", "fill_bracket", 0.0)


def test_gain_harvest_does_not_apply_without_gains_or_basis():
    assert "gain_harvest" not in candidate_keys(plan())  # basis equals balance
    assert "gain_harvest" not in candidate_keys(plan(accounts={
        "cash": AccountInfo(20_000, "checking"), "brok": AccountInfo(300_000, "taxable_brokerage")}))


# --- Filtering ------------------------------------------------------------------

def test_only_improving_candidates_are_returned(monkeypatch):
    p = plan(accounts=with_accounts(h=AccountInfo(2_000, "hsa")))
    real = build_suggestion_candidates

    def with_a_no_op(plan_data, baseline):
        found = real(plan_data, baseline)
        # A candidate that changes nothing has zero deltas and must be dropped.
        found.append(ts._Candidate("max_401k", "Max 401(k)", list(plan_data.priorities), []))
        return found

    monkeypatch.setattr(ts, "build_suggestion_candidates", with_a_no_op)
    suggestions = suggest_tax_strategies(p)
    assert [s.key for s in suggestions] == ["max_hsa"]
    [hsa] = suggestions
    assert hsa.end_net_worth_change > 0 and hsa.lifetime_tax_change < 0
    assert hsa.rules[0].target_account_id == "h"


@pytest.mark.parametrize("tax,net_worth,success,expected", [
    (-100, 0, True, True),      # same net worth, less tax
    (100, 500, True, True),     # more tax, more net worth
    (-100, -500, True, False),  # less tax, less net worth
    (0, 0, True, False),        # no change
    (-100, 500, False, False),  # the plan would now fail
])
def test_improvement_rule(tax, net_worth, success, expected):
    base = ts._Outcome(lifetime_taxes=1_000, end_net_worth=10_000, success=True)
    cand = ts._Outcome(lifetime_taxes=1_000 + tax, end_net_worth=10_000 + net_worth, success=success)
    assert ts._improves(base, cand) is expected


def test_roth_conversion_keeps_only_the_best_ceiling(monkeypatch):
    p = plan(accounts=with_accounts(ira=AccountInfo(400_000, "traditional_ira"), r=AccountInfo(0, "roth_ira")))
    outcomes = iter([ts._Outcome(1_000, 10_000, True), ts._Outcome(900, 10_100, True),
                     ts._Outcome(900, 10_300, True), ts._Outcome(900, 10_200, True)])
    monkeypatch.setattr(ts, "_outcome", lambda result, rate: next(outcomes))
    monkeypatch.setattr(ts, "build_suggestion_candidates",
                        lambda plan_data, baseline: [c for c in build_suggestion_candidates(plan_data, baseline)
                                                     if c.key == "roth_conversion"])
    [suggestion] = suggest_tax_strategies(p)
    assert suggestion.title == "Roth conversions to 22%"
    assert (suggestion.lifetime_tax_change, suggestion.end_net_worth_change) == (-100, 300)


# --- Pre-tax balances after income tax ---------------------------------------------

@pytest.mark.parametrize("estate,expected", [
    (None, 0.24), (EstateSettingsData(), 0.24), (EstateSettingsData(heir_income_tax_rate=0.37), 0.37),
])
def test_pre_tax_discount_rate_is_the_heir_rate_else_24_percent(estate, expected):
    assert pre_tax_discount_rate(plan(estate_settings=estate)) == expected


def test_suggestions_rank_with_pre_tax_balances_after_income_tax(monkeypatch):
    p = plan(accounts=with_accounts(k=AccountInfo(50_000, "traditional_401k"),
                                    ira=AccountInfo(600_000, "traditional_ira"), r=AccountInfo(0, "roth_ira")))
    base = run_simulation(copy.deepcopy(p))
    candidate = next(c for c in build_suggestion_candidates(p, base) if c.key == "max_401k")
    scenario = copy.deepcopy(p)
    scenario.priorities = copy.deepcopy(candidate.priorities)
    moved = run_simulation(scenario)
    raw_change = moved.yearly_snapshots[-1].net_worth - base.yearly_snapshots[-1].net_worth
    pre_tax_change = moved.metadata.net_legacy.pretax_balance - base.metadata.net_legacy.pretax_balance
    assert pre_tax_change > 0

    suggestions = {s.key: s for s in suggest_tax_strategies(p)}
    assert suggestions["max_401k"].end_net_worth_change == pytest.approx(raw_change - 0.24 * pre_tax_change)
    # Recompute each conversion candidate's after-heir-tax improvement rather
    # than assuming a particular conversion schedule remains beneficial. The
    # final-income target reserves tax-funded sales and the unused deduction.
    conversion_changes = []
    for conversion in build_suggestion_candidates(p, base):
        if conversion.key != "roth_conversion":
            continue
        scenario = copy.deepcopy(p)
        scenario.priorities = copy.deepcopy(conversion.priorities)
        result = run_simulation(scenario)
        raw = result.yearly_snapshots[-1].net_worth - base.yearly_snapshots[-1].net_worth
        pretax = result.metadata.net_legacy.pretax_balance - base.metadata.net_legacy.pretax_balance
        conversion_changes.append(raw - .24 * pretax)
    assert len(conversion_changes) == 3
    assert max(conversion_changes) == pytest.approx(-41_346.708238, abs=.02)
    assert "roth_conversion" not in suggestions
    monkeypatch.setattr(ts, "pre_tax_discount_rate", lambda plan_data: 0.0)
    assert [s.key for s in suggest_tax_strategies(p)] == ["max_401k"]
