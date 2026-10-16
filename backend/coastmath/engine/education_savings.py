"""529 qualified tuition program rules (``five_twenty_nine`` accounts).

- Contribution basis: deposits add basis; withdrawals recover it pro rata
  (IRC 529(c)(3)(A) applies the annuity rules of IRC 72). An opening account
  without a recorded basis is treated as all basis at plan start, so only
  earnings made during the projection can be taxed.
- Withdrawals up to the year's qualified education expenses are tax free
  (529(c)(3)(B)). Spending the user funds from a 529 directly counts as
  qualified; other withdrawals use the year's remaining allowance of
  expenses marked as qualified education. The earnings share of the rest is
  ordinary income plus a 10% additional tax (529(c)(6), 530(d)(4)).
- Optional state income tax deduction for contributions, per state data
  (``data/education_savings.json``). Recapture is not modeled.
- 529 balances are outside the owner's gross estate (529(c)(4)).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

EDUCATION_ACCOUNT_TYPE = "five_twenty_nine"

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "education_savings.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    with _DATA_PATH.open() as fh:
        return json.load(fh)


def nonqualified_additional_tax_rate() -> float:
    return float(_data()["federal"]["nonqualified_additional_tax_rate"])


def earnings_fraction(balance: float, basis: float | None) -> float:
    """Share of a withdrawal that is earnings; unknown basis means none."""
    if basis is None or balance <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - basis / balance))


def state_deduction_supported(state_code: str | None) -> bool:
    return (state_code or "") in _data()["state_contribution_deductions"]


def state_contribution_deduction(
    state_code: str | None,
    filing_status: str,
    contributions: float,
    qualified_withdrawals: float = 0.0,
) -> float:
    """State income tax subtraction for this year's 529 contributions.

    Caps are per return per year; a joint return uses the joint cap. States
    not in the data take no deduction.
    """
    rule = _data()["state_contribution_deductions"].get(state_code or "")
    if rule is None:
        return 0.0
    amount = max(0.0, contributions)
    if rule.get("net_of_qualified_withdrawals"):
        amount = max(0.0, amount - max(0.0, qualified_withdrawals))
    cap = rule["cap_joint"] if filing_status == "married_filing_jointly" else rule["cap_single"]
    return amount if cap is None else min(amount, float(cap))
