"""California personal/senior exemption credits for explicitly eligible owners.

2025 Form 540 lines 7/9 and the AGI Limitation Worksheet govern 2025;
2026 Form 540-ES lines 4/6a direct estimated tax to use those 2025 amounts.
Later years project credit/threshold inflation, not published future tax law.
Dependent counts are explicit for each year. Blind exemptions, part-year
proration and CA AMT are not modeled.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

_RULES = json.loads(
    (
        Path(__file__).resolve().parents[1] / "data" / "ca_exemption_credits.json"
    ).read_text()
)


def ca_exemption_credit(
    federal_agi: float,
    filing_status: str,
    eligible_owners: list[str] | None,
    holder_age: int | None = None,
    spouse_age: int | None = None,
    tax_year: int = 2026,
    inflation_factor: float = 1.0,
    dependent_count: int = 0,
) -> float:
    """Nonrefundable credit amount before capping at the regular state tax.

    Eligibility must be asserted explicitly: an eligible owner cannot be
    claimed as another taxpayer's dependent. None means unknown; [] means
    explicitly no eligible owners. Only joint returns include spouse credits.
    Ages follow the engine's supplied tax-year age convention; no birth-day
    inference is made for the January 1 birthday exception.
    """
    if tax_year < _RULES["published_tax_year"]:
        return 0.0
    if filing_status not in _RULES["phaseout_threshold"]:
        return 0.0
    owners = set(eligible_owners or []) & {"self", "spouse"}
    if filing_status != "married_filing_jointly":
        owners.discard("spouse")
    count = len(owners)
    ages = {"self": holder_age, "spouse": spouse_age}
    senior_count = sum(
        ages[owner] is not None and ages[owner] >= 65 for owner in owners
    )
    if not count and not dependent_count:
        return 0.0
    # Whole-dollar worksheet values. Future indexing is a documented estimate,
    # aligned with the caller's state-table multiplier; statutory steps stay fixed.
    factor = (
        max(0.0, inflation_factor) if tax_year > _RULES["estimate_tax_year"] else 1.0
    )
    personal = math.floor(_RULES["personal_credit"] * factor + 0.5)
    senior = math.floor(_RULES["senior_credit"] * factor + 0.5)
    dependent = math.floor(_RULES["dependent_credit"] * factor + 0.5)
    threshold = math.floor(_RULES["phaseout_threshold"][filing_status] * factor + 0.5)
    excess = max(0, math.floor(max(0.0, federal_agi) + 0.5) - threshold)
    step = (
        _RULES["phaseout_step_mfs"]
        if filing_status == "married_filing_separately"
        else _RULES["phaseout_step"]
    )
    reduction = math.ceil(excess / step) * _RULES["reduction_per_exemption_per_step"]
    return max(
        0.0,
        personal * count + senior * senior_count - reduction * (count + senior_count),
    ) + max(0.0, (dependent - reduction) * max(0, dependent_count))
