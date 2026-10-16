"""State standard/itemized deductions, exemptions and federal-tax deductions.

A pure evaluator over ``data/state_deduction_rules_2026.json``. It covers the
states listed as ``supported`` in that file's coverage map; every other state
returns ``supported=False`` so the caller keeps its existing path. Sources,
source years and the all-state coverage matrix are in
``_sources`` in ``state_deduction_rules_2026.json``.

For a supported state the result replaces the caller's state standard
deduction and exemption step. It separates four quantities that state returns
treat differently:

* ``deduction``: the standard or itemized deduction from state AGI;
* ``exemption_deduction``: personal, dependent and age exemptions;
* ``federal_tax_subtraction``: the deduction for federal income tax;
* ``nonrefundable_credit``: credits the caller applies after bracket tax.

State itemized deductions start from raw categories, never from the
federally SALT-capped total, except where the state return starts from the
federal Schedule A (Missouri and the spec-driven states whose ``itemized``
basis is ``federal``). Federal tax deductions use each state's own
definition of federal income tax liability. States built only from common
parts (a standard deduction, a state itemized deduction, exemptions and
exemption credits) are evaluated from their data by ``_generic``.

This module does not import ``tax_engine``; the federal SALT cap and
charitable limits it needs are read from its own data file.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

_RULES = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "state_deduction_rules_2026.json").read_text()
)

COVERAGE_VALUES = ("supported", "not_applicable", "legacy", "unverified")
_JOINT = "married_filing_jointly"


@dataclass(frozen=True)
class ItemizedCategories:
    """Raw itemizable amounts before any federal SALT cap or AGI floor."""

    state_local_income_tax: float = 0.0   # paid during the year (cash basis)
    real_estate_tax: float = 0.0
    personal_property_tax: float = 0.0
    mortgage_interest: float = 0.0
    charitable_cash: float = 0.0
    charitable_property: float = 0.0
    medical_expenses: float = 0.0         # gross; each state applies its own AGI floor
    other: float = 0.0
    # Part of ``state_local_income_tax`` paid to local jurisdictions (city,
    # county or school-district income and earnings taxes). Some states allow
    # local income tax but not their own state income tax.
    local_income_tax: float = 0.0


@dataclass(frozen=True)
class FederalTaxComponents:
    """Federal amounts outside ``federal_income_tax_liability``.

    Each state defines its federal income tax deduction from different lines
    of Form 1040, so these are kept apart. All default to zero.
    """

    net_investment_income_tax: float = 0.0               # Form 8960
    early_distribution_additional_tax: float = 0.0       # IRC 72(t), Schedule 2 line 8
    excess_advance_premium_tax_credit_repayment: float = 0.0  # Schedule 2 line 1a
    earned_income_credit: float = 0.0
    additional_child_tax_credit: float = 0.0             # refundable part of IRC 24
    refundable_american_opportunity_credit: float = 0.0
    refundable_adoption_credit: float = 0.0
    premium_tax_credit_allowed: float = 0.0              # Form 8962 line 24
    net_premium_tax_credit: float = 0.0                  # Schedule 3 line 9


@dataclass(frozen=True)
class StateDeductionContext:
    state_code: str                       # 2-letter, upper case
    tax_year: int
    inflation_factor: float               # same factor tax_engine uses for state brackets
    filing_status: str                    # engine filing-status strings
    holder_age: int | None
    spouse_age: int | None
    dependent_count: int
    federal_agi: float
    state_agi: float                      # after SS/retirement/basis/existing state adjustments
    itemized: ItemizedCategories
    federal_itemized_elected: bool        # federal return itemized
    federal_itemized_total: float         # federal allowed itemized (after federal SALT cap)
    federal_standard_deduction: float     # IRC 63(c) including the 63(f) aged amounts
    federal_income_tax_liability: float   # regular income tax + AMT after nonrefundable credits;
                                          # EXCLUDES payroll, SE tax, NIIT, Add'l Medicare
    federal_income_tax_paid: float | None = None    # cash paid in year; None = unknown
    federal_income_tax_refund_received: float | None = None  # prior-year refund; None = unknown
    federal_components: FederalTaxComponents = field(default_factory=FederalTaxComponents)
    # Employee Social Security, Medicare (including Additional Medicare) and
    # railroad retirement tax withheld in the year. None = unknown.
    payroll_taxes_withheld: float | None = None
    self_employment_tax: float = 0.0
    # State AGI before the Social Security subtraction and retirement
    # exclusions, where a state measures a phaseout on it (Missouri line 6).
    # None = use ``state_agi`` and report it.
    state_agi_before_retirement_exclusions: float | None = None
    # Dependents under 17 at year end (IRC 24(c) qualifying children), for
    # rules keyed to the federal child tax credit (North Carolina's child
    # deduction, Arizona's dependent credit). None = use ``dependent_count``
    # and report it.
    children_under_17: int | None = None


@dataclass(frozen=True)
class StateDeductionResult:
    supported: bool                       # False => caller keeps its existing legacy path unchanged
    coverage: str                         # "supported" | "not_applicable" | "legacy" | "unverified"
    use_itemized: bool
    deduction: float                      # amount subtracted from state AGI (std OR itemized)
    exemption_deduction: float            # personal/dependent exemptions after phaseout
    federal_tax_subtraction: float        # federal-income-tax deduction/subtraction (0 if none)
    nonrefundable_credit: float           # e.g. WI itemized-deduction credit; caller floors at tax
    source_year: int                      # year of the published law/form the numbers come from
    diagnostics: tuple[str, ...] = ()     # plain-language assumptions
    # Tax schedule items outside the deduction step (Connecticut). The caller
    # adds ``tax_addition`` to the bracket tax, then subtracts
    # ``tax_credit_rate`` times that total, before every other credit.
    tax_addition: float = 0.0
    tax_credit_rate: float = 0.0


def state_rule_coverage(state_code: str) -> str:
    """Coverage class of a state's deduction rules (``COVERAGE_VALUES``)."""
    return _RULES["coverage"].get((state_code or "").upper(), "unverified")


