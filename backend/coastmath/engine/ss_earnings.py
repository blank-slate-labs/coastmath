"""Covered-record estimates and the retirement earnings test, at month precision."""
from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

from coastmath.engine.social_security import claiming_factor
from coastmath.engine.ss_household import (
    month_index,
    owner_birth,
    retirement_fra_index,
    spousal_reduction_factor,
)

RULES = json.loads((Path(__file__).resolve().parents[1] / 'data/social_security_earnings_2026.json').read_text())


def bend_points(eligibility_year: int, wage_index) -> tuple[float, float]:
    published = RULES['bend_points'].get(str(eligibility_year))
    if published:
        return tuple(published)
    scale = wage_index(eligibility_year - 2) / wage_index(2024)
    return tuple(round(x * scale) for x in RULES['bend_points']['2026'])


def pia_from_aime(aime: float, bends: tuple[float, float]) -> float:
    first, second = bends
    rates = RULES['replacement_rates']
    return rates[0] * min(aime, first) + rates[1] * max(0, min(aime, second) - first) + rates[2] * max(0, aime - second)


def aime_from_pia(pia: float, bends: tuple[float, float]) -> float:
    first, second = bends
    rates = RULES['replacement_rates']
    if pia <= first * rates[0]:
        return pia / rates[0]
    if pia <= first * rates[0] + (second - first) * rates[1]:
        return first + (pia - first * rates[0]) / rates[1]
    return second + (pia - first * rates[0] - (second - first) * rates[1]) / rates[2]


class CoveredRecords:
    """Infer equal historical years plus zeros; add each completed future year.

    This estimate preserves the entered PIA without earnings, including when
    covered years are less than 35. It is not an imported SSA earnings record.
    Future earnings first affect the following January, as annual recomputations do.

    The entered PIA is at the plan-start wage level (the bend points of a
    plan-start-year eligibility, earnings indexed to two years earlier), while
    the record is kept at the eligibility-year level: earnings indexed to the
    age-60 year and that year's bend points (42 U.S.C. 415(a)(1)(B), (b)(3)).
    The PIA formula is homogeneous, so the entered PIA is scaled by
    AWI(age-60 year) / AWI(plan start - 2) on the way in and back on the way out.
    An age-60 year at or before that level keeps the entered PIA unscaled.
    """
    def __init__(self, plan, wage_index):
        self.plan = plan
        self.wage_index = wage_index
        self.records = {}
        self.bends = {}
        self.scales = {}
        level = plan.start_year - 2
        for income in plan.income_streams:
            if income.ss_benefit_basis != 'pia' or income.pia_reflects != 'current_record':
                continue
            birth, _ = owner_birth(plan, income.owner)
            bends = bend_points(birth + 62, wage_index)
            scale = wage_index(birth + 60) / wage_index(level) if birth + 60 > level else 1.0
            total = aime_from_pia((income.pia_monthly or 0) * scale, bends) * RULES['computation_months']
            years = income.covered_years_to_date
            # A positive entered PIA with zero covered years cannot describe a record.
            if years == 0 and total > 0:
                raise ValueError('A positive current-record PIA requires at least one covered year')
            self.records[income.id] = [total / years] * years + [0.0] * (35 - years)
            self.bends[income.id] = bends
            self.scales[income.id] = scale

    def adjusted_plan(self):
        streams = []
        for income in self.plan.income_streams:
            if income.id in self.records:
                pia = pia_from_aime(sum(self.records[income.id]) / RULES['computation_months'], self.bends[income.id])
                income = replace(income, pia_monthly=pia / self.scales[income.id])
            streams.append(income)
        return replace(self.plan, income_streams=streams)

    def add_year(self, year, wages, self_employment):
        base = round(RULES['wage_base']['2026'] * self.wage_index(year - 2) / self.wage_index(2024) / RULES['wage_base_rounding']) * RULES['wage_base_rounding']
        for income in self.plan.income_streams:
            if income.id not in self.records:
                continue
            birth, _ = owner_birth(self.plan, income.owner)
            earned = max(0, wages.get(income.owner, 0)) + max(0, self_employment.get(income.owner, 0)) * RULES['self_employment_factor']
            indexed = min(earned, base) * (self.wage_index(birth + 60) / self.wage_index(year) if year < birth + 60 else 1)
            record = self.records[income.id]
            lowest = min(range(35), key=record.__getitem__)
            record[lowest] = max(record[lowest], indexed)


def earnings_test_due(year: int, fra_index: int, earnings: float, wage_index) -> float:
    if month_index(year, 1) >= fra_index:
        return 0.0
    higher = fra_index < month_index(year + 1, 1)
    limits = RULES['exempt_amounts'].get(str(year))
    if limits is None:
        scale = wage_index(year - 2) / wage_index(2024)
        limits = [round(x * scale / 120) * 120 for x in RULES['exempt_amounts']['2026']]
    return max(0, earnings - limits[int(higher)]) / RULES['earnings_divisors'][int(higher)]


def arf_factor(plan, income, claim_index, withheld_months):
    birth, month = owner_birth(plan, income.owner)
    origin = month_index(birth, month)
    fra = retirement_fra_index(birth, origin)
    original = claiming_factor((claim_index - origin) / 12, birth)
    revised = claiming_factor((min(fra, claim_index + withheld_months) - origin) / 12, birth)
    return revised / original if claim_index < fra else 1.0


def spousal_arf_factor(reduction, withheld_months):
    """Multiplier on a spousal-type stream after its adjustment at FRA.

    Act 202(q)(7) (POMS RS 00615.482): months whose benefit was withheld under
    the earnings test leave the reduction period, so the reduction is
    recomputed for the remaining months of entitlement before FRA. A stream
    paid as the excess over another benefit (``offset``) gains the whole
    increase of the larger benefit.
    """
    _, months_early, gross, offset = reduction
    if months_early <= 0 or withheld_months <= 0 or gross <= offset:
        return 1.0
    revised = gross * spousal_reduction_factor(max(0, months_early - withheld_months)) / spousal_reduction_factor(months_early)
    return (revised - offset) / (gross - offset)


def fully_withheld_months(withheld: float, annual_benefit: float, maximum: float) -> int:
    return min(math.floor(maximum + 1e-8), math.floor(withheld / (annual_benefit / 12) + 1e-8)) if annual_benefit > 0 else 0
