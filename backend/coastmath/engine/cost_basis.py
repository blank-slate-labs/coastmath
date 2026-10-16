"""Cost basis tracking for taxable investment accounts.

Provides average-cost proportional gain calculation on withdrawals and
dollar-for-dollar basis updates on deposits.

Note: All capital gains are treated as long-term (LTCG rates). The annual
time-step granularity makes short-term vs long-term distinction impractical.
# TODO: If holding-period tracking is desired, each lot would need purchase
# year and the withdrawal logic would need to distinguish ST vs LT gains.
"""

from __future__ import annotations


def calculate_gain_on_withdrawal(
    withdrawal: float,
    balance: float,
    cost_basis: float | None,
) -> tuple[float, float]:
    """Calculate capital gain and updated cost basis for a withdrawal.

    Uses average-cost proportional method:
        gain = withdrawal * (1 - cost_basis / balance)

    Returns (gain, new_cost_basis).
    """
    # A missing opening basis means the existing position is treated as all
    # basis until a more specific tax-lot history is supplied.  This mirrors
    # the simulator's opening-state normalization and keeps direct SimState
    # callers safe as well.
    basis = balance if cost_basis is None else cost_basis
    if balance <= 0 or withdrawal <= 0:
        return 0.0, max(basis, 0.0)

    # A sale below basis realizes a loss, not zero income. The tax engine
    # nets realized losses and carries the unused amount to later years.
    withdrawal = min(withdrawal, balance)
    gain_fraction = 1.0 - basis / balance
    gain = withdrawal * gain_fraction

    # Basis decreases proportionally to the fraction of balance withdrawn
    ratio = max(1.0 - withdrawal / balance, 0.0)
    new_cost_basis = basis * ratio

    return gain, new_cost_basis


def update_cost_basis_on_deposit(
    deposit: float,
    current_cost_basis: float | None,
) -> float:
    """Update cost basis after a deposit (contribution).

    Contributions increase cost basis dollar-for-dollar.
    """
    basis = 0.0 if current_cost_basis is None else current_cost_basis
    if deposit <= 0:
        return basis
    return basis + deposit
