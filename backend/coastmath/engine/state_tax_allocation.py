"""Bounded California part-year wage allocation, with explicit estimate limits.

FTB Publication 1100 section B supplies the all-source effective-rate method:
https://www.ftb.ca.gov/forms/misc/1100.html
Schedule CA (540NR), Part IV supplies the AGI deduction ratio; Form 540NR
lines 36–39 supply the taxable-income exemption-credit ratio:
https://www.ftb.ca.gov/forms/2025/2025-540nr-ca-instructions.html
https://www.ftb.ca.gov/forms/2025/2025-540nr-booklet.html

This native projection uses continuous rates/ratios, not the return's four-place
rounding. It does not supply missing work locations, receipt dates, CA itemized
deductions, or comprehensive California conformity/surcharge rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class CAPartYearWageContext:
    """Actual annual modeled wages and demonstrably conforming wage deductions.

    The caller intersects wage activity with residency spans, assuming wages
    are earned and received there. Unknown sourcing or deduction conformity
    must be supplied as unsupported_reason, never inferred from account owner.
    """

    total_w2_wages: float
    ca_w2_wages: float
    conforming_wage_deductions: float = 0.0
    ca_conforming_wage_deductions: float = 0.0
    legacy_residual_in_ca: bool = False
    residency_state_codes: tuple[str, ...] = ()
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class CAPartYearTaxAllocation:
    """None state_tax requests the unchanged, explicitly labeled legacy result."""

    state_tax: float | None
    diagnostics: tuple[str, ...]
    ca_agi: float = 0.0
    total_taxable_income: float = 0.0
    ca_taxable_income: float = 0.0
    deduction_ratio: float = 0.0
    allocated_deduction: float = 0.0
    effective_rate: float = 0.0
    exemption_credit_ratio: float = 0.0
    allocated_exemption_credit: float = 0.0


# Explicitly bounded ordinary-income counterparts, not inferred from an empty
# bracket table. WA's separate capital-gains regime is outside this branch.
_COUNTERPARTS = frozenset({"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WY"})
_RECONCILIATION_TOLERANCE = 1e-6


def allocate_ca_part_year_tax(
    context: CAPartYearWageContext,
    *,
    all_source_agi: float,
    standard_deduction: float,
    gross_tax_on_total_taxable: float,
    all_source_exemption_credit: float,
    residual_components: tuple[tuple[str, float], ...],
    surcharge_threshold: float,
    unsupported_reasons: tuple[str, ...] = (),
) -> CAPartYearTaxAllocation:
    """Allocate one annual regular tax, then the nonrefundable exemption credit.

    all_source_agi is CA-law AGI under the supported adjustments (excluding
    federally taxable Social Security). The credit must already be phased out
    using FEDERAL AGI. gross_tax_on_total_taxable must be BEFORE any credits.
    Each residual component is retained separately so opposing amounts cannot
    disappear into a seemingly supported net amount.
    """
    diagnostics: list[str] = []
    reasons = list(unsupported_reasons)
    if context.unsupported_reason:
        reasons.append(context.unsupported_reason)
    states = set(context.residency_state_codes)
    if len(states) != 2 or "CA" not in states or not (states - {"CA"}) <= _COUNTERPARTS:
        reasons.append("requires CA and one supported ordinary-income-tax-free counterpart state")

    values = {
        "all-source CA AGI": all_source_agi,
        "total W2 wages": context.total_w2_wages,
        "CA-attributed W2 wages": context.ca_w2_wages,
        "conforming wage deductions": context.conforming_wage_deductions,
        "CA conforming wage deductions": context.ca_conforming_wage_deductions,
        "standard deduction": standard_deduction,
        "all-source gross regular tax": gross_tax_on_total_taxable,
        "all-source exemption credit": all_source_exemption_credit,
        "surcharge threshold": surcharge_threshold,
    }
    for name, amount in values.items():
        if not isfinite(amount) or amount < 0:
            reasons.append(f"invalid {name}: {amount!r}")
    for name, amount in residual_components:
        if not isfinite(amount) or amount < -_RECONCILIATION_TOLERANCE:
            reasons.append(f"negative or nonfinite residual component {name}: {amount!r}")
        if isfinite(amount) and abs(amount) > _RECONCILIATION_TOLERANCE:
            destination = "CA" if context.legacy_residual_in_ca else "outside CA"
            diagnostics.append(
                f"California part-year residual {name} ${amount:,.2f} has no supported receipt/source "
                f"allocation; legacy annual-state convention assigns it {destination}. "
                "This residual remains unresolved."
            )

    def fallback() -> CAPartYearTaxAllocation:
        return CAPartYearTaxAllocation(
            state_tax=None,
            diagnostics=tuple(diagnostics) + (
                "California part-year wage allocation unsupported: " + "; ".join(reasons)
                + ". Retained the legacy annual selected-state tax estimate for the whole year.",
            ),
        )

    if reasons:
        return fallback()

    wages = context.total_w2_wages
    ca_wages = context.ca_w2_wages
    deductions = context.conforming_wage_deductions
    ca_deductions = context.ca_conforming_wage_deductions
    if (ca_wages > wages + _RECONCILIATION_TOLERANCE
            or deductions > wages + _RECONCILIATION_TOLERANCE
            or ca_deductions > ca_wages + _RECONCILIATION_TOLERANCE
            or ca_deductions > deductions + _RECONCILIATION_TOLERANCE
            or ca_wages - ca_deductions > wages - deductions + _RECONCILIATION_TOLERANCE):
        reasons.append("wage/deduction attribution does not reconcile with all-source wages")
        return fallback()
    wage_net = wages - deductions
    residual_net = all_source_agi - wage_net
    if (residual_net < -_RECONCILIATION_TOLERANCE
            or abs(residual_net - sum(amount for _, amount in residual_components))
            > _RECONCILIATION_TOLERANCE):
        reasons.append("residual components do not reconcile with all-source CA AGI and known net wages")
        return fallback()

    ca_agi = ca_wages - ca_deductions
    if context.legacy_residual_in_ca:
        ca_agi += max(0.0, residual_net)
    # Only floating-point reconciliation noise can reach these bounds.
    ca_agi = min(all_source_agi, max(0.0, ca_agi))
    total_taxable = max(0.0, all_source_agi - standard_deduction)
    deduction_ratio = min(1.0, ca_agi / all_source_agi) if all_source_agi > 0 else 0.0
    allocated_deduction = standard_deduction * deduction_ratio
    ca_taxable = max(0.0, ca_agi - allocated_deduction)
    # The gross tax includes the separate Behavioral Health tax. Form 540NR
    # line 72 applies that levy to CA taxable income, not a prorated
    # all-source amount, so partial positive bases beyond its statutory (not
    # MFJ-doubled or indexed) threshold remain unsupported.
    # A zero CA base safely owes no regular tax regardless of the annual rate.
    if 0 < ca_taxable < total_taxable and total_taxable > surcharge_threshold:
        reasons.append("separate California Behavioral Health surcharge allocation is not modeled")
        return fallback()

    if ca_taxable == total_taxable and total_taxable > surcharge_threshold:
        diagnostics.append(
            "All-CA income retains the native California estimate, including the separate "
            "Behavioral Health surcharge; existing table limitations are not independently "
            "validated by this allocation."
        )
    if residual_net > _RECONCILIATION_TOLERANCE:
        diagnostics.append(
            "The supported California wage allocation includes positive residual income in "
            "one all-source rate; the residual's CA share retains the disclosed legacy "
            "annual selected-state estimate, without a second residual tax."
        )

    rate = gross_tax_on_total_taxable / total_taxable if total_taxable > 0 else 0.0
    credit_ratio = min(1.0, ca_taxable / total_taxable) if total_taxable > 0 else 0.0
    allocated_credit = all_source_exemption_credit * credit_ratio
    diagnostics.extend((
        "California part-year wages are modeled as earned and received contemporaneously at the "
        "modeled residence; actual work location and deferred/nonresident California-source pay "
        "are not established by residence timing.",
        "California part-year tax uses the native standard-deduction estimate and supported "
        "personal/senior exemption credits; CA itemization, other credits and complete CA "
        "conformity are not modeled.",
        "California part-year tax uses continuous rates and ratios for projection precision; "
        "Form 540NR four-decimal return rounding is not reproduced.",
    ))
    return CAPartYearTaxAllocation(
        state_tax=max(0.0, ca_taxable * rate - allocated_credit),
        diagnostics=tuple(diagnostics),
        ca_agi=ca_agi,
        total_taxable_income=total_taxable,
        ca_taxable_income=ca_taxable,
        deduction_ratio=deduction_ratio,
        allocated_deduction=allocated_deduction,
        effective_rate=rate,
        exemption_credit_ratio=credit_ratio,
        allocated_exemption_credit=allocated_credit,
    )
