"""Summarize actual milestone observations across independent simulation trials."""

from collections import Counter
from math import ceil

from coastmath.schemas.monte_carlo import MilestoneDistribution
from coastmath.schemas.simulation import SimulationResult


def _observed_percentile(years: list[int], percentile: float) -> int | None:
    # Empirical inverse CDF: return an observed calendar year, never
    # interpolate years or substitute zero for an unreached milestone.
    return years[max(0, ceil(percentile * len(years)) - 1)] if years else None


def milestone_distributions(results: list[SimulationResult]) -> list[MilestoneDistribution]:
    by_id: dict[str, list[int | None]] = {}
    names: dict[str, str] = {}
    for result in results:
        # A milestone counts at most once in a trial, even for legacy callers
        # with duplicated metadata. Never count an absent report as unreached.
        outcomes = {item.id: item for item in result.metadata.milestone_outcomes}
        for mid, item in outcomes.items():
            names.setdefault(mid, item.name)
            by_id.setdefault(mid, []).append(item.year if item.missed_year is None else None)

    summaries = []
    for mid, observations in by_id.items():
        years = sorted(year for year in observations if year is not None)
        missing = len(results) - len(observations)
        summaries.append(MilestoneDistribution(
            id=mid, name=names[mid], reached_trials=len(years),
            unreached_trials=len(observations) - len(years), unreported_trials=missing,
            reach_rate=len(years) / len(results) if results and not missing else None,
            year_counts=dict(sorted(Counter(years).items())),
            p10_year=_observed_percentile(years, .1), median_year=_observed_percentile(years, .5),
            p90_year=_observed_percentile(years, .9),
        ))
    return summaries
