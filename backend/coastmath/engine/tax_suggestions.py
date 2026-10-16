"""Tax suggestions: a small fixed set of rule changes tested against the plan.

Each candidate is a deep copy of the plan with one rule change (one rule per
eligible person or account), simulated in full and compared with the plan as
it is on lifetime taxes and end-of-plan net worth, with pre-tax balances
after income tax at ``pre_tax_discount_rate`` (as the strategy comparison
ranks them). Only applicable candidates
are simulated, and only those that improve the plan are returned: net worth no
lower, and either higher net worth or lower lifetime taxes, without making a
successful plan fail. A run is at most nine simulations.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace

from coastmath.engine.account_types import (
    ELECTIVE_DEFERRAL_402G_TYPES,
    EMPLOYER_PLAN_FAMILY,
    EMPLOYER_PLAN_TYPES,
    ROTH_EMPLOYER_PLAN_TYPES,
    TRADITIONAL_RETIREMENT_TYPES,
)
from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_strategy import (
    build_candidates,
    pre_tax_discount,
    pre_tax_discount_rate,
)
from coastmath.engine.types import PlanData, PriorityData
from coastmath.engine.waterfall import (
    _IRS_LIMITS,
    _ROTH_IRA_PHASEOUTS,
    _irs_contribution_room,
)
from coastmath.schemas.simulation import SimulationResult

ROTH_CONVERSION_CEILINGS = [0.12, 0.22, 0.24]
GAIN_HARVEST_CEILING = 0.0
# Deltas within a dollar are rounding, not an improvement.
_EPSILON = 1.0
# One 402(g) limit across 401(k)s and 403(b)s, pre-tax first. A 457(b) has its
# own limit and no suggestion yet.
_402G_TYPES = tuple(sorted(ELECTIVE_DEFERRAL_402G_TYPES, key=lambda t: (not t.startswith("traditional"), t)))
_CONVERSION_SOURCES = tuple(sorted(TRADITIONAL_RETIREMENT_TYPES))
# Preferred target first: the Roth IRA, then designated Roth plans.
_CONVERSION_TARGETS = ("roth_ira", *sorted(ROTH_EMPLOYER_PLAN_TYPES))
_SURPLUS_TYPES = (None, "contribution")
_PAYROLL_TYPES = ("income_percent", "pre_tax_contribution", "after_tax_401k")
_OWNERS = ("self", "spouse")


@dataclass
class SuggestedRule:
    """One allocation rule in the wire format of ``CashFlowPriorityCreate``.

    ``change`` is ``add`` (insert at ``priority_rank``; existing rules at or
    after it move down one) or ``update`` (set these fields on the existing
    rule whose current rank is ``priority_rank``).
    """
    change: str
    priority_rank: int
    priority_type: str
    target_account_id: str | None = None
    source_account_id: str | None = None
    source_income_id: str | None = None
    conversion_mode: str = "fixed"
    bracket_ceiling_rate: float | None = None
    backdoor_roth: bool = False


@dataclass
class Suggestion:
    key: str
    title: str
    lifetime_tax_change: float  # candidate minus plan; negative saves tax
    end_net_worth_change: float  # candidate minus plan, pre-tax balances after income tax
    rules: list[SuggestedRule] = field(default_factory=list)


@dataclass
class _Candidate:
    key: str
    title: str
    priorities: list[PriorityData]
    rules: list[SuggestedRule]


@dataclass
class _Outcome:
    lifetime_taxes: float
    end_net_worth: float
    success: bool


def _outcome(result: SimulationResult, rate: float) -> _Outcome:
    # Same lifetime-tax and end-net-worth measures as tax_strategy._evaluate.
    snaps = result.yearly_snapshots
    return _Outcome(
        lifetime_taxes=sum(s.taxes for s in snaps),
        end_net_worth=(snaps[-1].net_worth if snaps else 0.0) - pre_tax_discount(result, rate),
        success=result.metadata.success,
    )


def _improves(base: _Outcome, cand: _Outcome) -> bool:
    if base.success and not cand.success:
        return False
    net_worth = cand.end_net_worth - base.end_net_worth
    taxes = cand.lifetime_taxes - base.lifetime_taxes
    return net_worth >= -_EPSILON and (net_worth > _EPSILON or taxes < -_EPSILON)


def _rule(p: PriorityData, change: str = "add") -> SuggestedRule:
    return SuggestedRule(
        change=change, priority_rank=p.priority_rank, priority_type=p.priority_type or "contribution",
        target_account_id=p.target_account_id, source_account_id=p.source_account_id,
        source_income_id=p.source_income_id, conversion_mode=p.conversion_mode,
        bracket_ceiling_rate=p.bracket_ceiling_rate, backdoor_roth=p.backdoor_roth,
    )


def _next_rank(plan: PlanData) -> int:
    return max((p.priority_rank for p in plan.priorities), default=0) + 1


def _appended(plan: PlanData, key: str, title: str, new: list[PriorityData]) -> _Candidate:
    rank = _next_rank(plan)
    added = [replace(p, priority_rank=rank + i) for i, p in enumerate(new)]
    return _Candidate(key, title, [*plan.priorities, *added], [_rule(p) for p in added])


def _inserted(plan: PlanData, key: str, title: str, new: list[PriorityData], at: int) -> _Candidate:
    """Insert *new* at rank *at*, moving existing rules at or below it down."""
    priorities = [replace(p, priority_rank=p.priority_rank + len(new)) if p.priority_rank >= at else p
                  for p in plan.priorities]
    added = [replace(p, priority_rank=at + i) for i, p in enumerate(new)]
    return _Candidate(key, title, [*priorities, *added], [_rule(p) for p in added])


def _owner_age(plan: PlanData, owner: str) -> int:
    birth_year = plan.spouse_birth_year if owner == "spouse" else plan.birth_year
    return plan.start_year - (birth_year or plan.birth_year)


def _contributable(plan: PlanData, account_types: tuple[str, ...]) -> dict[str, list[str]]:
    """Owner -> own (not inherited, not joint) accounts of these types."""
    found: dict[str, list[str]] = {}
    for aid, account in plan.accounts.items():
        if account.account_type in account_types and account.owner in _OWNERS and account.inherited_year is None:
            found.setdefault(account.owner, []).append(aid)
    return found


def _wages_by_owner(plan: PlanData, w2_only: bool = False) -> dict[str, str]:
    """Owner -> id of their largest active earned-income stream (W-2 only if asked)."""
    best: dict[str, tuple[float, str]] = {}
    for inc in plan.income_streams:
        if w2_only and inc.is_self_employed:
            continue
        if inc.is_active and inc.is_earned_income and not inc.is_social_security and inc.annual_amount > 0:
            if inc.owner not in best or inc.annual_amount > best[inc.owner][0]:
                best[inc.owner] = (inc.annual_amount, inc.id)
    return {owner: income_id for owner, (_, income_id) in best.items()}


def _payroll_rules(plan: PlanData, account_ids: list[str]) -> list[PriorityData]:
    return [p for p in plan.priorities
            if p.priority_type in ("income_percent", "pre_tax_contribution") and p.target_account_id in account_ids]


def _requested_payroll(plan: PlanData, rules: list[PriorityData]) -> float:
    """First-year employee amount the existing payroll rules ask for."""
    income = {inc.id: inc.annual_amount for inc in plan.income_streams}
    total = 0.0
    for p in rules:
        if p.priority_type == "pre_tax_contribution":
            amount = float("inf") if p.max_annual_amount is None else p.max_annual_amount
        else:
            amount = income.get(p.source_income_id or "", 0.0) * p.employee_rate
            if p.max_annual_amount is not None:
                amount = min(amount, p.max_annual_amount)
        total += amount
    return total


def _max_401k(plan: PlanData) -> _Candidate | None:
    """A deferral rule filling each earner's 401(k)/403(b) limit.

    Into a Roth 401(k) the deferral is taxed like wages, so its only gain over
    the money's surplus destination is the tax it avoids there. A brokerage at
    the default 0% dividend yield, whose sales realize gains in the 0% bracket,
    pays no tax, so the candidate changes nothing and is filtered out.
    """
    wages = _wages_by_owner(plan)
    new: list[PriorityData] = []
    for owner, account_ids in _contributable(plan, _402G_TYPES).items():
        if owner not in wages:
            continue
        rules = _payroll_rules(plan, account_ids)
        limit = max(_irs_contribution_room(plan.accounts[aid].account_type, _owner_age(plan, owner), 0)
                    for aid in account_ids)
        if _requested_payroll(plan, rules) >= limit:
            continue
        # Fill the account the person already defers to; otherwise pre-tax first.
        target = next((p.target_account_id for p in rules), None) or min(
            account_ids, key=lambda aid: _402G_TYPES.index(plan.accounts[aid].account_type))
        new.append(PriorityData(priority_rank=0, priority_type="pre_tax_contribution",
                                target_account_id=target, source_income_id=wages[owner]))
    if not new:
        return None
    # Deferrals go ahead of any after-tax rule, which would otherwise take the 415(c) room first.
    after_tax = [p.priority_rank for p in plan.priorities if p.priority_type == "after_tax_401k"]
    families = sorted({EMPLOYER_PLAN_FAMILY[plan.accounts[p.target_account_id].account_type] for p in new})
    return _inserted(plan, "max_401k", f"Max {' and '.join(families)}", new, min(after_tax, default=_next_rank(plan)))


def _hsa_ineligible(plan: PlanData, owner: str) -> bool:
    rows = (plan.tax_settings or {}).get("hsa_coverage", [])
    return any(r.get("owner") == owner and r.get("coverage") == "ineligible"
               and r["start_year"] <= plan.start_year <= (r.get("end_year") or 2300) for r in rows)


def _max_hsa(plan: PlanData) -> _Candidate | None:
    wages = _wages_by_owner(plan)
    if not wages:
        return None  # payroll rules are funded from earned income
    new: list[PriorityData] = []
    for owner, account_ids in _contributable(plan, ("hsa",)).items():
        if _hsa_ineligible(plan, owner):
            continue
        if _requested_payroll(plan, _payroll_rules(plan, account_ids)) == float("inf"):
            continue
        new.append(PriorityData(priority_rank=0, priority_type="pre_tax_contribution",
                                target_account_id=account_ids[0], source_income_id=wages.get(owner)))
    return _appended(plan, "max_hsa", "Max HSA", new) if new else None


def _mega_backdoor(plan: PlanData) -> _Candidate | None:
    """Uncapped after-tax 401(k) rule from each eligible owner's largest W-2 wages.

    It goes right after the existing payroll rules so the section 415(c) room
    it fills already reflects their deferrals and employer money.
    """
    wages = _wages_by_owner(plan, w2_only=True)
    new: list[PriorityData] = []
    for owner, account_ids in _contributable(plan, ("roth_401k",)).items():
        owned = {aid for aid, account in plan.accounts.items() if account.owner == owner}
        if owner not in wages or any(p.priority_type == "after_tax_401k" and p.target_account_id in owned
                                     for p in plan.priorities):
            continue
        new.append(PriorityData(priority_rank=0, priority_type="after_tax_401k",
                                target_account_id=account_ids[0], source_income_id=wages[owner]))
    if not new:
        return None
    at = max((p.priority_rank for p in plan.priorities if p.priority_type in _PAYROLL_TYPES), default=0) + 1
    return _inserted(plan, "mega_backdoor", "Mega backdoor Roth", new, at)


def _estimated_magi(plan: PlanData, baseline: SimulationResult) -> float:
    """First full plan year's income less payroll deductions.

    An estimate: Roth deferrals are subtracted too, and drawdown gains are not
    added. Used only to decide whether the backdoor candidate applies.
    """
    snaps = baseline.yearly_snapshots
    if not snaps:
        return 0.0
    snap = snaps[1] if plan.first_year_fraction < 1 and len(snaps) > 1 else snaps[0]
    if snap.cash_flow is None:
        return snap.gross_income
    return snap.cash_flow.gross_income - snap.cash_flow.payroll_deductions


def _phaseout_start(plan: PlanData, baseline: SimulationResult) -> float | None:
    bounds = _ROTH_IRA_PHASEOUTS.get(plan.filing_status)
    snaps = baseline.yearly_snapshots
    if bounds is None or not snaps:
        return None
    snap = snaps[1] if plan.first_year_fraction < 1 and len(snaps) > 1 else snaps[0]
    factor = 1.0 if plan.filing_status == "married_filing_separately" else (snap.inflation_factor or 1.0)
    return bounds[0] * factor


def _catch_all_rank(plan: PlanData) -> int | None:
    """Rank of the first uncapped surplus rule into an account without an IRS limit."""
    for p in sorted(plan.priorities, key=lambda x: x.priority_rank):
        account = plan.accounts.get(p.target_account_id or "")
        if (p.priority_type in _SURPLUS_TYPES and account is not None and account.account_type not in _IRS_LIMITS
                and account.account_type not in EMPLOYER_PLAN_TYPES
                and p.allocation_mode == "remaining" and p.max_annual_amount is None and p.target_balance is None):
            return p.priority_rank
    return None


def _backdoor_roth(plan: PlanData, baseline: SimulationResult) -> _Candidate | None:
    if any(p.backdoor_roth for p in plan.priorities):
        return None
    wages = _wages_by_owner(plan)
    joint = plan.filing_status == "married_filing_jointly"
    roth_iras = [account_ids[0] for owner, account_ids in _contributable(plan, ("roth_ira",)).items()
                 if owner in wages or (joint and wages)]
    start = _phaseout_start(plan, baseline)
    if not roth_iras or start is None or _estimated_magi(plan, baseline) < start:
        return None
    priorities = list(plan.priorities)
    updated: list[SuggestedRule] = []
    added: list[str] = []
    for aid in roth_iras:
        index = next((i for i, p in enumerate(priorities)
                      if p.priority_type in _SURPLUS_TYPES and p.target_account_id == aid), None)
        if index is None:
            added.append(aid)
        else:
            priorities[index] = replace(priorities[index], backdoor_roth=True)
            updated.append(_rule(priorities[index], change="update"))
    rules = list(updated)
    if added:
        at = _catch_all_rank(plan)
        if at is None:
            at = _next_rank(plan)
        else:
            priorities = [replace(p, priority_rank=p.priority_rank + len(added)) if p.priority_rank >= at else p
                          for p in priorities]
        for i, aid in enumerate(added):
            rule = PriorityData(priority_rank=at + i, priority_type="contribution",
                                target_account_id=aid, backdoor_roth=True)
            priorities.append(rule)
            rules.append(_rule(rule))
    return _Candidate("backdoor_roth", "Backdoor Roth", priorities, rules)


def _flat_tax(plan: PlanData) -> bool:
    return (plan.tax_settings or {}).get("mode") == "flat"


def _roth_conversions(plan: PlanData) -> list[_Candidate]:
    if _flat_tax(plan):
        return []
    sources = _contributable(plan, _CONVERSION_SOURCES)
    targets = _contributable(plan, _CONVERSION_TARGETS)
    for owner in _OWNERS:
        funded = [aid for aid in sources.get(owner, []) if plan.accounts[aid].balance > 0]
        if not funded or owner not in targets:
            continue
        source = max(funded, key=lambda aid: plan.accounts[aid].balance)
        if any(p.priority_type == "roth_conversion" and p.source_account_id == source for p in plan.priorities):
            continue
        target = min(targets[owner], key=lambda aid: _CONVERSION_TARGETS.index(plan.accounts[aid].account_type))
        built = build_candidates(plan, source_account_id=source, target_account_id=target,
                                 bracket_ceilings=ROTH_CONVERSION_CEILINGS, magi_cap=None,
                                 start_milestone_id=None, end_milestone_id=None)
        return [_Candidate("roth_conversion", f"Roth conversions to {round(c.priority.bracket_ceiling_rate * 100)}%",
                           [*plan.priorities, c.priority], [_rule(c.priority)])
                for c in built if c.priority is not None]
    return []


def _gain_harvest(plan: PlanData) -> _Candidate | None:
    if _flat_tax(plan):
        return None
    harvested = {p.source_account_id for p in plan.priorities if p.priority_type == "gain_harvest"}
    new: list[PriorityData] = []
    for aid, account in plan.accounts.items():
        if (account.account_type == "taxable_brokerage" and account.cost_basis is not None
                and account.balance - account.cost_basis > _EPSILON and aid not in harvested):
            built = build_candidates(plan, source_account_id=aid, target_account_id=None,
                                     bracket_ceilings=[GAIN_HARVEST_CEILING], magi_cap=None,
                                     start_milestone_id=None, end_milestone_id=None, strategy_type="gain_harvest")
            new.extend(c.priority for c in built if c.priority is not None)
    return _appended(plan, "gain_harvest", "0% gain harvesting", new) if new else None


def build_suggestion_candidates(plan: PlanData, baseline: SimulationResult) -> list[_Candidate]:
    """Applicable candidates only; each becomes one simulation."""
    candidates = [c for c in (_max_401k(plan), _backdoor_roth(plan, baseline), _max_hsa(plan),
                              _mega_backdoor(plan)) if c]
    candidates.extend(_roth_conversions(plan))
    harvest = _gain_harvest(plan)
    if harvest:
        candidates.append(harvest)
    return candidates


def suggest_tax_strategies(plan: PlanData) -> list[Suggestion]:
    """Improving suggestions, best end-of-plan net worth change first."""
    rate = pre_tax_discount_rate(plan)
    baseline_result = run_simulation(copy.deepcopy(plan))
    baseline = _outcome(baseline_result, rate)
    best: dict[str, Suggestion] = {}
    for candidate in build_suggestion_candidates(plan, baseline_result):
        scenario = copy.deepcopy(plan)
        scenario.priorities = copy.deepcopy(candidate.priorities)
        try:
            outcome = _outcome(run_simulation(scenario), rate)
        except ValueError:
            continue  # the engine rejected this combination; skip it
        if not _improves(baseline, outcome):
            continue
        suggestion = Suggestion(
            key=candidate.key, title=candidate.title,
            lifetime_tax_change=outcome.lifetime_taxes - baseline.lifetime_taxes,
            end_net_worth_change=outcome.end_net_worth - baseline.end_net_worth,
            rules=candidate.rules,
        )
        # Roth conversion ceilings share a key; keep the best of them.
        if candidate.key not in best or suggestion.end_net_worth_change > best[candidate.key].end_net_worth_change:
            best[candidate.key] = suggestion
    return sorted(best.values(), key=lambda s: s.end_net_worth_change, reverse=True)
