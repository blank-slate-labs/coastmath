"""Bounded multi-year tax strategy comparison.

Each candidate strategy is a bracket-fill Roth conversion rule (or the
"no new conversions" baseline) evaluated by running the full projection.
Results are compared on explicit objectives; because the candidate set is
a small, user-bounded grid, the best candidate is the best *of those
evaluated*, not a global optimum.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from coastmath.engine.simulator import run_simulation
from coastmath.engine.tax_engine import get_ltcg_brackets
from coastmath.engine.tax_target import plan_bracket_rates
from coastmath.engine.types import PlanData, PriorityData
from coastmath.schemas.simulation import SimulationResult

OBJECTIVES = {
    "net_legacy": "Net estate after estate tax and income tax on pre-tax balances (higher is better)",
    "final_net_worth": "Net worth at the end of the plan after income tax on pre-tax balances (higher is better)",
    "lifetime_taxes": "Lifetime income taxes and penalties (lower is better)",
    "lifetime_taxes_and_healthcare": "Lifetime taxes plus health coverage costs (lower is better)",
    "lifetime_effective_tax_rate": "Lifetime effective tax rate: taxes divided by income, weighted by each year's income (lower is better)",
    "total_aca_subsidies": "Total ACA premium tax credits received (higher is better)",
    "total_rmd_distributions": "Total required minimum distributions taken (lower is better)",
    "total_irmaa_surcharge": "Total Medicare IRMAA surcharges, Part B and Part D (lower is better)",
}
_HIGHER_IS_BETTER = {"net_legacy", "final_net_worth", "total_aca_subsidies"}


def objective_direction(objective: str) -> str:
    """``"higher"`` or ``"lower"``: which end of the objective is better."""
    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective {objective!r}")
    return "higher" if objective in _HIGHER_IS_BETTER else "lower"
#: Income tax rate on end-of-plan pre-tax balances when the plan sets no heir rate.
DEFAULT_PRE_TAX_DISCOUNT_RATE = 0.24


def pre_tax_discount_rate(plan_data: PlanData) -> float:
    """The plan's heir income tax rate when set above zero, otherwise 24%."""
    rate = plan_data.estate_settings.heir_income_tax_rate if plan_data.estate_settings else 0.0
    return min(1.0, float(rate)) if rate and rate > 0 else DEFAULT_PRE_TAX_DISCOUNT_RATE


def pre_tax_discount(result: SimulationResult, rate: float) -> float:
    """Income tax at ``rate`` on the end-of-plan pre-tax balances, for ranking only.

    Pre-tax balances are those the estate projection treats as income to
    heirs (traditional IRAs and 401(k)s, HSAs). Rankings by net legacy or end
    net worth subtract this so a dollar converted to Roth is not worth less
    than a pre-tax dollar. It ignores the IRC 691(c) estate tax deduction, and
    the reported net worth and net legacy figures stay unreduced.
    """
    legacy = result.metadata.net_legacy
    return rate * (legacy.pretax_balance if legacy is not None else 0.0)


@dataclass
class StrategyCandidate:
    key: str
    label: str
    priority: PriorityData | None  # None = baseline (existing plan only)


@dataclass
class StrategyMetrics:
    key: str
    label: str
    success: bool
    failure_year: int | None
    lifetime_taxes: float
    lifetime_healthcare: float
    final_net_worth: float
    net_legacy: float
    total_converted: float
    conversion_years: int
    irmaa_years: int
    aca_credit_lost_years: int
    peak_marginal_rate: float
    objective_value: float
    delta_vs_baseline: float = 0.0
    is_best: bool = False
    notes: list[str] = field(default_factory=list)
    # Additive objective measures, always computed so any objective can be
    # shown or ranked without another simulation.
    lifetime_effective_tax_rate: float = 0.0
    total_aca_subsidies: float = 0.0
    total_rmd_distributions: float = 0.0
    total_irmaa_surcharge: float = 0.0


@dataclass(frozen=True)
class OutcomeMeasures:
    """Every objective measure of one finished simulation, in dollars.

    All figures sum the year-by-year snapshots, so each objective is an actual
    amount rather than a count of affected years.
    """
    lifetime_taxes: float
    lifetime_healthcare: float
    final_net_worth: float
    net_legacy: float
    pre_tax_discount: float
    lifetime_income: float
    lifetime_effective_tax_rate: float
    total_aca_subsidies: float
    total_rmd_distributions: float
    total_irmaa_surcharge: float

    def objective_values(self) -> dict[str, float]:
        return {
            "net_legacy": self.net_legacy - self.pre_tax_discount,
            "final_net_worth": self.final_net_worth - self.pre_tax_discount,
            "lifetime_taxes": self.lifetime_taxes,
            "lifetime_taxes_and_healthcare": self.lifetime_taxes + self.lifetime_healthcare,
            "lifetime_effective_tax_rate": self.lifetime_effective_tax_rate,
            "total_aca_subsidies": self.total_aca_subsidies,
            "total_rmd_distributions": self.total_rmd_distributions,
            "total_irmaa_surcharge": self.total_irmaa_surcharge,
        }


