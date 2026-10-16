import type { CashFlowPriorityCreate, TaxSettings } from "@/types/plan";

/** Built-in federal ordinary-income bracket rates. */
export const BUILT_IN_FEDERAL_RATES = [0.1, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37];

const sameRate = (a: number, b: number) => Math.abs(a - b) < 1e-9;

export function includesRate(rates: number[], rate: number): boolean {
  return rates.some((r) => sameRate(r, rate));
}

/** Bound stored for an open-ended top bracket, as in the built-in tables. */
export const TOP_BRACKET_BOUND = 999_999_999;

type Schedule = Array<[number, number]> | null | undefined;

/**
 * The rates `ratesOf` takes from the plan's own schedule and from every schedule a
 * scheduled change installs, ascending and without repeats. Absent or null
 * `federal_brackets` in a change installs nothing.
 */
function scheduleRates(
  settings: TaxSettings | null | undefined,
  ratesOf: (brackets: Schedule) => number[],
): number[] {
  const all = [...ratesOf(settings?.federal_brackets)];
  for (const change of settings?.scheduled_changes ?? []) {
    const brackets = change.settings?.federal_brackets;
    if (brackets !== undefined && brackets !== null) all.push(...ratesOf(brackets));
  }
  const unique: number[] = [];
  for (const rate of [...all].sort((a, b) => a - b)) {
    if (!includesRate(unique, rate)) unique.push(rate);
  }
  return unique;
}

/**
 * Rates a federal bracket tax target can name in this plan, ascending: the plan's
 * own schedule (custom `federal_brackets`, else the built-in brackets) and every
 * schedule a scheduled change installs (an empty one restores the built-in brackets).
 * The backend checks saved targets and strategy searches against the same set.
 */
export function planBracketRates(settings: TaxSettings | null | undefined): number[] {
  return scheduleRates(settings, (brackets) =>
    brackets && brackets.length > 0 ? brackets.map(([, rate]) => rate) : BUILT_IN_FEDERAL_RATES,
  );
}

/**
 * Rates a picker offers for a new bracket target or bracket fill: the plan's rates
 * of brackets that have a top. The built-in top bracket and a custom one left open
 * have none, so filling them would convert the whole balance. Saved values may
 * still name any rate of `planBracketRates`.
 */
export function fillableBracketRates(settings: TaxSettings | null | undefined): number[] {
  return scheduleRates(settings, (brackets) =>
    brackets && brackets.length > 0
      ? brackets.filter(([upper]) => upper < TOP_BRACKET_BOUND).map(([, rate]) => rate)
      : BUILT_IN_FEDERAL_RATES.slice(0, -1),
  );
}

/** Shown beside a saved rate the plan's brackets no longer include. */
export const STALE_RATE_NOTE = "(not in this plan's brackets)";

/**
 * Whether a Roth conversion rule's own bracket ceiling is missing from the plan's
 * federal brackets. The projection then fills only brackets taxed at or below it and
 * warns. Gain-harvest ceilings are capital-gains rates, which custom brackets don't change.
 */
export function isStaleConversionCeiling(
  rule: CashFlowPriorityCreate,
  settings: TaxSettings | null | undefined,
): boolean {
  return (
    rule.priority_type === "roth_conversion" &&
    rule.conversion_mode === "fill_bracket" &&
    !rule.use_plan_tax_target &&
    rule.bracket_ceiling_rate != null &&
    !includesRate(planBracketRates(settings), rule.bracket_ceiling_rate)
  );
}
