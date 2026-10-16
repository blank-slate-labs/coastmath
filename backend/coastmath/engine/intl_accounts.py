"""Country account kinds in the yearly loop (``AccountInfo.intl_account_kind``).

An account with a country account kind follows that kind's rules
(``coastmath.engine.intl_bridge.AccountKind``) instead of the US account rules. Its
stored ``account_type`` comes from the kind's category ("other" for
tax-deferred and tax-free kinds), so IRS limits, RMDs, the 72(t) additional
tax, Roth ordering and SEPP never match it. The rules, in loop order:

- **Conversion** (``converts_to``): at the start of the year the owner
  reaches the age, the account becomes the target kind (a savings kind
  becoming a payout kind).
- **Minimum withdrawal**: a share of the opening balance by the owner's age,
  taken like a required distribution.
- **Earnings tax**: a rate on the year's positive investment growth, taken
  from the balance (tax inside the account).
- **Contributions**: room is the smallest of the annual amount (shared by a
  ``shared_group`` across the owner's kinds), the percent of earned income
  up to its cap, the lifetime cap and the balance cap, inside the age
  window. Employer contributions use the same room, after the employee's
  (only the annual amount when ``percent_limit_excludes_employer``); the
  rest is not deposited, like US employer money over its limit. Amounts are
  indexed with the calendar-year inflation factor
  unless ``index`` is false (rounded to ``index_rounding`` when set). A
  contribution tax is taken from the deposit and a bonus (up to its yearly
  cap) is added to it; both stay inside the account and show in investment
  growth.
- **Room ledger** (``carry_forward``): the owner's room for the kind (or its
  shared group) is the unused room carried into the year plus the year's
  new room, less the year's contributions. New room accrues from the year
  the owner reaches ``age_min``; the percent limit can use the prior year's
  earned income (``percent_of_prior_year_income``; the first plan year uses
  the entered prior-year income, else its own). The plan may give the
  unused room at its start (``intl_settings.starting_room``, before the
  first year's new room). Withdrawals from a kind with
  ``withdrawals_restore_room`` are added back on the next 1 January.
- **Withdrawals**: before the access age the kind's penalty applies; a
  kind with an access age and no penalty is locked until that age
  (:func:`lock_before_access_age`). The
  taxable part of a withdrawal from a kind whose withdrawals are taxable is
  income (``retirement_withdrawal``); a tax-free fraction is excluded up to
  a lifetime tax-free cap. Other withdrawals are not income.

Approximations: contributions made before the plan starts do not count
toward lifetime caps, and the tax-free lifetime cap starts unused. Without an
entered starting room the ledger starts empty, and withdrawals before the
plan starts restore nothing. A partial opening year's earned income is
annualized when it becomes the prior year's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from coastmath.engine import intl_bridge
from coastmath.engine.intl_bridge import AccountKind
from coastmath.engine.types import AccountInfo, SimState


def kind(account: AccountInfo | None) -> AccountKind | None:
    if account is None or not account.intl_account_kind:
        return None
    return intl_bridge.account_kind(account.intl_account_kind)


def _index(state: SimState, amount: float | None, indexed: bool) -> float | None:
    if amount is None:
        return None
    return amount * (state.coverage_inflation_factor if indexed else 1.0)


def start_year(state: SimState, owner_ages: dict[str, int]) -> list[str]:
    """Resolve each account's kind for the year and apply conversions.

    Returns notes for kinds that are not registered (their accounts then
    follow no country rules this year).
    """
    notes = []
    state.intl_kinds = {}
    for account_id, account in state.accounts.items():
        if not account.intl_account_kind:
            continue
        resolved = intl_bridge.account_kind(account.intl_account_kind)
        if resolved is None:
            notes.append(f"{account.name or account_id}: account kind {account.intl_account_kind} is not available; "
                         "its country account rules are not applied.")
            continue
        age = owner_ages.get(account.owner, owner_ages.get("self", 0))
        # A conversion chain (rarely more than one step) settles at once.
        for _ in range(3):
            if (resolved.converts_to is None or resolved.converts_at_age is None
                    or age < resolved.converts_at_age):
                break
            target = intl_bridge.account_kind(resolved.converts_to)
            if target is None:
                break
            account.intl_account_kind = target.ref
            resolved = target
        state.intl_kinds[account_id] = resolved
    state.intl_penalty_rates = {
        account_id: resolved.early_withdrawal_penalty_rate
        for account_id, resolved in state.intl_kinds.items()
        if resolved.access_age is not None and resolved.early_withdrawal_penalty_rate > 0
        and owner_ages.get(state.accounts[account_id].owner, owner_ages.get("self", 0)) < resolved.access_age
    }
    return notes


def lock_before_access_age(state: SimState) -> None:
    """Keep a kind with an access age and no early-withdrawal penalty out of withdrawals before that age.

    Such a kind's balance is preserved until that age: it is
    added to ``state.locked_account_ids`` like a user withdrawal lock, so
    drawdown, transfers and expense funding skip it, while minimum
    withdrawals and contributions continue. Call after the year's user locks
    are recomputed; an account this added in an earlier year is released
    unless the user's own lock still holds it.
    """
    for account_id, account in state.accounts.items():
        if not account.intl_account_kind:
            continue
        resolved = state.intl_kinds.get(account_id)
        preserved = (
            resolved is not None and resolved.access_age is not None
            and resolved.early_withdrawal_penalty_rate <= 0
            and _owner_age(state, account) < resolved.access_age
        )
        if preserved:
            state.locked_account_ids.add(account_id)
        elif not account.withdrawal_lock:
            state.locked_account_ids.discard(account_id)


def minimum_withdrawals(state: SimState, owner_ages: dict[str, int], opening_balances: dict[str, float]) -> float:
    """Take each kind's minimum withdrawal for the year; returns the total (cash)."""
    total = 0.0
    for account_id, resolved in state.intl_kinds.items():
        account = state.accounts[account_id]
        rate = resolved.minimum_withdrawal_rate(owner_ages.get(account.owner, owner_ages.get("self", 0)))
        if rate <= 0 or account.balance <= 0:
            continue
        growth_factor = state.withdrawal_growth_factors.get(account_id, 0.0)
        available = max(0.0, account.balance) / (1 + growth_factor)
        amount = min(available, rate * max(0.0, opening_balances.get(account_id, account.balance) * state.year_fraction))
        if amount <= 0:
            continue
        drag = amount * growth_factor
        account.balance -= drag
        state.withdrawal_growth_adjustment -= drag
        state.withdraw_from(account_id, amount)
        total += amount
    return total


