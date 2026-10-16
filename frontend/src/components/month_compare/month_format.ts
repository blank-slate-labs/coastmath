import type { LedgerMonth, MonthSource } from "@/api/ledger";
import type { NetWorthPoint, SpendingOutcome } from "@/api/spending_models";
import type { CurrencyMode } from "@/utils/currency";
import { monthLabel } from "@/components/ledger/ledger_format";

export const MAX_SEPARATE = 6;
export const MAX_COMBINED = 12;
/** Plan first, then one color per variant (at most six). */
export const PLAN_COLOR = "var(--viz-context)";
export const SERIES_COLORS = [
  "var(--viz-1)",
  "var(--viz-2)",
  "var(--viz-3)",
  "var(--viz-4)",
  "var(--viz-5)",
  "var(--viz-7)",
];

function names(ids: string[], sources: MonthSource[]): string {
  const found = ids.map((id) => sources.find((s) => s.id === id)?.name ?? "An account");
  return found.length ? found.join(", ") : "An account";
}

/** Why a month cannot model spending, in one line. */
export function reasonText(month: LedgerMonth, sources: MonthSource[]): string {
  const reason = month.reasons[0];
  switch (reason?.code) {
    case "in_progress":
      return "Month in progress.";
    case "settling":
      return `Still settling: ${names(reason.source_ids, sources)}.`;
    case "partial_coverage":
      return `Not fully covered: ${names(reason.source_ids, sources)}.`;
    case "waiting_for_history":
      return `Waiting for history: ${names(reason.source_ids, sources)}.`;
    default:
      return "Incomplete.";
  }
}

/** Net worth in the chosen currency mode; the engine's inflation factor is 1 in the first year. */
export function shownNetWorth(point: NetWorthPoint, mode: CurrencyMode): number {
  return mode === "nominal" || !point.inflation_factor
    ? point.net_worth
    : point.net_worth / point.inflation_factor;
}

export function finalNetWorth(outcome: SpendingOutcome, mode: CurrencyMode): number {
  const last = outcome.net_worth_path[outcome.net_worth_path.length - 1];
  return last ? shownNetWorth(last, mode) : outcome.final_net_worth;
}

/** FI age against the plan's: "2 yrs earlier", "1 yr later", "Same", or nothing when either is not reached. */
export function fiChange(variant: SpendingOutcome, plan: SpendingOutcome): string | null {
  if (variant.fi_age == null || plan.fi_age == null) return null;
  const years = plan.fi_age - variant.fi_age;
  if (years === 0) return "Same";
  const n = Math.abs(years);
  return `${n} yr${n === 1 ? "" : "s"} ${years > 0 ? "earlier" : "later"}`;
}

export function monthsText(keys: string[]): string {
  return keys.map(monthLabel).join(", ");
}

/** Categories whose mean monthly spending differs most between two outcomes, largest first. */
export function categoryDifferences(
  a: Record<string, number>,
  b: Record<string, number>,
  limit = 6,
) {
  const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
  return keys
    .map((key) => ({
      key,
      a: a[key] ?? 0,
      b: b[key] ?? 0,
      difference: (b[key] ?? 0) - (a[key] ?? 0),
    }))
    .filter((row) => Math.abs(row.difference) >= 0.5)
    .sort((x, y) => Math.abs(y.difference) - Math.abs(x.difference) || x.key.localeCompare(y.key))
    .slice(0, limit);
}

export const srOnly: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
};