def _year_income(snap) -> float:
    """The income the year's effective rate is measured against.

    The engine's own denominator (calendar-year gross income plus taxable Roth
    conversions) is recovered from its reported taxes and effective rate, so
    the lifetime rate weights each year's rate by the income it applied to.
    A year without a usable rate falls back to its gross income.
    """
    if snap.effective_rate and snap.taxes and snap.taxes / snap.effective_rate > 0:
        return snap.taxes / snap.effective_rate
    gross = snap.calendar_year_gross_income if snap.calendar_year_gross_income is not None else snap.gross_income
    return max(0.0, gross)


def _year_rmd(snap) -> float:
    if snap.cash_flow is None:
        return 0.0
    return sum(item.amount for item in snap.cash_flow.income_sources if item.source == "rmd")


def measure_result(result: SimulationResult, discount_rate: float) -> OutcomeMeasures:
    """Objective measures of ``result``; pre-tax balances taxed at ``discount_rate`` for ranking."""
    snaps = result.yearly_snapshots
    lifetime_taxes = sum(s.taxes for s in snaps)
    final_net_worth = snaps[-1].net_worth if snaps else 0.0
    legacy = result.metadata.net_legacy
    income = sum(_year_income(s) for s in snaps)
    healthcare = [s.healthcare for s in snaps if s.healthcare is not None]
    return OutcomeMeasures(
        lifetime_taxes=lifetime_taxes,
        lifetime_healthcare=sum(h.total for h in healthcare),
        final_net_worth=final_net_worth,
        net_legacy=float(legacy.net_legacy) if legacy else final_net_worth,
        pre_tax_discount=pre_tax_discount(result, discount_rate),
        lifetime_income=income,
        # No income leaves no tax burden to weight: the rate is defined as 0.
        lifetime_effective_tax_rate=lifetime_taxes / income if income > 0 else 0.0,
        total_aca_subsidies=sum(h.aca_credit for h in healthcare),
        total_rmd_distributions=sum(_year_rmd(s) for s in snaps),
        total_irmaa_surcharge=sum(h.medicare_irmaa_part_b + h.medicare_irmaa_part_d for h in healthcare),
    )


@dataclass
class StrategyComparison:
    objective: str
    objective_description: str
    baseline_key: str
    best_key: str | None
    candidates: list[StrategyMetrics]
    caveats: list[str]
    pre_tax_discount_rate: float = DEFAULT_PRE_TAX_DISCOUNT_RATE


def _bracket_rates(plan_data: PlanData, strategy_type: str) -> list[float]:
    """Capital-gains rates for harvests; the plan's own federal bracket rates
    (custom or scheduled brackets included) for conversions."""
    if strategy_type == "gain_harvest":
        return [rate for _, rate in get_ltcg_brackets(plan_data.filing_status)]
    return plan_bracket_rates(plan_data.tax_settings, plan_data.filing_status)


def build_candidates(
    plan_data: PlanData,
    *,
    source_account_id: str,
    target_account_id: str | None,
    bracket_ceilings: list[float],
    magi_cap: float | None,
    start_milestone_id: str | None,
    end_milestone_id: str | None,
    strategy_type: str = "roth_conversion",
) -> list[StrategyCandidate]:
    """Baseline plus one bracket-fill rule per requested ceiling.

    ``roth_conversion`` fills ordinary-income brackets by converting pre-tax
    balances; ``gain_harvest`` fills long-term capital-gains brackets by
    realising and re-buying appreciated taxable holdings.
    """
    harvest = strategy_type == "gain_harvest"
    candidates = [StrategyCandidate(key="baseline", label="No new harvesting" if harvest else "No new conversions", priority=None)]
    available = _bracket_rates(plan_data, strategy_type)
    next_rank = max((p.priority_rank for p in plan_data.priorities), default=0) + 1
    for rate in bracket_ceilings:
        if not any(abs(rate - r) < 1e-9 for r in available):
            continue
        label = (f"Harvest gains to fill the {round(rate * 100)}% capital-gains bracket" if harvest
                 else f"Convert to fill the {round(rate * 100)}% bracket")
        if magi_cap is not None:
            label += f", MAGI capped at ${magi_cap:,.0f}"
        candidates.append(StrategyCandidate(
            key=f"fill_{round(rate * 10000)}",
            label=label,
            priority=PriorityData(
                priority_rank=next_rank,
                priority_type="gain_harvest" if harvest else "roth_conversion",
                source_account_id=source_account_id,
                target_account_id=None if harvest else target_account_id,
                conversion_mode="fill_bracket",
                bracket_ceiling_rate=rate,
                magi_cap=magi_cap,
                start_milestone_id=start_milestone_id,
                end_milestone_id=end_milestone_id,
            ),
        ))
    return candidates


