"""Financial wellness scorecard: key plan ratios graded against benchmarks.

Every metric reads one deterministic projection (``run_simulation``) and the
engine ``PlanData``. Nothing here re-runs or changes accounting: each value is
a ratio or a reading of figures the projection already reports.

Grading uses two thresholds per metric. ``better="higher"``: a value at or
above ``strong_at`` is strong, at or above ``fair_at`` is fair,
anything lower needs attention. ``better="lower"`` mirrors it (at or below).

Year readings:

- "First year" is the projection's first year. Flow-over-flow ratios of the
  same year (savings rate, debt payments) need no annualization; a flow set
  against a balance or an annual benchmark is annualized by dividing by the
  opening year's ``first_year_fraction``.
- "Retirement" is the plan holder's retirement milestone, found as Monte Carlo
  finds it (``monte_carlo._retirement_milestone``: the first milestone whose
  name mentions retirement and not a partner). The first retirement year is
  the first full calendar year after the milestone's year, read against
  balances at its start (the milestone year's closing balances). A plan whose
  milestone fired in or before its first year is already retired: its first
  retirement year is the first projection year, read against opening balances.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from coastmath.engine import intl_accounts, intl_bridge
from coastmath.engine.intl_regime import account_category
from coastmath.engine.monte_carlo import _retirement_milestone
from coastmath.engine.state_retirement_exclusion import STREAM_CATEGORY_SOURCES
from coastmath.engine.types import PlanData
from coastmath.schemas.simulation import SimulationResult, YearSnapshot

Status = Literal["strong", "fair", "needs_attention", "not_applicable"]
Unit = Literal["percent", "months", "ratio", "multiple", "currency", "year", "age"]

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

#: CoastMath planning threshold: saving 20% of gross income or more is strong.
SAVINGS_RATE_STRONG = 0.20
#: CoastMath planning threshold: saving under 10% of gross income needs attention.
SAVINGS_RATE_FAIR = 0.10
#: CoastMath planning threshold: six months of essential spending in cash is strong.
EMERGENCY_FUND_STRONG = 6.0
#: CoastMath planning threshold: under three months needs attention.
EMERGENCY_FUND_FAIR = 3.0
#: CoastMath planning threshold: debt payments at or under 20% of gross income are strong.
DEBT_TO_INCOME_STRONG = 0.20
#: Fannie Mae's 36% maximum total debt-to-income ratio for manually
#: underwritten mortgages (Selling Guide B3-6-02): above it needs attention.
DEBT_TO_INCOME_FAIR = 0.36
#: Savings-by-age targets (age, multiple of salary) from Fidelity's published
#: retirement savings milestones (1x by 30, 3x by 40, 6x by 50, 8x by 60,
#: 10x by 67). Its methodology assumes saving starts at 25, so the target is
#: 0x at 25. Linear between points, flat after 67.
SAVINGS_TARGETS: tuple[tuple[int, float], ...] = (
    (25, 0.0), (30, 1.0), (40, 3.0), (50, 6.0), (60, 8.0), (67, 10.0),
)
#: CoastMath planning threshold: half the age target or more is fair.
SAVINGS_TARGET_FAIR_SHARE = 0.5
#: Withdrawal rate is strong at 4% or less: the published safe initial
#: withdrawal rate research (Bengen, Journal of Financial Planning, 1994).
WITHDRAWAL_RATE_STRONG = 0.04
#: CoastMath planning threshold: a first-year withdrawal rate over 5% needs attention.
WITHDRAWAL_RATE_FAIR = 0.05
#: CoastMath planning threshold: guaranteed income covering all essential spending is strong.
GUARANTEED_INCOME_STRONG = 1.0
#: CoastMath planning threshold: covering under half of essential spending needs attention.
GUARANTEED_INCOME_FAIR = 0.5
#: CoastMath planning threshold: half or less of invested balances pre-tax is strong.
PRE_TAX_SHARE_STRONG = 0.5
#: CoastMath planning threshold: more than three quarters pre-tax needs attention.
PRE_TAX_SHARE_FAIR = 0.75
#: CoastMath planning threshold: every projection year funded is strong.
FUNDED_YEARS_STRONG = 1.0
#: CoastMath planning threshold: a first shortfall in the last tenth of the
#: projection is fair; an earlier one needs attention.
FUNDED_YEARS_FAIR = 0.9
#: CoastMath planning threshold: independence within five years after the
#: retirement year is fair; later (or never) needs attention.
FI_TIMING_GRACE_YEARS = 5

#: Unfunded expenses below half a dollar are rounding, not a shortfall.
_UNFUNDED_TOLERANCE = 0.5
#: The survivor top-up row the engine adds to a Social Security survivor.
_SURVIVOR_TOP_UP = "Social Security survivor top-up"
#: Investment balances exclude cash and education savings (account_category
#: files a 529 as tax free; it does not fund retirement).
_EDUCATION_TYPES = frozenset({"five_twenty_nine"})


@dataclass(frozen=True)
class Bands:
    better: Literal["higher", "lower"]
    fair_at: float
    strong_at: float


@dataclass(frozen=True)
class WellnessMetric:
    key: str
    label: str
    unit: Unit
    status: Status
    value: float | None = None
    bands: Bands | None = None
    basis_year: int | None = None
    section: str | None = None


@dataclass(frozen=True)
class WellnessResult:
    start_year: int
    metrics: list[WellnessMetric]


def grade(value: float | None, bands: Bands) -> Status:
    """The status of ``value`` against ``bands``; a missing value needs attention."""
    if value is None:
        return "needs_attention"
    if bands.better == "higher":
        if value >= bands.strong_at:
            return "strong"
        return "fair" if value >= bands.fair_at else "needs_attention"
    if value <= bands.strong_at:
        return "strong"
    return "fair" if value <= bands.fair_at else "needs_attention"


def savings_target(age: int) -> float:
    """The savings-by-age target multiple at ``age`` (linear between points)."""
    points = SAVINGS_TARGETS
    if age <= points[0][0]:
        return points[0][1]
    for (age_a, mult_a), (age_b, mult_b) in pairwise(points):
        if age <= age_b:
            return mult_a + (mult_b - mult_a) * (age - age_a) / (age_b - age_a)
    return points[-1][1]


# ---------------------------------------------------------------------------
# Readings of the projection
# ---------------------------------------------------------------------------

class _Plan:
    """Name and account classifications the metrics read from ``PlanData``."""

    def __init__(self, plan: PlanData):
        self.plan = plan
        streams = [s for s in plan.income_streams if s.is_active]
        self.earned_names = {s.name for s in streams
                             if s.is_earned_income and not s.is_social_security and s.tax_category != "nontaxable"}
        ss_names = {s.name for s in streams if s.is_social_security}
        # Auxiliary Social Security streams are named "<worker stream> (<kind>)".
        self.ss_prefixes = tuple(f"{name} (" for name in ss_names)
        benefit_labels = set()
        for benefit in (plan.intl_settings or {}).get("benefits") or []:
            rule = intl_bridge.benefit_rule(benefit["rule"])
            if rule is not None:
                benefit_labels.add(str(getattr(rule, "label", benefit["rule"])))
        self.guaranteed_names = (ss_names | benefit_labels | {_SURVIVOR_TOP_UP}
                                 | {s.name for s in streams
                                    if s.pension_formula or s.tax_category in STREAM_CATEGORY_SOURCES})
        self.liability_names = Counter(liab.name for liab in plan.liabilities)
        self.categories = {aid: account_category(acct, intl_accounts.kind(acct)) for aid, acct in plan.accounts.items()}

    def accounts_in(self, balances: dict[str, float], *categories: str) -> float:
        """Balances of accounts in ``categories``. Accounts the engine adds
        (the cash that holds an unallocated surplus) are cash."""
        return sum(value for aid, value in balances.items()
                   if self.categories.get(aid, "cash") in categories
                   and (aid not in self.plan.accounts or self.plan.accounts[aid].account_type not in _EDUCATION_TYPES))

    def earned_income(self, snap: YearSnapshot) -> float:
        rows = snap.cash_flow.income_sources if snap.cash_flow else []
        return sum(row.amount for row in rows if row.name in self.earned_names)

    def guaranteed_income(self, snap: YearSnapshot) -> float:
        rows = snap.cash_flow.income_sources if snap.cash_flow else []
        return sum(row.amount for row in rows
                   if row.name in self.guaranteed_names or row.name.startswith(self.ss_prefixes))

    def debt_payments(self, snap: YearSnapshot) -> float:
        """Loan payments: the engine's essential rows named after a loan.

        Loan rows follow every ordinary expense row in a year, so when an
        expense shares a loan's name the last rows of that name are the loan's.
        """
        rows = snap.cash_flow.expenses if snap.cash_flow else []
        total = 0.0
        for name, count in self.liability_names.items():
            matches = [row.amount for row in rows
                       if row.name == name and row.category == "essential" and row.discretionary_amount is None]
            total += sum(matches[-count:])
        return total


def essential_spending(snap: YearSnapshot) -> float:
    """The year's essential spending from the engine's own expense categories.

    Essential and uncategorized rows count in full (the engine never cuts an
    uncategorized expense); a row with a discretionary percent counts its
    essential part. Discretionary rows and state payroll taxes do not count.
    """
    rows = snap.cash_flow.expenses if snap.cash_flow else []
    total = 0.0
    for row in rows:
        if row.discretionary_amount is not None:
            total += row.amount - row.discretionary_amount
        elif row.category in ("essential", None):
            total += row.amount
    return total


def saved_from_income(snap: YearSnapshot) -> float:
    """Money saved from the year's income: contributions made through payroll
    (employee deferrals and employer money, which gross income includes) plus
    the positive surplus. Surplus-funded allocation rows are part of the
    surplus, so they are not added again; payroll expenses are not saving."""
    if snap.cash_flow is None:
        return max(0.0, snap.net_cash_flow)
    payroll = sum(row.amount for row in snap.cash_flow.contributions if row.source in ("payroll", "employer"))
    return payroll + max(0.0, snap.net_cash_flow)


def portfolio_withdrawals(snap: YearSnapshot) -> float:
    """Withdrawals from accounts: the withdrawal order, RMDs and a 72(t) series."""
    if snap.cash_flow is None:
        return 0.0
    drawn = sum(row.amount for row in snap.cash_flow.drawdowns)
    return drawn + sum(row.amount for row in snap.cash_flow.income_sources if row.source in ("rmd", "sepp"))


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _metric(key: str, label: str, unit: Unit, section: str | None, value: float | None,
            bands: Bands | None, basis_year: int | None) -> WellnessMetric:
    if bands is None or basis_year is None:
        return WellnessMetric(key=key, label=label, unit=unit, status="not_applicable", section=section)
    return WellnessMetric(key=key, label=label, unit=unit, status=grade(value, bands), value=value,
                          bands=bands, basis_year=basis_year, section=section)


# ---------------------------------------------------------------------------
# The scorecard
# ---------------------------------------------------------------------------

def wellness_scorecard(plan: PlanData, result: SimulationResult) -> WellnessResult:
    """Grade the plan's key ratios from its deterministic projection ``result``."""
    snaps = result.yearly_snapshots
    meta = result.metadata
    info = _Plan(plan)
    first = snaps[0]
    fraction = meta.first_year_fraction or 1.0
    by_year = {snap.year: snap for snap in snaps}
    opening = result.initial_snapshot
    opening_accounts = opening.accounts if opening is not None else {aid: a.balance for aid, a in plan.accounts.items()}
    earning = info.earned_income(first) > 0

    # Retirement: the milestone year and the first retirement year's reading.
    milestone = _retirement_milestone(result)
    milestone_year = milestone[2] if milestone is not None else None
    already_retired = milestone_year is not None and milestone_year <= meta.start_year
    retirement_year: int | None = None
    retirement_balances: dict[str, float] = {}
    retirement_liquid_ids: set[str] = set()
    if already_retired:
        retirement_year = first.year
        retirement_balances = opening_accounts
        retirement_liquid_ids = set(opening_accounts) - set(first._locked_account_ids)
    elif milestone_year is not None and milestone_year + 1 in by_year:
        retirement_year = milestone_year + 1
        prior = by_year[milestone_year]
        retirement_balances = prior.accounts
        retirement_liquid_ids = set(prior.accounts) - set(prior._locked_account_ids)

    metrics: list[WellnessMetric] = []

    # Savings rate: payroll saving plus the positive surplus / gross income.
    value = _ratio(saved_from_income(first), first.gross_income) if earning else None
    metrics.append(_metric(
        # Labelled with its basis: the Overview's savings rate is net cash flow alone.
        "savings_rate", "Savings rate incl. payroll", "percent", "income_allocation", value,
        Bands("higher", SAVINGS_RATE_FAIR, SAVINGS_RATE_STRONG) if value is not None else None,
        first.year))

    # Emergency fund: opening cash balances / monthly essential spending.
    monthly_essential = essential_spending(first) / (12 * fraction)
    value = _ratio(info.accounts_in(opening_accounts, "cash"), monthly_essential)
    metrics.append(_metric(
        "emergency_fund", "Emergency fund", "months", "accounts", value,
        Bands("higher", EMERGENCY_FUND_FAIR, EMERGENCY_FUND_STRONG) if value is not None else None,
        first.year))

    # Debt payments to income: first-year loan payments / gross income.
    debt = info.debt_payments(first)
    value = _ratio(debt, first.gross_income) if debt > 0 else None
    metrics.append(_metric(
        "debt_to_income", "Debt payments to income", "percent", "property_debt", value,
        Bands("lower", DEBT_TO_INCOME_FAIR, DEBT_TO_INCOME_STRONG) if value is not None else None,
        first.year))

    # Savings to income against the savings-by-age target: opening account
    # balances (no home, no debt) over a full year of earned income.
    target = savings_target(first.age)
    value = None
    if earning and target > 0:
        unlocked = {aid: v for aid, v in opening_accounts.items() if aid not in first._locked_account_ids}
        savings = info.accounts_in(unlocked, "cash", "taxable", "tax_deferred", "tax_free")
        value = _ratio(savings, info.earned_income(first) / fraction)
    metrics.append(_metric(
        "savings_to_income", "Savings to income", "multiple", "accounts", value,
        Bands("higher", target * SAVINGS_TARGET_FAIR_SHARE, target) if value is not None else None,
        first.year))

    # Withdrawal rate at retirement: withdrawals / liquid portfolio at its start.
    value = None
    if retirement_year is not None:
        portfolio = sum(v for aid, v in retirement_balances.items() if aid in retirement_liquid_ids)
        withdrawals = portfolio_withdrawals(by_year[retirement_year])
        if retirement_year == first.year:
            withdrawals /= fraction
        value = _ratio(withdrawals, portfolio)
    metrics.append(_metric(
        "withdrawal_rate", "Withdrawal rate at retirement", "percent", "drawdown", value,
        Bands("lower", WITHDRAWAL_RATE_FAIR, WITHDRAWAL_RATE_STRONG) if value is not None else None,
        retirement_year))

    # Guaranteed income coverage: the first full year of guaranteed income
    # in retirement (its first year when only a partial year exists).
    value, basis = None, None
    if retirement_year is not None:
        candidates = [snap for snap in snaps if snap.year >= retirement_year
                      and info.guaranteed_income(snap) > 0 and essential_spending(snap) > 0]
        full = [snap for snap in candidates if snap.year == first.year
                or (snap.year - 1 in by_year and info.guaranteed_income(by_year[snap.year - 1]) > 0)]
        chosen = (full or candidates or [None])[0]
        if chosen is not None:
            basis = chosen.year
            value = info.guaranteed_income(chosen) / essential_spending(chosen)
    metrics.append(_metric(
        "guaranteed_income", "Guaranteed income coverage", "percent", "income", value,
        Bands("higher", GUARANTEED_INCOME_FAIR, GUARANTEED_INCOME_STRONG) if value is not None else None,
        basis))

    # Pre-tax share at retirement: tax-deferred / invested balances.
    value = None
    if retirement_year is not None:
        invested = info.accounts_in(retirement_balances, "tax_deferred", "tax_free", "taxable")
        value = _ratio(info.accounts_in(retirement_balances, "tax_deferred"), invested)
    metrics.append(_metric(
        "pre_tax_share", "Pre-tax share at retirement", "percent", "income_allocation", value,
        Bands("lower", PRE_TAX_SHARE_FAIR, PRE_TAX_SHARE_STRONG) if value is not None else None,
        retirement_year))

    # Funded years: the share of projection years before the first shortfall.
    shortfalls = [snap.year for snap in snaps if snap.unfunded_expenses > _UNFUNDED_TOLERANCE]
    if meta.failure_year is not None:
        shortfalls.append(meta.failure_year)
    first_shortfall = min(shortfalls) if shortfalls else None
    funded = (first_shortfall - first.year if first_shortfall is not None else len(snaps)) / len(snaps)
    metrics.append(_metric(
        "funded_years", "Funded years", "percent", "expenses", funded,
        Bands("higher", FUNDED_YEARS_FAIR, FUNDED_YEARS_STRONG),
        first_shortfall if first_shortfall is not None else snaps[-1].year))

    # Financial independence timing: the FI estimate year against retirement.
    fi_year = meta.fi_estimate.year if meta.fi_estimate is not None else None
    applicable = milestone_year is not None and not already_retired
    metrics.append(_metric(
        "fi_timing", "Financial independence", "year", "milestones",
        float(fi_year) if fi_year is not None and applicable else None,
        Bands("lower", float(milestone_year + FI_TIMING_GRACE_YEARS), float(milestone_year)) if applicable else None,
        (fi_year if fi_year is not None else milestone_year) if applicable else None))

    return WellnessResult(start_year=meta.start_year, metrics=metrics)