def apply_earnings_tax(state: SimState, opening_balances: dict[str, float]) -> None:
    """Tax inside the account on the year's positive growth (before other flows)."""
    for account_id, resolved in state.intl_kinds.items():
        if resolved.earnings_tax_rate <= 0:
            continue
        account = state.accounts[account_id]
        growth = account.balance - opening_balances.get(account_id, account.balance)
        if growth > 0:
            tax = growth * resolved.earnings_tax_rate
            account.balance -= tax
            state.intl_account_tax_this_year += tax


def _owner_age(state: SimState, account: AccountInfo) -> int:
    return state.owner_ages.get(account.owner, state.owner_ages.get("self", 0))


def _group_ids(state: SimState, account_id: str, resolved: AccountKind) -> list[str]:
    owner = state.accounts[account_id].owner
    group = resolved.limit.shared_group if resolved.limit is not None else None
    if group is None:
        return [account_id]
    return [aid for aid, other in state.intl_kinds.items()
            if other.limit is not None and other.limit.shared_group == group and other.country == resolved.country
            and state.accounts[aid].owner == owner]


def configure_room(state: SimState, settings: dict | None) -> None:
    """Load the plan's entered starting room and first-year prior earned income."""
    settings = settings or {}
    state.intl_starting_room = {}
    for entry in settings.get("starting_room") or ():
        key = (str(entry.get("owner", "self")), str(entry["kind"]))
        state.intl_starting_room[key] = state.intl_starting_room.get(key, 0.0) + max(0.0, float(entry["amount"]))
    state.intl_entered_prior_income = {
        str(owner): max(0.0, float(amount))
        for owner, amount in (settings.get("prior_year_earned_income") or {}).items() if amount is not None
    }
    state.intl_room_carried = {}
    state.intl_prior_earned_income = None


ledger_key = intl_bridge.room_ledger_key


def _ledger_ids(state: SimState, owner: str, key: str) -> list[str]:
    return [aid for aid, other in state.intl_kinds.items()
            if other.limit is not None and other.limit.carry_forward
            and ledger_key(other) == key and state.accounts[aid].owner == owner]


def _carried(state: SimState, owner: str, key: str) -> float:
    """Unused room carried into this year; the first time, the plan's entered starting room."""
    if (owner, key) not in state.intl_room_carried:
        seed = 0.0
        for (entry_owner, ref), amount in state.intl_starting_room.items():
            entered = intl_bridge.account_kind(ref)
            if entry_owner == owner and entered is not None and ledger_key(entered) == key:
                seed += amount
        state.intl_room_carried[(owner, key)] = seed
    return state.intl_room_carried[(owner, key)]


