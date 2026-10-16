/**
 * Partially discretionary expenses. `discretionary_percent` (0-100) is the
 * share flexible spending may cut; when null the category keeps its
 * all-or-nothing meaning (essential 0%, discretionary 100%). The server
 * mirrors a percent into `category` with the same rule as categoryForPercent.
 */

/** A percent at or above this is reported as "discretionary" to category-only readers. */
export const DISCRETIONARY_CATEGORY_THRESHOLD = 50;

export type ShareMode = "essential" | "discretionary" | "custom";

export function categoryForPercent(percent: number): "essential" | "discretionary" {
  return percent >= DISCRETIONARY_CATEGORY_THRESHOLD ? "discretionary" : "essential";
}

/** Percent for display, with at most two decimals and no trailing zeros. */
export function formatPercent(percent: number): string {
  return `${Number(percent.toFixed(2))}%`;
}

/** "40% flexible" for a partial split; null for 0, 100 or no percent. */
export function flexibleLabel(percent: number | null | undefined): string | null {
  return percent != null && percent > 0 && percent < 100
    ? `${formatPercent(percent)} flexible`
    : null;
}

/** The editor mode that shows a saved expense: a preset when it is all-or-nothing. */
export function openingShareMode(
  percent: number | null | undefined,
  category: string | null | undefined,
): ShareMode {
  if (percent == null) return category === "discretionary" ? "discretionary" : "essential";
  if (percent === 0) return "essential";
  if (percent === 100) return "discretionary";
  return "custom";
}

/** Parse a custom percent entry; null when it is not a number from 0 to 100. */
export function parsePercent(value: string): number | null {
  if (value.trim() === "") return null;
  const percent = Number(value);
  return Number.isFinite(percent) && percent >= 0 && percent <= 100 ? percent : null;
}
