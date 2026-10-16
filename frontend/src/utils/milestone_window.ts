import type { Milestone, MilestoneOutcome } from "@/types/plan";

/**
 * Calendar year a milestone fires when that is knowable before simulating.
 * Age and date triggers resolve directly; relative triggers resolve through
 * their base. Net-worth and expense-multiple triggers return null, as do
 * switched-off milestones.
 */
export function resolveMilestoneYear(
  milestone: Milestone | undefined,
  all: Milestone[],
  birthYear: number | null | undefined,
  seen: Set<string> = new Set(),
): number | null {
  // A switched-off milestone never fires.
  if (!milestone || milestone.is_active === false || seen.has(milestone.id)) return null;
  seen.add(milestone.id);
  switch (milestone.trigger_type) {
    case "age":
      return milestone.trigger_value != null && birthYear != null
        ? birthYear + Math.ceil(milestone.trigger_value)
        : null;
    case "date":
      return milestone.trigger_date ? Number(milestone.trigger_date.slice(0, 4)) : null;
    case "relative": {
      const base = resolveMilestoneYear(
        all.find((m) => m.id === milestone.relative_to_id),
        all,
        birthYear,
        seen,
      );
      return base == null ? null : base + (milestone.offset_years ?? 0);
    }
    default:
      return null;
  }
}

/**
 * Human-readable error when an event's start milestone resolves after its end
 * milestone; null when the order is fine or cannot be known yet.
 */
export function milestoneWindowError(
  startId: string | null | undefined,
  endId: string | null | undefined,
  all: Milestone[],
  birthYear: number | null | undefined,
  startMonth?: number | null,
  endMonth?: number | null,
): string | null {
  if (!startId || !endId) return null;
  const start = all.find((m) => m.id === startId);
  const end = all.find((m) => m.id === endId);
  const startYear = resolveMilestoneYear(start, all, birthYear);
  const endYear = resolveMilestoneYear(end, all, birthYear);
  if (
    (startId === endId || (startYear != null && startYear === endYear)) &&
    startMonth != null &&
    endMonth != null &&
    startMonth > endMonth
  ) {
    return "Start month must not be after end month when both milestones occur in the same year.";
  }
  if (startYear == null || endYear == null || startYear <= endYear) return null;
  return `Start milestone "${start?.name}" (${startYear}) comes after end milestone "${end?.name}" (${endYear}). Swap them or choose a later end.`;
}

const PROJECTED = new Set(["net_worth", "expense_multiple"]);

/**
 * Advisory text for a window bounded by a projection-dependent milestone
 * (net worth, expense multiple). The order cannot be checked up front, so the
 * latest projection's outcome is used instead: the window is dead when its
 * start fired after its end or never fired while the end did. Null when both
 * bounds are fixed, or when nothing is wrong.
 */
export function milestoneWindowWarning(
  startId: string | null | undefined,
  endId: string | null | undefined,
  all: Milestone[],
  outcomes: MilestoneOutcome[] | null | undefined,
): string | null {
  if (!startId || !endId || startId === endId) return null;
  const start = all.find((m) => m.id === startId);
  const end = all.find((m) => m.id === endId);
  if (!start || !end) return null;
  if (!PROJECTED.has(start.trigger_type) && !PROJECTED.has(end.trigger_type)) return null;
  const dynamic = [start, end]
    .filter((m) => PROJECTED.has(m.trigger_type))
    .map((m) => `"${m.name}"`)
    .join(" and ");
  const lead = `${dynamic} ${dynamic.includes(" and ") ? "fire" : "fires"} only when the projection says so, so this window cannot be checked until the plan runs.`;
  const fired = new Map((outcomes ?? []).map((o) => [o.id, o.year]));
  if (!outcomes || !fired.has(startId) || !fired.has(endId)) return lead;
  const startYear = fired.get(startId) ?? null;
  const endYear = fired.get(endId) ?? null;
  if (endYear == null)
    return `${lead} In the latest projection the end never fires, so it runs from "${start.name}"${startYear == null ? ", which never fires either" : ` (${startYear})`} onward.`;
  if (startYear == null)
    return `${lead} In the latest projection "${end.name}" fires in ${endYear} but "${start.name}" never does, so this never runs.`;
  if (startYear > endYear)
    return `${lead} In the latest projection "${start.name}" fires in ${startYear}, after "${end.name}" in ${endYear}, so this never runs. Swap them or choose a later end.`;
  return `${lead} In the latest projection it runs from ${startYear} to ${endYear}.`;
}