def _annual_amount(state: SimState, limit) -> float | None:
    amount = _index(state, limit.annual_amount, limit.index)
    if amount is not None and limit.index and limit.index_rounding:
        step = limit.index_rounding
        amount = math.floor(amount / step + 0.5) * step
    return amount


def _earned_income(state: SimState, owner: str, limit) -> float:
    """Earned income for a percent limit: this year's, or the prior year's when the kind says so."""
    if limit.percent_of_prior_year_income:
        if state.intl_prior_earned_income is not None:
            return state.intl_prior_earned_income.get(owner, 0.0)
        if owner in state.intl_entered_prior_income:
            return state.intl_entered_prior_income[owner]
    return (state.compensation_by_owner or {}).get(owner, 0.0)


def _new_room(state: SimState, owner: str, limit) -> float | None:
    """This year's new room: the annual amount and the percent of earned income up to its cap."""
    annual = _annual_amount(state, limit)
    if limit.percent_of_earned_income is not None:
        percent_room = limit.percent_of_earned_income * max(0.0, _earned_income(state, owner, limit))
        cap = _index(state, limit.percent_cap_amount, limit.index)
        if cap is not None:
            percent_room = min(percent_room, cap)
        annual = percent_room if annual is None else min(annual, percent_room)
    return annual


def _accrual(state: SimState, owner: str, limit) -> float:
    """New room added to a ledger this year (none before ``age_min``)."""
    age = state.owner_ages.get(owner, state.owner_ages.get("self", 0))
    if limit.age_min is not None and age < limit.age_min:
        return 0.0
    return max(0.0, _new_room(state, owner, limit) or 0.0)


def contribution_room(account_id: str, state: SimState, *, employer: bool = False) -> float:
    """Room left this year for contributions to a country-kind account.

    Contributions so far count employer money too. With
    ``percent_limit_excludes_employer`` the percent of earned income limits
    only the member's own contributions; ``employer`` asks for the room an
    employer contribution has, which that percent limit does not bind.
    """
    resolved = state.intl_kinds.get(account_id)
    if resolved is None:
        return 0.0
    limit = resolved.limit
    if limit is None:
        return float("inf")
    account = state.accounts[account_id]
    age = _owner_age(state, account)
    if (limit.age_min is not None and age < limit.age_min) or (limit.age_max is not None and age > limit.age_max):
        return 0.0
    rooms = []
    if limit.carry_forward:
        key = ledger_key(resolved)
        used = sum(state.ytd_contributions.get(aid, 0.0) for aid in _ledger_ids(state, account.owner, key))
        rooms.append(_carried(state, account.owner, key) + _accrual(state, account.owner, limit) - used)
    elif limit.percent_limit_excludes_employer:
        group = _group_ids(state, account_id, resolved)
        group_used = sum(state.ytd_contributions.get(aid, 0.0) for aid in group)
        annual = _annual_amount(state, limit)
        if annual is not None:
            rooms.append(annual - group_used)
        if not employer:
            member_used = group_used - sum(state.ytd_employer_contributions.get(aid, 0.0) for aid in group)
            percent_room = limit.percent_of_earned_income * max(0.0, _earned_income(state, account.owner, limit))
            cap = _index(state, limit.percent_cap_amount, limit.index)
            rooms.append((percent_room if cap is None else min(percent_room, cap)) - member_used)
    else:
        group_used = sum(state.ytd_contributions.get(aid, 0.0) for aid in _group_ids(state, account_id, resolved))
        annual = _new_room(state, account.owner, limit)
        if annual is not None:
            rooms.append(annual - group_used)
    if limit.lifetime_cap is not None:
        rooms.append(_index(state, limit.lifetime_cap, limit.index)
                     - state.intl_lifetime_contributions.get(account_id, 0.0)
                     - state.ytd_contributions.get(account_id, 0.0))
    if limit.balance_cap is not None:
        rooms.append(_index(state, limit.balance_cap, limit.index) - account.balance)
    return max(0.0, min(rooms)) if rooms else float("inf")


