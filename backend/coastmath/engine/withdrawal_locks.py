"""Account withdrawal locks: when voluntary withdrawals may start.

A lock (``AccountInfo.withdrawal_lock``, validated by
``coastmath.schemas.account.WithdrawalLock``) keeps an account out of drawdown,
specific expense funding, transfers, Roth conversions, gain harvests, SEPP
payments, charitable gifts and QCDs beyond the RMD until it unlocks. RMDs are
still taken: the legal requirement overrides the user's lock. Contributions,
growth and inheritance are unchanged. Locked balances are not liquid.

Unlock rules, all applied to whole calendar years:

- ``year``: unlocked from January of that year.
- ``milestone``: unlocked from the year the milestone fires. A milestone
  that is not in the simulated plan (a household account shared with a plan
  that lacks it) leaves the account unlocked, with a projection warning.
- ``age``: the owner's age (``self`` or ``spouse``; a joint account uses
  the primary person). As with the age-59½ early-withdrawal status
  (:func:`coastmath.engine.waterfall.is_subject_to_early_withdrawal_penalty`),
  the account is unlocked in a year unless most of that year falls before
  the age. An age is reached at the start of its month; an unknown birth
  month counts as July. So a 62 lock unlocks in the year the owner turns 62
  when born January–July and the following year when born August–December.
"""

from __future__ import annotations

from collections.abc import Iterable

from coastmath.engine.types import AccountInfo, SimState
from coastmath.engine.waterfall import share_of_year_before_age


def lock_owner(account: AccountInfo) -> str:
    """The person whose age unlocks the account; joint uses the primary person."""
    return "spouse" if account.owner == "spouse" else "self"


def is_withdrawal_locked(account: AccountInfo, state: SimState, plan_milestone_ids: set[str]) -> bool:
    """Whether voluntary withdrawals from ``account`` are blocked in ``state.year``."""
    lock = account.withdrawal_lock
    if not lock:
        return False
    kind = lock.get("unlock")
    if kind == "year" and lock.get("year") is not None:
        return state.year < int(lock["year"])
    if kind == "milestone" and lock.get("milestone_id"):
        milestone_id = str(lock["milestone_id"])
        return milestone_id in plan_milestone_ids and milestone_id not in state.triggered_milestones
    if kind == "age" and lock.get("age") is not None:
        owner = lock_owner(account)
        if owner not in state.owner_ages:
            # No partner birth year: fall back to the primary person, as
            # execute_drawdown does for the early-withdrawal penalty.
            owner = "self"
        age = state.owner_ages.get(owner)
        if age is None:
            return False
        return share_of_year_before_age(age, state.owner_birth_months.get(owner), float(lock["age"])) > 0.5
    return False


def update_locked_accounts(state: SimState, plan_milestone_ids: set[str]) -> None:
    """Recompute ``state.locked_account_ids`` for the current year."""
    state.locked_account_ids = {
        account_id for account_id, account in state.accounts.items()
        if account.withdrawal_lock and is_withdrawal_locked(account, state, plan_milestone_ids)
    }


def unresolved_lock_warnings(accounts: Iterable[AccountInfo], plan_milestone_ids: set[str]) -> list[str]:
    """Warn about milestone locks this plan cannot evaluate (they are ignored)."""
    return [
        f"The withdrawal lock on '{account.name or 'an account'}' uses a milestone that is not in this plan, "
        "so withdrawals from it are available any time in this projection. Choose one of this plan's milestones."
        for account in accounts
        if (account.withdrawal_lock or {}).get("unlock") == "milestone"
        and str(account.withdrawal_lock.get("milestone_id")) not in plan_milestone_ids
    ]
