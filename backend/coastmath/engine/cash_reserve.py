"""Opt-in cash reserve: protected balances spent only as a last resort."""

from __future__ import annotations

from coastmath.engine.types import CashReserveData


def cash_reserve_from_settings(raw: object) -> CashReserveData | None:
    """The engine policy for a stored or requested setting; None when off."""
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    ids = tuple(str(value) for value in raw.get("account_ids") or [])
    amount = float(raw.get("reserve_amount") or 0.0)
    if not ids or amount <= 0:
        return None
    return CashReserveData(account_ids=ids, amount=amount, sweep_excess=bool(raw.get("sweep_excess")))


def reserve_floors(balances: dict[str, float], account_ids: tuple[str, ...], target: float) -> dict[str, float]:
    """Protected dollars per reserve account, filled in the listed order.

    The reserve never exceeds what the accounts hold, so a depleted reserve
    protects nothing.
    """
    floors: dict[str, float] = {}
    left = max(0.0, target)
    for account_id in account_ids:
        if left <= 0:
            break
        protected = min(left, max(0.0, balances.get(account_id, 0.0)))
        if protected > 0:
            floors[account_id] = protected
            left -= protected
    return floors