def room_left(state: SimState) -> dict[tuple[str, str], float]:
    """Each room ledger's unused room after this year's flows (carried into next year)."""
    result: dict[tuple[str, str], float] = {}
    seen: set[tuple[str, str]] = set()
    for account_id, resolved in state.intl_kinds.items():
        limit = resolved.limit
        if limit is None or not limit.carry_forward:
            continue
        owner = state.accounts[account_id].owner
        key = ledger_key(resolved)
        if (owner, key) in seen:
            continue
        seen.add((owner, key))
        ids = _ledger_ids(state, owner, key)
        used = sum(state.ytd_contributions.get(aid, 0.0) for aid in ids)
        remaining = max(0.0, _carried(state, owner, key) + _accrual(state, owner, limit) - used)
        if limit.withdrawals_restore_room:
            remaining += sum(max(0.0, state.withdrawals_this_year.get(aid, 0.0)) for aid in ids)
        result[(owner, key)] = remaining
    return result


def after_contribution(state: SimState, account_id: str, amount: float) -> None:
    """Apply the contribution tax and bonus to a deposited contribution."""
    resolved = state.intl_kinds.get(account_id)
    if resolved is None or amount <= 0:
        return
    account = state.accounts[account_id]
    adjustment = 0.0
    if resolved.contribution_tax_rate > 0:
        tax = amount * resolved.contribution_tax_rate
        adjustment -= tax
        state.intl_account_tax_this_year += tax
    if resolved.bonus_rate > 0:
        bonus = amount * resolved.bonus_rate
        cap = _index(state, resolved.bonus_cap, True)
        if cap is not None:
            bonus = min(bonus, max(0.0, cap - state.intl_bonus_this_year.get(account_id, 0.0)))
        state.intl_bonus_this_year[account_id] = state.intl_bonus_this_year.get(account_id, 0.0) + bonus
        adjustment += bonus
    if adjustment:
        account.balance += adjustment
        # Tax and bonus stay inside the account: investment growth, not cash.
        state.withdrawal_growth_adjustment += adjustment


@dataclass(frozen=True)
class WithdrawalIncome:
    """This year's withdrawals from country-kind accounts, by tax treatment."""

    taxable_by_owner: dict[str, float]
    tax_free_used: dict[str, float]  # account -> tax-free amount counted against its lifetime cap

    @property
    def taxable(self) -> float:
        return sum(self.taxable_by_owner.values())


def withdrawal_income(state: SimState) -> WithdrawalIncome:
    """The taxable part of this year's country-kind withdrawals (deterministic, uncommitted)."""
    taxable: dict[str, float] = {}
    tax_free: dict[str, float] = {}
    for account_id, resolved in state.intl_kinds.items():
        if resolved.category != "tax_deferred" or not resolved.withdrawal_taxable:
            continue
        amount = state.withdrawals_this_year.get(account_id, 0.0)
        if amount <= 0:
            continue
        free = amount * resolved.tax_free_withdrawal_fraction
        if resolved.tax_free_lifetime_cap is not None:
            cap = _index(state, resolved.tax_free_lifetime_cap, True)
            free = min(free, max(0.0, cap - state.intl_tax_free_used.get(account_id, 0.0)))
        tax_free[account_id] = free
        owner = state.accounts[account_id].owner
        taxable[owner] = taxable.get(owner, 0.0) + amount - free
    return WithdrawalIncome(taxable, tax_free)


def deductible_contributions_by_owner(state: SimState) -> dict[str, float]:
    """Employee contributions this year to kinds whose contributions are deductible."""
    result: dict[str, float] = {}
    for account_id, resolved in state.intl_kinds.items():
        if not resolved.contribution_deductible:
            continue
        amount = (state.ytd_contributions.get(account_id, 0.0)
                  - state.ytd_employer_contributions.get(account_id, 0.0))
        if amount > 0:
            owner = state.accounts[account_id].owner
            result[owner] = result.get(owner, 0.0) + amount
    return result


def finish_year(state: SimState) -> None:
    """Commit lifetime contributions, tax-free withdrawals and the room ledger at year end.

    The year's earned income becomes next year's prior-year income
    (annualized for a partial opening year).
    """
    state.intl_room_carried.update(room_left(state))
    fraction = state.year_fraction
    state.intl_prior_earned_income = {
        owner: (amount / fraction if 0 < fraction < 1 else amount)
        for owner, amount in (state.compensation_by_owner or {}).items()
    }
    for account_id, amount in withdrawal_income(state).tax_free_used.items():
        state.intl_tax_free_used[account_id] = state.intl_tax_free_used.get(account_id, 0.0) + amount
    for account_id in state.intl_kinds:
        contributed = state.ytd_contributions.get(account_id, 0.0)
        if contributed > 0:
            state.intl_lifetime_contributions[account_id] = (
                state.intl_lifetime_contributions.get(account_id, 0.0) + contributed)
