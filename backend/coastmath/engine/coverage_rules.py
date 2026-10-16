"""Coverage-aware HSA limits and employee state payroll cash obligations.

Coverage is explicit, never inferred from marriage, residency, age or labels.
Payroll currently models localized W2 wages only, excluding elective SE
coverage. The simulator applies supported federal SALT treatment. Future
years are projections.
"""
import json
from pathlib import Path

from coastmath.engine.types import SimState

_DATA = json.loads((Path(__file__).resolve().parents[1] / "data" / "coverage_rules.json").read_text())


def active_coverage(year: int, rows: list[dict]) -> dict[str, dict]:
    return {r["owner"]: r for r in rows
            if r["start_year"] <= year <= (r.get("end_year") or 2300)}


def _rules(year: int, inflation_factor: float) -> tuple[dict, float]:
    if year < 2025:
        raise ValueError("Explicit coverage rules are supported from 2025 onward.")
    return _DATA[str(min(year, 2026))], (inflation_factor if year > 2026 else 1.0)


def state_payroll_obligations(year: int, w2_by_owner: dict[str, float],
                              coverage: list[dict], inflation_factor: float = 1.0) -> dict[str, float]:
    rows = active_coverage(year, coverage)
    if not rows:
        return {}
    rules, factor = _rules(year, inflation_factor)
    result: dict[str, float] = {}
    for owner, row in rows.items():
        wages = max(0.0, w2_by_owner.get(owner, 0.0))
        employee_fraction = 1.0 - row.get("employer_pays_fraction", 0.0)
        obligations = {}
        if row["state_code"] == "CA" and row.get("ca_sdi"):
            obligations["California SDI"] = wages * rules["ca_sdi"]
        if row["state_code"] == "WA":
            if row.get("wa_paid_leave"):
                obligations["Washington Paid Leave"] = min(wages, rules["wa_wage_cap"] * factor) * rules["wa_paid_leave"] * rules["wa_employee_share"]
            if row.get("wa_cares"):
                obligations["Washington Cares"] = wages * rules["wa_cares"]
        for name, amount in obligations.items():
            result[name] = result.get(name, 0.0) + amount * employee_fraction
    return result


def hsa_contribution_room(account_id: str, state: SimState, age: int) -> float | None:
    """Remaining employee+employer room, with household family base sharing.

    Returns None for unknown coverage (caller preserves legacy self-only
    behavior and reports uncertainty). Catch-up belongs only to its owner.
    Monthly eligibility prorates both base and fixed $1,000 catch-up; no
    December last-month election or future testing-period assumption.
    """
    rows = active_coverage(state.year, state.hsa_coverage)
    account = state.accounts[account_id]
    row = rows.get(account.owner)
    if row is None:
        if any(r["coverage"] == "family" for r in rows.values()):
            # A partial explicit family declaration cannot safely establish
            # the other HSA owner's eligibility or create a second base.
            return 0.0
        return None
    if row["coverage"] == "ineligible":
        return 0.0
    rules, factor = _rules(state.year, state.coverage_inflation_factor)
    owners = {a.owner for a in state.accounts.values() if a.account_type == "hsa"}
    # Unknown partner coverage must not allow an additional family base.
    owners |= rows.keys()
    used = {owner: sum(v for aid, v in state.ytd_contributions.items()
             if aid in state.accounts and state.accounts[aid].account_type == "hsa"
             and state.accounts[aid].owner == owner) for owner in owners}
    bases = dict.fromkeys(owners, 0.0)
    catchups = dict.fromkeys(owners, 0.0)
    household_base = 0.0
    has_family_month = False
    for month in range(1, 13):
        eligible = {o: r for o, r in rows.items() if r["coverage"] != "ineligible"
                    and month in r.get("eligible_months", list(range(1, 13)))}
        family = any(r["coverage"] == "family" for r in eligible.values())
        has_family_month |= family
        monthly_base = rules["hsa_family" if family else "hsa_self_only"] * factor / 12
        household_base += monthly_base * (1 if family and eligible else len(eligible))
        for owner in eligible:
            bases[owner] += monthly_base
            # A spouse's unknown age cannot inherit the primary person's
            # catch-up eligibility. Primary age remains a supported input.
            known_age = state.owner_ages.get(owner, age if owner == "self" else None)
            if known_age is not None and known_age >= 55:
                catchups[owner] += rules["hsa_catchup"] / 12
    # Allocate each person's contributions to their own catch-up first for
    # room accounting, preventing one spouse from consuming the other's.
    base_used = sum(max(0.0, used[o] - catchups[o]) for o in owners)
    shared_room = max(0.0, household_base - base_used)
    own_catchup_room = max(0.0, catchups[account.owner] - used[account.owner])
    own_room = max(0.0, bases[account.owner] + catchups[account.owner] - used[account.owner])
    # Independent self-only coverage does not share a household ceiling.
    # In particular, an unknown spouse retaining the legacy self-only
    # limit must not consume this explicitly eligible owner's limit.
    room = min(own_room, shared_room + own_catchup_room) if has_family_month else own_room
    return 0.0 if room < 1e-8 else room