def _route_amounts(snaps, priority: PriorityData) -> list[float]:
    """Per-year amount the rule's route moved: realised gains for a harvest,
    source-to-target transfers for a conversion. Other plan rules on the same
    route are included, so callers subtract the baseline's figures."""
    if priority.priority_type == "gain_harvest":
        return [s.harvested_gains for s in snaps]
    return [
        sum(t.amount for t in s.transfers
            if t.source_account_id == priority.source_account_id
            and t.target_account_id == priority.target_account_id)
        for s in snaps
    ]


def _evaluate(plan_data: PlanData, candidate: StrategyCandidate, objective: str, rate: float,
              baseline_result=None) -> StrategyMetrics:
    priorities = list(plan_data.priorities)
    if candidate.priority is not None:
        priorities.append(candidate.priority)
    scenario = replace(plan_data, priorities=priorities)
    result = run_simulation(scenario) if candidate.priority is not None or baseline_result is None else baseline_result
    snaps = result.yearly_snapshots
    lifetime_taxes = sum(s.taxes for s in snaps)
    lifetime_healthcare = sum((s.healthcare.total if s.healthcare else 0.0) for s in snaps)
    converted = 0.0
    conversion_years = 0
    if candidate.priority is not None:
        # Only what the candidate adds: the plan's own rules on the same route
        # (an existing conversion or harvest rule) already move money in the
        # baseline and must not be credited to the candidate.
        baseline = baseline_result if baseline_result is not None else run_simulation(plan_data)
        moved = _route_amounts(snaps, candidate.priority)
        before = {s.year: amount for s, amount in zip(baseline.yearly_snapshots, _route_amounts(baseline.yearly_snapshots, candidate.priority), strict=True)}
        added = [amount - before.get(s.year, 0.0) for s, amount in zip(snaps, moved, strict=True)]
        # Net of any later years in which the plan's own rule moves less;
        # sub-cent float noise from re-ordered rules is not a move.
        net = sum(added)
        converted = net if net > 0.005 else 0.0
        conversion_years = sum(1 for a in added if a > 0.005) if converted > 0 else 0
    irmaa_years = sum(1 for s in snaps if s.healthcare and s.healthcare.medicare_tier > 0)
    aca_lost = sum(1 for s in snaps if s.healthcare and s.healthcare.aca_covered_adults > 0 and not s.healthcare.aca_eligible)
    measures = measure_result(result, rate)
    values = measures.objective_values()
    notes: list[str] = []
    if candidate.priority is not None and converted <= 0:
        notes.append("No headroom or unrealised gain was available in the window, so this rule did nothing.")
    if not result.metadata.success:
        notes.append(f"Plan fails in {result.metadata.failure_year} under this strategy.")
    return StrategyMetrics(
        key=candidate.key, label=candidate.label,
        success=result.metadata.success, failure_year=result.metadata.failure_year,
        lifetime_taxes=lifetime_taxes, lifetime_healthcare=lifetime_healthcare,
        final_net_worth=measures.final_net_worth, net_legacy=measures.net_legacy,
        total_converted=converted, conversion_years=conversion_years,
        irmaa_years=irmaa_years, aca_credit_lost_years=aca_lost,
        peak_marginal_rate=max((s.marginal_rate for s in snaps), default=0.0),
        objective_value=values[objective], notes=notes,
        lifetime_effective_tax_rate=measures.lifetime_effective_tax_rate,
        total_aca_subsidies=measures.total_aca_subsidies,
        total_rmd_distributions=measures.total_rmd_distributions,
        total_irmaa_surcharge=measures.total_irmaa_surcharge,
    )


def compare_strategies(
    plan_data: PlanData,
    candidates: list[StrategyCandidate],
    objective: str,
) -> StrategyComparison:
    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective {objective!r}")
    rate = pre_tax_discount_rate(plan_data)
    baseline_result = run_simulation(replace(plan_data, priorities=list(plan_data.priorities)))
    metrics = [_evaluate(plan_data, c, objective, rate, baseline_result) for c in candidates]
    baseline = next(m for m in metrics if m.key == "baseline")
    for m in metrics:
        m.delta_vs_baseline = m.objective_value - baseline.objective_value
    feasible = [m for m in metrics if m.success] or metrics
    best = (max if objective in _HIGHER_IS_BETTER else min)(feasible, key=lambda m: m.objective_value)
    best.is_best = True
    caveats = [
        "Only the listed candidates were simulated; the best result is the best of these, not a global optimum.",
        "Bracket headroom is measured before the year's withdrawals; withdrawals taken later in the year can push income above the target bracket.",
        "Harvested gains are re-invested immediately (no cash moves); all gains are treated as long-term and basis uses the average-cost method.",
        "Health coverage effects (ACA credits, IRMAA) are included only when health coverage is modeled for this plan.",
        "Net estate and end net worth rankings tax pre-tax balances at one flat rate without the estate tax deduction (IRC 691(c)); the Net estate column is not reduced.",
    ]
    return StrategyComparison(
        objective=objective, objective_description=OBJECTIVES[objective],
        baseline_key="baseline", best_key=best.key, candidates=metrics, caveats=caveats,
        pre_tax_discount_rate=rate,
    )