def uses_federal_tax_deduction(state_code: str, tax_year: int) -> bool:
    """Whether the state deducts federal income tax in ``tax_year``.

    True for the states whose deduction this module computes, and for the
    repealed states only in years before the repeal took effect.
    """
    code = (state_code or "").upper()
    rule = _RULES["states"].get(code)
    if rule is not None and "federal_tax_deduction" in rule:
        return tax_year >= int(_RULES["earliest_tax_year"])
    repealed = _RULES["repealed_federal_tax_deductions"].get(code)
    return repealed is not None and tax_year <= int(repealed["last_tax_year"])


def evaluate_state_deductions(ctx: StateDeductionContext) -> StateDeductionResult:
    """Evaluate one state's deduction rules; see the module docstring."""
    code = (ctx.state_code or "").upper()
    coverage = state_rule_coverage(code)
    rule = _RULES["states"].get(code)
    if coverage != "supported" or rule is None:
        return _unsupported(coverage, int(_RULES["base_tax_year"]))
    table_year = int(rule["table_year"])
    if ctx.tax_year < table_year:
        return _unsupported("unverified", table_year, (
            f"{code} deduction rules are published from {table_year}; "
            f"{ctx.tax_year} keeps the existing calculation.",))
    if ctx.filing_status not in _STATUSES:
        return _unsupported("unverified", table_year, (
            f"Filing status {ctx.filing_status!r} is not covered.",))
    notes: list[str] = []
    if rule.get("indexed") and ctx.tax_year > table_year:
        notes.append(f"{code} uses its {table_year} published amounts, projected with "
                     "the plan's inflation assumption.")
    result = _EVALUATORS.get(code, _generic)(ctx, rule, _scale(ctx, rule), notes)
    if ctx.federal_income_tax_paid is not None or ctx.federal_income_tax_refund_received is not None:
        if "federal_tax_deduction" in rule:
            notes.append(f"{code} deducts the current-year federal liability, so federal "
                         "tax paid and refunds received are not used.")
    return StateDeductionResult(
        supported=True,
        coverage="supported",
        use_itemized=result[0],
        deduction=_money(result[1]),
        exemption_deduction=_money(result[2]),
        federal_tax_subtraction=_money(result[3]),
        nonrefundable_credit=_money(result[4]),
        source_year=table_year,
        diagnostics=tuple(notes),
        tax_addition=_money(result[5]) if len(result) > 5 else 0.0,
        tax_credit_rate=min(1.0, _money(result[6])) if len(result) > 6 else 0.0,
    )


_STATUSES = ("single", _JOINT, "married_filing_separately", "head_of_household")


def _unsupported(coverage: str, source_year: int, diagnostics: tuple[str, ...] = ()) -> StateDeductionResult:
    return StateDeductionResult(
        supported=False, coverage=coverage, use_itemized=False, deduction=0.0,
        exemption_deduction=0.0, federal_tax_subtraction=0.0, nonrefundable_credit=0.0,
        source_year=source_year, diagnostics=diagnostics,
    )


def _money(value: float) -> float:
    return max(0.0, float(value))


def _scale(ctx: StateDeductionContext, rule: dict) -> float:
    """Multiplier for indexed amounts in years after the published table."""
    if not rule.get("indexed") or ctx.tax_year <= int(rule["table_year"]):
        return 1.0
    return max(0.0, float(ctx.inflation_factor))


def _aged_count(ctx: StateDeductionContext) -> int:
    count = int(ctx.holder_age is not None and ctx.holder_age >= 65)
    if ctx.filing_status == _JOINT:
        count += int(ctx.spouse_age is not None and ctx.spouse_age >= 65)
    return count


def _filers(ctx: StateDeductionContext) -> int:
    return 2 if ctx.filing_status == _JOINT else 1


def _salt_cap(tax_year: int, filing_status: str, income: float) -> float:
    """IRC 164(b)(6)-(7) cap on state/local income and property taxes."""
    rule = _RULES["federal_salt_cap"]
    share = (float(rule["married_filing_separately_share"])
             if filing_status == "married_filing_separately" else 1.0)
    floor = float(rule["legacy_cap"]) * share
    if not int(rule["first_raised_year"]) <= tax_year <= int(rule["last_raised_year"]):
        return floor
    if tax_year == 2025:
        cap, threshold = float(rule["cap_2025"]), float(rule["threshold_2025"])
    else:
        growth = (1.0 + float(rule["annual_increase_after_2026"])) ** (tax_year - 2026)
        cap = float(rule["cap_2026"]) * growth
        threshold = float(rule["threshold_2026"]) * growth
    cap *= share
    threshold *= share
    return max(floor, cap - float(rule["phasedown_rate"]) * max(0.0, income - threshold))


