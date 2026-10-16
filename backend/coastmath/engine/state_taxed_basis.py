"""Recovery of retirement contributions a state taxed when they were made.

Pennsylvania taxes employee contributions to every retirement plan, and New
Jersey and Massachusetts tax traditional IRA contributions (New Jersey also
403(b) and 457 deferrals), so the simulator adds them back to state income in
the year they are made. Those states then exclude the taxed contributions
when they are withdrawn. This module keeps that basis per account and per
taxing state (``SimState.state_taxed_basis``) and computes the part of each
year's distributions that recovers it.

A state's method is ``contribution_basis_recovery.method`` in
``coastmath/data/tax_brackets_2026.json`` (sources in
``_sources`` in ``tax_brackets_2026.json``):

- ``cost_recovery``: distributions recover the basis first, dollar for dollar
  (Pennsylvania cost recovery; Massachusetts recovers IRA contributions
  before any distribution is income).
- ``pro_rata``: each distribution recovers basis / (year-end balance +
  the year's distributions) of itself (New Jersey IRA worksheet). The balance
  is the account balance when the tax is computed.

Recovery applies only while the person resides in the state that taxed the
contributions. Taxable Roth conversions do not recover basis (not modeled).
"""

from __future__ import annotations

import json
from pathlib import Path

from coastmath.engine.types import SimState

_DATA = json.loads((Path(__file__).resolve().parent.parent / "data" / "tax_brackets_2026.json").read_text())


def recovery_method(state_code: str | None) -> str | None:
    """The state's documented basis recovery method, or None."""
    rule = _DATA["state"].get(state_code or "", {}).get("contribution_basis_recovery")
    return rule["method"] if rule else None


def basis_recovery_by_account(state: SimState, state_code: str | None) -> dict[str, float]:
    """This year's recovered basis by account for the resident state."""
    method = recovery_method(state_code)
    if method is None:
        return {}
    recovered: dict[str, float] = {}
    for account_id, distributed in state.retirement_distributions_this_year.items():
        basis = state.state_taxed_basis.get(account_id, {}).get(state_code or "", 0.0)
        if basis <= 0 or distributed <= 0:
            continue
        if method == "cost_recovery":
            amount = distributed
        elif method == "pro_rata":
            account = state.accounts.get(account_id)
            total = max(0.0, account.balance if account is not None else 0.0) + distributed
            amount = distributed * basis / total if total > 0 else distributed
        else:
            raise ValueError(f"Unknown contribution basis recovery method: {method!r}")
        recovered[account_id] = min(basis, amount)
    return recovered


def basis_distributions(state: SimState, state_code: str | None) -> float:
    """This year's distributions from accounts holding basis taxed by the state."""
    return sum(amount for account_id, amount in state.retirement_distributions_this_year.items()
               if amount > 0 and state.state_taxed_basis.get(account_id, {}).get(state_code or "", 0.0) > 0)


def commit_year(
    state: SimState,
    state_code: str | None,
    recovered: dict[str, float],
    added: dict[str, float],
) -> None:
    """Consume this year's recovered basis, then add this year's taxed contributions."""
    for account_id, amount in recovered.items():
        by_state = state.state_taxed_basis.get(account_id, {})
        if state_code in by_state:
            by_state[state_code] = max(0.0, by_state[state_code] - amount)
    if not state_code:
        return
    for account_id, amount in added.items():
        if amount > 0:
            by_state = state.state_taxed_basis.setdefault(account_id, {})
            by_state[state_code] = by_state.get(state_code, 0.0) + amount