def _charitable(cash: float, prop: float, income: float) -> float:
    """Federal percentage limits: property within 30%, then cash within 60%."""
    limits = _RULES["federal_charitable_limits"]
    base = max(0.0, income)
    allowed_property = min(max(0.0, prop), float(limits["capital_gain_property_agi_share"]) * base)
    allowed_cash = min(max(0.0, cash),
                       max(0.0, float(limits["cash_agi_share"]) * base - allowed_property))
    return allowed_property + allowed_cash


def _income(ctx: StateDeductionContext, base: str) -> float:
    return ctx.state_agi if base == "state_agi" else ctx.federal_agi


def _payroll(ctx: StateDeductionContext, notes: list[str], code: str) -> float:
    if ctx.payroll_taxes_withheld is None:
        notes.append(f"{code} itemized deductions include Social Security and Medicare tax; "
                     "withheld payroll tax was not supplied, so none is included.")
        withheld = 0.0
    else:
        withheld = max(0.0, ctx.payroll_taxes_withheld)
    return withheld + max(0.0, ctx.self_employment_tax)


def _state_itemized(ctx: StateDeductionContext, spec: dict, notes: list[str], code: str) -> float:
    """Itemized deductions for a state that defines its own Schedule A."""
    cats = ctx.itemized
    medical_base = _income(ctx, spec["medical_floor_base"])
    medical = max(0.0, max(0.0, cats.medical_expenses)
                  - float(spec["medical_floor_rate"]) * max(0.0, medical_base))
    local = min(max(0.0, cats.local_income_tax), max(0.0, cats.state_local_income_tax))
    income_taxes = 0.0
    if spec["state_income_tax_deductible"]:
        income_taxes += max(0.0, cats.state_local_income_tax) - local
    if spec["local_income_tax_deductible"]:
        income_taxes += local
    property_taxes = max(0.0, cats.real_estate_tax) + max(0.0, cats.personal_property_tax)
    taxes = income_taxes + property_taxes
    if spec["property_taxes_salt_capped"]:
        cap = _salt_cap(ctx.tax_year, ctx.filing_status, _income(ctx, spec["salt_cap_income_base"]))
        if code == "AL":
            # Alabama applies the IRC 164 limit to real estate and personal
            # property taxes; local occupational taxes are listed separately.
            taxes = income_taxes + min(property_taxes, cap)
        else:
            taxes = min(taxes, cap)
    payroll = _payroll(ctx, notes, code) if spec["payroll_taxes_deductible"] else 0.0
    charity = _charitable(cats.charitable_cash, cats.charitable_property,
                          _income(ctx, spec["charitable_limit_base"]))
    return (medical + taxes + payroll + max(0.0, cats.mortgage_interest) + charity
            + max(0.0, cats.other))


def _federal_tax_base(ctx: StateDeductionContext, spec: dict) -> float:
    """The state's definition of federal income tax liability."""
    parts = ctx.federal_components
    total = max(0.0, ctx.federal_income_tax_liability)
    total += sum(max(0.0, getattr(parts, name)) for name in spec["adds"])
    total -= sum(max(0.0, getattr(parts, name)) for name in spec["subtracts"])
    return max(0.0, total)


def _mfs_note(ctx: StateDeductionContext, notes: list[str], code: str) -> None:
    if ctx.filing_status == "married_filing_separately":
        notes.append(f"{code} separate returns: the spouse is assumed to make the same "
                     "standard-or-itemized choice.")


# --- Alabama --------------------------------------------------------------

def _alabama(ctx, rule, _scale_factor, notes):
    status = ctx.filing_status
    chart = rule["standard_deduction"][status]
    agi = math.floor(max(0.0, ctx.state_agi))
    standard = float(chart["maximum"])
    if agi >= chart["reduction_start"]:
        bands = (agi - chart["reduction_start"]) // chart["band_width"] + 1
        standard = max(float(chart["minimum"]), standard - bands * chart["reduction_per_band"])
    itemized = _state_itemized(ctx, rule["itemized"], notes, "AL")
    use_itemized = itemized > standard
    _mfs_note(ctx, notes, "AL")
    personal = float(rule["personal_exemption"][status])
    per_dependent = next(
        float(tier["amount"]) for tier in rule["dependent_exemption_tiers"]
        if tier["maximum_state_agi"] is None or ctx.state_agi <= tier["maximum_state_agi"])
    exemptions = personal + per_dependent * max(0, ctx.dependent_count)
    federal = _federal_tax_base(ctx, rule["federal_tax_deduction"])
    return (use_itemized, itemized if use_itemized else standard, exemptions, federal, 0.0)


# --- Missouri -------------------------------------------------------------

def _missouri(ctx, rule, _scale_factor, notes):
    standard = max(0.0, ctx.federal_standard_deduction)
    use_itemized = False
    deduction = standard
    if ctx.federal_itemized_elected:
        cats = ctx.itemized
        state_income = max(0.0, cats.state_local_income_tax)
        # Earnings taxes (local) stay deductible; only state income tax is removed.
        income_portion = max(0.0, state_income - max(0.0, cats.local_income_tax))
        salt_total = state_income + max(0.0, cats.real_estate_tax) + max(0.0, cats.personal_property_tax)
        allowed_salt = min(salt_total, _salt_cap(ctx.tax_year, ctx.filing_status, ctx.federal_agi))
        if salt_total > allowed_salt and salt_total > 0:
            # Form MO-A Part 2 worksheet: the capped amount in proportion.
            income_portion = allowed_salt * income_portion / salt_total
        itemized = (max(0.0, ctx.federal_itemized_total) + _payroll(ctx, notes, "MO")
                    - income_portion)
        if itemized > standard:
            use_itemized, deduction = True, itemized
    exemptions = (float(rule["head_of_household_exemption"])
                  if ctx.filing_status == "head_of_household" else 0.0)
    spec = rule["federal_tax_deduction"]
    base_agi = ctx.state_agi_before_retirement_exclusions
    if base_agi is None:
        base_agi = ctx.state_agi
        notes.append("MO federal tax percentage is measured on Missouri AGI after pension and "
                     "Social Security exemptions because the earlier figure was not supplied.")
    rate = next(float(tier["rate"]) for tier in spec["percentage_tiers"]
                if tier["maximum_state_agi"] is None or base_agi <= tier["maximum_state_agi"])
    federal = min(_federal_tax_base(ctx, spec) * rate, float(spec["cap"][ctx.filing_status]))
    return (use_itemized, deduction, exemptions, federal, 0.0)


# --- Oregon ---------------------------------------------------------------

def _oregon(ctx, rule, scale, notes):
    status = ctx.filing_status
    standard = float(rule["standard_deduction"][status]) * scale
    if f"standard_deduction.{status}" in rule.get("estimated_amounts", ()):
        notes.append(f"OR {status.replace('_', ' ')} standard deduction uses the state's published estimate.")
    aged = float(rule["aged_additional_deduction"][status])
    if rule.get("aged_additional_deduction_indexed"):
        aged *= scale
    standard += aged * _aged_count(ctx)
    itemized = _state_itemized(ctx, rule["itemized"], notes, "OR")
    use_itemized = itemized > standard
    _mfs_note(ctx, notes, "OR")
    spec = rule["federal_tax_deduction"]
    cap = float(spec["cap"][status]) * scale
    phase = spec["step_phaseout"]
    excess = ctx.federal_agi - float(phase["start"][status])
    if excess >= 0:
        steps = min(int(phase["steps"]), int(excess // float(phase["step_width"][status])) + 1)
        cap *= max(0.0, 1.0 - steps * float(phase["reduction_per_step"]))
    federal = min(_federal_tax_base(ctx, spec), cap)
    credit_rule = rule["exemption_credit"]
    credit = 0.0
    if ctx.federal_agi <= float(credit_rule["federal_agi_cutoff"][status]):
        credit = float(credit_rule["amount"]) * scale * (_filers(ctx) + max(0, ctx.dependent_count))
    return (use_itemized, itemized if use_itemized else standard, 0.0, federal, credit)


# --- Connecticut ----------------------------------------------------------

def _connecticut(ctx, rule, _scale_factor, notes):
    spec = rule["personal_exemption"][ctx.filing_status]
    amount = float(spec["amount"])
    excess = ctx.state_agi - float(spec["reduction_start"])
    if excess > 0:
        steps = math.ceil(excess / float(rule["exemption_reduction_step"]))
        amount = max(0.0, amount - steps * float(rule["exemption_reduction_per_step"]))
    addition, rate = _tax_schedule(ctx, rule["tax_schedule"])
    return (False, 0.0, amount, 0.0, 0.0, addition, rate)


def _segment_amount(income: float, segments: list) -> float:
    """A banded table: above ``over`` the amount is ``base`` plus ``per_step``
    for each ``step`` of excess or fraction of one, at most ``maximum``."""
    amount = 0.0
    for over, step, base, per_step, maximum in segments:
        if income > over:
            steps = math.ceil((income - over) / step)
            amount = min(float(maximum), float(base) + steps * float(per_step))
    return amount


def _tax_schedule(ctx: StateDeductionContext, spec: dict) -> tuple[float, float]:
    """Tax additions and the credit rate applied to tax plus additions.

    Connecticut CGS 12-700(a)(10)(B)-(D) and 12-703: the 2% rate phase-out
    add-back and the benefit recapture (dollar tables by CT AGI) are added to
    the bracket tax, and the personal tax credit is a decimal of that total.
    """
    status, income = ctx.filing_status, max(0.0, ctx.state_agi)
    addition = sum(_segment_amount(income, table[status]) for table in spec["additions"])
    rate = 0.0
    for maximum, decimal in spec["credit_decimal"][status]:
        if maximum is None or income <= maximum:
            rate = float(decimal)
            break
    return addition, rate


# --- Wisconsin ------------------------------------------------------------

def _wi_amount(value: float, scale: float, rounding: int) -> float:
    """Wis. Stat. 71.05(22)(dt): indexed amounts round to $10, a $5 remainder up."""
    if scale == 1.0:
        return float(value)
    return float(math.floor(value * scale / rounding + 0.5) * rounding)


def _wi_standard(rule: dict, status: str, income: float, scale: float) -> float:
    spec = rule["standard_deduction"][status]
    rounding = int(rule["index_rounding"])
    maximum = _wi_amount(spec["maximum"], scale, rounding)
    threshold = _wi_amount(spec["threshold"], scale, rounding)
    amount = max(0.0, maximum - float(spec["rate"]) * max(0.0, income - threshold))
    if spec.get("floor_status"):
        # Wis. Stat. 71.05(22)(dp)1: once the head-of-household amount falls
        # to the single amount, the single formula applies.
        amount = max(amount, _wi_standard(rule, spec["floor_status"], income, scale))
    return amount


def _wisconsin(ctx, rule, scale, notes):
    standard = _wi_standard(rule, ctx.filing_status, ctx.state_agi, scale)
    exemptions = (float(rule["personal_exemption"]) * _filers(ctx)
                  + float(rule["dependent_exemption"]) * max(0, ctx.dependent_count)
                  + float(rule["aged_exemption"]) * _aged_count(ctx))
    credit_rule = rule["itemized_deduction_credit"]
    cats = ctx.itemized
    income = _income(ctx, credit_rule["income_base"])
    medical = max(0.0, max(0.0, cats.medical_expenses)
                  - float(credit_rule["medical_floor_rate"]) * max(0.0, income))
    eligible = (medical + max(0.0, cats.mortgage_interest)
                + _charitable(cats.charitable_cash, cats.charitable_property, income))
    credit = float(credit_rule["rate"]) * max(0.0, eligible - standard)
    if cats.other > 0:
        notes.append("WI itemized deduction credit excludes other itemized amounts "
                     "(only medical, interest, charity and casualty qualify).")
    return (False, standard, exemptions, 0.0, credit)


# --- Spec-driven states ---------------------------------------------------
#
# States whose rules are combinations of the same parts are described by data
# alone (see the "Spec-driven states" section of the data file's ``_sources``): a
# standard deduction, a state itemized deduction, exemptions, exemption
# credits and a few state-specific items. Every dollar figure, threshold and
# rate lives in the JSON file.

def _status_value(value, status: str) -> float:
    """A figure that is either one number or keyed by filing status."""
    return float(value[status]) if isinstance(value, dict) else float(value)


def _index(ctx: StateDeductionContext, rule: dict, spec: dict | None) -> float:
    """Inflation multiplier for an indexed block after the table year."""
    if not spec or not spec.get("indexed") or ctx.tax_year <= int(rule["table_year"]):
        return 1.0
    return max(0.0, float(ctx.inflation_factor))


def _aged_filers(ctx: StateDeductionContext, minimum_age: int = 65) -> int:
    count = int(ctx.holder_age is not None and ctx.holder_age >= minimum_age)
    if ctx.filing_status == _JOINT:
        count += int(ctx.spouse_age is not None and ctx.spouse_age >= minimum_age)
    return count


def _children(ctx: StateDeductionContext, notes: list[str], code: str) -> tuple[int, int]:
    """(dependents under 17, other dependents)."""
    dependents = max(0, ctx.dependent_count)
    if ctx.children_under_17 is None:
        notes.append(f"{code} counts children under 17; every dependent is treated as one "
                     "because their ages were not supplied.")
        return dependents, 0
    under = min(dependents, max(0, ctx.children_under_17))
    return under, dependents - under


def _for_year(spec: dict, key: str, tax_year: int):
    """``spec[key]``, replaced by the latest ``by_year`` entry in effect."""
    value = spec[key]
    for change in sorted(spec.get("by_year", ()), key=lambda item: int(item["from_year"])):
        if int(change["from_year"]) <= tax_year and key in change:
            value = change[key]
    return value


def _step_phaseout(ctx: StateDeductionContext, spec: dict | None, index: float) -> float:
    """Share kept after a reduction of ``per_step`` for each ``step`` (or
    fraction of one) of income above ``start``."""
    if not spec:
        return 1.0
    excess = _income(ctx, spec["income"]) - _status_value(spec["start"], ctx.filing_status) * index
    if excess <= 0:
        return 1.0
    steps = math.ceil(excess / (_status_value(spec["step"], ctx.filing_status) * index))
    return max(0.0, 1.0 - steps * float(spec["per_step"]))


def _linear_phaseout(ctx: StateDeductionContext, spec: dict | None, index: float) -> float:
    """Share kept after a reduction by the fraction (income - start) / width,
    at most one (Maine 36 M.R.S. 5124-C(2), 5125(7), 5126-A(2))."""
    if not spec:
        return 1.0
    status = ctx.filing_status
    excess = _income(ctx, spec["income"]) - _status_value(spec["start"], status) * index
    if excess <= 0:
        return 1.0
    return max(0.0, 1.0 - min(1.0, excess / _status_value(spec["width"], status)))


def _graduated_reduction(ctx: StateDeductionContext, amount: float, spec: dict | None,
                         index: float) -> float:
    """Reduction by rates on income bands, at most ``max_share`` of the amount,
    and exactly ``max_share`` above ``full_above`` (Minnesota 290.0122 subd. 2,
    290.0123 subd. 5)."""
    if not spec or amount <= 0:
        return 0.0
    status = ctx.filing_status
    income = _income(ctx, spec["income"])
    cap = float(spec["max_share"]) * amount
    if income > float(spec["full_above"]) * index:
        return cap
    bands = [(_status_value(start, status) * index, float(rate)) for start, rate in spec["bands"]]
    reduction = 0.0
    for position, (start, rate) in enumerate(bands):
        end = bands[position + 1][0] if position + 1 < len(bands) else math.inf
        reduction += rate * max(0.0, min(income, end) - start)
    return min(reduction, cap)


def _salt_parts(ctx: StateDeductionContext) -> tuple[float, float, float]:
    """(federal SALT allowed after the cap, income taxes, property taxes)."""
    cats = ctx.itemized
    income_taxes = max(0.0, cats.state_local_income_tax)
    property_taxes = max(0.0, cats.real_estate_tax) + max(0.0, cats.personal_property_tax)
    allowed = min(income_taxes + property_taxes,
                  _salt_cap(ctx.tax_year, ctx.filing_status, ctx.federal_agi))
    return allowed, income_taxes, property_taxes


def _income_tax_in_federal(ctx: StateDeductionContext, method: str) -> float:
    """State and local income tax inside the federal itemized total.

    ``full``: everything paid (Nebraska line 8); ``capped_share``: the income
    tax share of the capped amount; ``after_property``: the capped amount
    less property taxes (Utah line 14); ``none``: nothing is removed.
    """
    allowed, income_taxes, property_taxes = _salt_parts(ctx)
    if method == "full":
        return income_taxes
    if method == "capped_share":
        total = income_taxes + property_taxes
        return allowed * income_taxes / total if total > 0 else 0.0
    if method == "after_property":
        return min(income_taxes, max(0.0, allowed - property_taxes))
    return 0.0


def _medical(ctx: StateDeductionContext, spec: dict | None) -> float:
    if not spec:
        return 0.0
    floor = float(spec["rate"]) * max(0.0, _income(ctx, spec["base"]))
    return max(0.0, max(0.0, ctx.itemized.medical_expenses) - floor)


def _pease(ctx: StateDeductionContext, total: float, protected: float, spec: dict | None,
           index: float) -> float:
    """Pre-2018 IRC 68 style limit: the smaller of ``rate`` of income over the
    threshold or ``max_share`` of the deductions it covers."""
    if not spec:
        return total
    excess = _income(ctx, spec["income"]) - _status_value(spec["threshold"], ctx.filing_status) * index
    if excess <= 0:
        return total
    covered = max(0.0, total - protected)
    return total - min(float(spec["max_share"]) * covered, float(spec["rate"]) * excess)


def _ny_adjustment(ctx: StateDeductionContext, total: float, charity: float, spec: dict) -> float:
    """New York IT-196 lines 46-47: the high-income itemized deduction adjustment."""
    income = ctx.state_agi
    if income > float(spec["charity_only_above"][1]):
        return float(spec["charity_share"][1]) * charity
    if income > float(spec["charity_only_above"][0]):
        return float(spec["charity_share"][0]) * charity
    if income <= float(spec["start"]):
        return total
    if income > float(spec["full_band_end"]):
        return total * (1.0 - 2 * float(spec["band_share"]))
    width = float(spec["band_width"])
    if income > float(spec["upper_band_start"]):
        fraction = round(min(income - float(spec["upper_band_start"]), width) / width, 4)
        return total - float(spec["band_share"]) * total * (1.0 + fraction)
    excess = income - _status_value(spec["status_base"], ctx.filing_status)
    if excess <= 0:
        return total
    fraction = round(min(excess, width) / width, 4)
    return total - float(spec["band_share"]) * total * fraction


def _own_itemized(ctx: StateDeductionContext, spec: dict, rule: dict) -> float:
    """A state Schedule A built from the raw categories."""
    cats = ctx.itemized
    status = ctx.filing_status
    medical = _medical(ctx, spec.get("medical_floor"))
    paid = max(0.0, cats.state_local_income_tax)
    local = min(max(0.0, cats.local_income_tax), paid)
    rule_income = spec.get("income_taxes", "none")
    income_taxes = {"none": 0.0, "local": local, "all": paid}[rule_income]
    limit = spec.get("income_taxes_federal_agi_below")
    if limit and ctx.federal_agi >= _status_value(limit, status):
        income_taxes = 0.0
    property_taxes = max(0.0, cats.real_estate_tax) + max(0.0, cats.personal_property_tax)
    taxes = income_taxes + property_taxes
    salt_cap = spec.get("salt_cap")
    if salt_cap == "federal":
        taxes = min(taxes, _salt_cap(ctx.tax_year, status, ctx.federal_agi))
    elif isinstance(salt_cap, (int, float, dict)):
        # A state's own dollar limit on deductible taxes (Minnesota 290.0122 subd. 3).
        taxes = min(taxes, _status_value(salt_cap, status))
    mortgage = max(0.0, cats.mortgage_interest)
    cap = spec.get("mortgage_and_property_tax_cap")
    if cap is not None:
        # G.S. 105-153.5(a)(2)b (North Carolina): mortgage interest and real
        # estate taxes together, for both spouses combined.
        # No other taxes are deductible there.
        taxes, mortgage = 0.0, min(mortgage + max(0.0, cats.real_estate_tax), float(cap))
    elif not spec.get("property_taxes", True):
        taxes -= property_taxes
    charity = (_charitable(cats.charitable_cash, cats.charitable_property, ctx.federal_agi)
               if spec.get("charitable", True) else 0.0)
    if not spec.get("mortgage_interest", True):
        mortgage = 0.0
    other = max(0.0, cats.other) if spec.get("other", True) else 0.0
    total = medical + max(0.0, taxes) + mortgage + charity + other
    cap = spec.get("cap_excluding_medical")
    if cap is not None:
        # Maine 36 M.R.S. 5125(4): medical expenses sit outside the limit.
        total = medical + min(total - medical, float(cap) * _index(ctx, rule, spec))
    total = _pease(ctx, total, medical, spec.get("overall_limitation"),
                   _index(ctx, rule, spec.get("overall_limitation")))
    limit = spec.get("graduated_limit")
    if limit:
        # The limitation covers everything but medical expenses.
        total -= _graduated_reduction(ctx, total - medical, limit, _index(ctx, rule, limit))
    total *= _linear_phaseout(ctx, spec.get("linear_phaseout"),
                              _index(ctx, rule, spec.get("linear_phaseout")))
    if spec.get("high_income_adjustment"):
        total = _ny_adjustment(ctx, total, charity, spec["high_income_adjustment"])
    return max(0.0, total)


def _federal_based_itemized(ctx: StateDeductionContext, spec: dict) -> float:
    """A state deduction that starts from the federal Schedule A total."""
    federal_total = max(0.0, ctx.federal_itemized_total)
    removed = _income_tax_in_federal(ctx, spec["remove_income_taxes"])
    if spec.get("removal_limited_to_excess_over_federal_standard"):
        # New Mexico PIT-1 line 10 worksheet: the income tax added back is at
        # most the amount by which the itemized total exceeds the federal
        # standard deduction.
        removed = min(removed, max(0.0, federal_total - max(0.0, ctx.federal_standard_deduction)))
    total = federal_total - removed
    cap = spec.get("cap_excluding_medical_and_charity")
    if cap is not None:
        # Schedule 511-D (Oklahoma): only medical and charity sit outside the cap.
        protected = (_medical(ctx, {"rate": spec["federal_medical_floor_rate"], "base": "federal_agi"})
                     + _charitable(ctx.itemized.charitable_cash, ctx.itemized.charitable_property,
                                   ctx.federal_agi))
        if total - protected > float(cap):
            total = float(cap) + protected
    phaseout = spec.get("phaseout")
    if phaseout:
        threshold = _status_value(phaseout["threshold"], ctx.filing_status)
        total -= float(phaseout["rate"]) * max(0.0, ctx.federal_agi - threshold)
    return max(0.0, total)


def _exemptions(ctx: StateDeductionContext, rule: dict, notes: list[str], code: str) -> float:
    spec = rule.get("exemptions") or {}
    status, index = ctx.filing_status, _index(ctx, rule, spec)
    rounding = float(spec.get("index_rounding", 0.0))

    def indexed(value) -> float:
        """An amount after indexing, rounded where the statute says so."""
        amount = float(value) * index
        if rounding and index != 1.0:
            amount = math.floor(amount / rounding + 0.5) * rounding
        return amount

    dependents = max(0, ctx.dependent_count)
    if "personal" in spec:
        personal = indexed(_status_value(spec["personal"], status))
    else:
        personal = indexed(spec.get("per_filer", 0.0)) * _filers(ctx)
    basic = (personal + indexed(spec.get("dependent", 0.0)) * dependents
             + indexed(spec.get("dependent_child_extra", 0.0)) * dependents)
    if status == "head_of_household":
        basic += indexed(spec.get("head_of_household_extra", 0.0))
    last_year = spec.get("basic_last_tax_year")
    if last_year is not None and ctx.tax_year > int(last_year):
        notes.append(f"{code} law sets no personal or dependent exemption amount after "
                     f"{last_year}, so none is allowed.")
        basic = 0.0
    tiers = spec.get("per_exemption_tiers")
    if tiers:
        # Each personal and dependent exemption falls with federal AGI
        # (Maryland exemption chart 10A); age exemptions are not reduced.
        count = _filers(ctx) + dependents
        income = _income(ctx, tiers["income"])
        per = next(float(amount) for maximum, amount in tiers[status]
                   if maximum is None or income <= maximum)
        basic = indexed(per) * count
    reduction = spec.get("per_exemption_reduction")
    if reduction:
        # Each personal and dependent exemption is the amount less a rate
        # times income over a base, never below zero (New Mexico's low- and
        # middle-income exemption, NMSA 7-2-5.8).
        excess = max(0.0, _income(ctx, reduction["income"]) - _status_value(reduction["base"], status))
        per = max(0.0, float(reduction["amount"]) - _status_value(reduction["rate"], status) * excess)
        basic = per * (_filers(ctx) + dependents)
    after_first = spec.get("dependent_after_first")
    if after_first and status in after_first["statuses"]:
        # New Mexico NMSA 7-2-39: every dependent but the first, joint and
        # head-of-household returns only.
        basic += float(after_first["amount"]) * max(0, dependents - 1)
    aged = 0.0
    aged_tiers = spec.get("aged_tiers")
    if aged_tiers:
        # A per-person age amount that falls by income band (New Mexico
        # NMSA 7-2-5.2, PIT-ADJ Table 1).
        income = _income(ctx, aged_tiers["income"])
        per_person = next(float(amount) for maximum, amount in aged_tiers[status]
                          if maximum is None or income <= maximum)
        aged += per_person * _aged_filers(ctx)
    for item in spec.get("aged", ()):
        below, at_most = item.get("federal_agi_below"), item.get("federal_agi_at_most")
        if below is not None and ctx.federal_agi >= _status_value(below, status):
            continue
        if at_most is not None and ctx.federal_agi > _status_value(at_most, status):
            continue
        amount = float(item["amount"]) * (index if item.get("indexed", spec.get("indexed")) else 1.0)
        aged += amount * _aged_filers(ctx)
    total = (basic + aged) * _step_phaseout(ctx, spec.get("step_phaseout"), _index(ctx, rule, spec.get("step_phaseout")))
    total *= _linear_phaseout(ctx, spec.get("linear_phaseout"),
                              _index(ctx, rule, spec.get("linear_phaseout")))
    cliff = spec.get("cliff")
    if cliff and _income(ctx, cliff["income"]) > _status_value(cliff["above"], status):
        total = 0.0
    child = rule.get("child_deduction")
    if child:
        under, _ = _children(ctx, notes, code)
        income = _income(ctx, child["income"])
        per_child = next(float(amount) for maximum, amount in child["tiers"][status]
                         if maximum is None or income <= maximum)
        total += per_child * under
    return total


def _credits(ctx: StateDeductionContext, rule: dict, notes: list[str], code: str) -> float:
    spec = rule.get("credits")
    credit = 0.0
    if spec:
        index = _index(ctx, rule, spec)
        dependents = max(0, ctx.dependent_count)
        credit = (float(spec.get("per_filer", 0.0)) * _filers(ctx)
                  + float(spec.get("per_dependent", 0.0)) * dependents
                  + float(spec.get("aged", 0.0)) * _aged_filers(ctx, int(spec.get("aged_minimum_age", 65))))
        if ctx.filing_status == "head_of_household":
            credit += float(spec.get("head_of_household_extra", 0.0))
        if "per_child_under_17" in spec:
            under, older = _children(ctx, notes, code)
            credit += (float(spec["per_child_under_17"]) * under
                       + float(spec.get("per_dependent_17_or_older", 0.0)) * older)
        credit *= index
        phaseout = spec.get("phaseout")
        if phaseout:
            excess = _income(ctx, phaseout["income"]) - _status_value(phaseout["start"], ctx.filing_status)
            if excess > 0:
                bands = math.ceil(excess / float(phaseout["band"]))
                credit *= max(0.0, 1.0 - bands * float(phaseout["rate_per_band"]))
    taxpayer = rule.get("deduction_credit")
    if taxpayer:
        # Utah Code 59-10-1018: a share of the federal deduction (less state
        # income tax in it) and the dependent exemptions, phased out by
        # income above a base amount.
        index = _index(ctx, rule, taxpayer)
        if ctx.federal_itemized_elected:
            federal = (max(0.0, ctx.federal_itemized_total)
                       - _income_tax_in_federal(ctx, taxpayer["remove_income_taxes"]))
        else:
            federal = max(0.0, ctx.federal_standard_deduction)
        base = (float(taxpayer["dependent_exemption"]) * index * max(0, ctx.dependent_count)
                + federal)
        initial = float(taxpayer["rate"]) * base
        excess = max(0.0, _income(ctx, taxpayer["income"])
                     - _status_value(taxpayer["phaseout_base"], ctx.filing_status) * index)
        credit += max(0.0, initial - float(taxpayer["phaseout_rate"]) * excess)
    return credit


def _generic(ctx, rule, _scale_factor, notes):
    code, status = ctx.state_code.upper(), ctx.filing_status
    standard = 0.0
    std_spec = rule.get("standard_deduction")
    if std_spec:
        amount = _for_year(std_spec, "amount", ctx.tax_year)
        if amount == "federal":
            standard = max(0.0, ctx.federal_standard_deduction)
        else:
            index = _index(ctx, rule, std_spec)
            standard = _status_value(amount, status) * index
            if "aged" in std_spec:
                standard += _status_value(std_spec["aged"], status) * index * _aged_filers(ctx)
        standard *= _step_phaseout(ctx, std_spec.get("step_phaseout"),
                                   _index(ctx, rule, std_spec.get("step_phaseout")))
        standard *= _linear_phaseout(ctx, std_spec.get("linear_phaseout"),
                                     _index(ctx, rule, std_spec.get("linear_phaseout")))
        limit = std_spec.get("graduated_limit")
        standard -= _graduated_reduction(ctx, standard, limit, _index(ctx, rule, limit))
        charity_cap = std_spec.get("charitable_cap")
        if charity_cap:
            # ARS 43-1041(I)(2) (Arizona, from 2026): charitable contributions
            # added to the standard deduction, up to a fixed amount.
            given = max(0.0, ctx.itemized.charitable_cash) + max(0.0, ctx.itemized.charitable_property)
            standard += min(given, _status_value(charity_cap, status))
        elif std_spec.get("charitable_share"):
            # ARS 43-1041(I) (Arizona): a share of the charitable deduction
            # that itemizing would have allowed.
            standard += float(std_spec["charitable_share"]) * _charitable(
                ctx.itemized.charitable_cash, ctx.itemized.charitable_property, ctx.federal_agi)
    deduction, use_itemized = standard, False
    item_spec = rule.get("itemized")
    if item_spec:
        election = item_spec["election"]
        allowed = election == "independent" or ctx.federal_itemized_elected
        if allowed:
            itemized = (_federal_based_itemized(ctx, item_spec) if item_spec["basis"] == "federal"
                        else _own_itemized(ctx, item_spec, rule))
            if election == "follow_federal" or itemized > standard:
                deduction, use_itemized = itemized, True
        if ctx.filing_status == "married_filing_separately":
            _mfs_note(ctx, notes, code)
    other = rule.get("other_deductions")
    if other:
        if not other.get("medical_requires_federal_itemized") or ctx.federal_itemized_elected:
            deduction += _medical(ctx, other.get("medical_floor"))
        cap = other.get("property_tax_cap")
        if cap:
            deduction += min(max(0.0, ctx.itemized.real_estate_tax), _status_value(cap, status))
            if ctx.itemized.real_estate_tax > 0:
                notes.append(f"{code} property tax deduction assumes the taxes are on the main home "
                             "and that the deduction is worth more than the alternative credit.")
    exemptions = _exemptions(ctx, rule, notes, code)
    credit = _credits(ctx, rule, notes, code)
    for note in rule.get("notes", ()):
        if isinstance(note, str):
            notes.append(note)
        elif status in note["statuses"]:
            notes.append(note["text"])
    return (use_itemized, deduction, exemptions, 0.0, credit)


_EVALUATORS = {
    "AL": _alabama,
    "MO": _missouri,
    "OR": _oregon,
    "CT": _connecticut,
    "WI": _wisconsin,
}
