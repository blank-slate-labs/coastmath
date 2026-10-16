import type { AmountFrequency, IncomeAmountFrequency } from "@/types/plan";

export type { AmountFrequency };

/**
 * Units an income or expense amount can be entered in. Display only: the wire
 * and the engine use `annual_amount`, and the saved `amount_frequency` just
 * reopens the editor in the unit the user last chose. Shortest period first.
 */
export const AMOUNT_FREQUENCIES: readonly AmountFrequency[] = [
  "weekly",
  "biweekly",
  "semimonthly",
  "monthly",
  "quarterly",
  "annual",
];

export const PERIODS_PER_YEAR: Readonly<Record<AmountFrequency, number>> = {
  annual: 1,
  quarterly: 4,
  monthly: 12,
  semimonthly: 24,
  biweekly: 26,
  weekly: 52,
};

/** The server's cap on a yearly amount or a balance: past $1 trillion is a typo. */
export const MAX_ANNUAL_AMOUNT = 1e12;

/** The yearly cap in the unit an amount is typed in, so the field states it in that unit. */
export function maxEntry(frequency: AmountFrequency): number {
  return Math.floor(MAX_ANNUAL_AMOUNT / PERIODS_PER_YEAR[frequency]);
}

/** Unit select options. */
export const FREQUENCY_LABELS: Readonly<Record<AmountFrequency, string>> = {
  weekly: "Weekly",
  biweekly: "Biweekly (every 2 weeks)",
  semimonthly: "Semimonthly (twice a month)",
  monthly: "Monthly",
  quarterly: "Quarterly",
  annual: "Annual",
};

/** Amount input labels. */
export const AMOUNT_LABELS: Readonly<Record<AmountFrequency, string>> = {
  weekly: "Weekly amount ($)",
  biweekly: "Biweekly amount ($)",
  semimonthly: "Semimonthly amount ($)",
  monthly: "Monthly amount ($)",
  quarterly: "Quarterly amount ($)",
  annual: "Annual amount ($)",
};

/** Suffixes for a sentence such as "$2,500/month". */
export const PERIOD_SUFFIXES: Readonly<Record<AmountFrequency, string>> = {
  weekly: "/week",
  biweekly: " every 2 weeks",
  semimonthly: " twice a month",
  monthly: "/month",
  quarterly: "/quarter",
  annual: "/year",
};

/** Suffixes for compact list rows such as "$2.5K/mo". */
export const SHORT_PERIOD_SUFFIXES: Readonly<Record<AmountFrequency, string>> = {
  weekly: "/wk",
  biweekly: "/2 wks",
  semimonthly: " 2×/mo",
  monthly: "/mo",
  quarterly: "/qtr",
  annual: "/yr",
};

/** Rounds half away from zero, as PostgreSQL rounds `Numeric(15, 2)`. */
function roundCents(value: number): number {
  return (Math.sign(value) * Math.round(Math.abs(value) * 100)) / 100;
}

/** An annual amount per period: exact when annual, otherwise rounded to cents. */
export function fromAnnual(annual: number, frequency: AmountFrequency): number {
  return frequency === "annual" ? annual : roundCents(annual / PERIODS_PER_YEAR[frequency]);
}

/**
 * The annual wire amount for a per-period value. Annual values pass through
 * unchanged; other units round to the cents the database stores, which drops
 * float noise such as 1000.01 × 12 = 12000.119999999999.
 */
export function toAnnual(value: number, frequency: AmountFrequency): number {
  return frequency === "annual" ? value : roundCents(value * PERIODS_PER_YEAR[frequency]);
}

/**
 * What the user typed and the unit it was typed in. Editors keep this rather
 * than a converted number, so switching the displayed unit never rounds or
 * drifts the annual amount unless the value itself is edited.
 */
export interface AmountEntry {
  value: string;
  frequency: AmountFrequency;
}

/** A saved amount enters as its exact annual value; a new one in `frequency`. */
export function initialEntry(
  annual: number | null | undefined,
  frequency: AmountFrequency,
): AmountEntry {
  return annual == null
    ? { value: "0", frequency }
    : { value: String(annual), frequency: "annual" };
}

export function entryAnnual(entry: AmountEntry): number {
  return toAnnual(Number(entry.value), entry.frequency);
}

/** The entry shown in `frequency`: verbatim in its own unit, otherwise converted. */
export function entryDisplay(entry: AmountEntry, frequency: AmountFrequency): string {
  if (entry.value.trim() === "" || entry.frequency === frequency) return entry.value;
  return String(fromAnnual(entryAnnual(entry), frequency));
}

/** The unit an editor opens in; records saved before units existed use the editor's legacy default. */
export function openingFrequency(
  saved: AmountFrequency | null | undefined,
  legacy: AmountFrequency,
): AmountFrequency {
  return saved ?? legacy;
}

/** A list-row amount in its saved unit, e.g. "$2.5K/mo"; legacy records read per year. */
export function formatPerPeriod(
  annual: number,
  frequency: AmountFrequency | null | undefined,
  format: (value: number) => string,
  suffixes: Readonly<Record<AmountFrequency, string>> = SHORT_PERIOD_SUFFIXES,
): string {
  const unit = frequency ?? "annual";
  return `${format(fromAnnual(Number(annual), unit))}${suffixes[unit]}`;
}

/** Paid weeks a year for hourly pay; the server uses the same factor. */
export const HOURLY_WEEKS_PER_YEAR = 52;

/** Annual pay for an hourly rate and weekly hours, to the cent. */
export function hourlyAnnual(rate: number, hoursPerWeek: number): number {
  return roundCents(rate * hoursPerWeek * HOURLY_WEEKS_PER_YEAR);
}

/** An income list row: hourly pay reads "$25.50/hr × 40 hrs/wk", other units as `formatPerPeriod`. */
export function formatIncomePerPeriod(
  income: {
    annual_amount: number;
    amount_frequency?: IncomeAmountFrequency | null;
    hourly_rate?: number | null;
    hours_per_week?: number | null;
  },
  format: (value: number) => string,
): string {
  if (income.amount_frequency === "hourly") {
    if (income.hourly_rate != null && income.hours_per_week != null) {
      return `${format(Number(income.hourly_rate))}/hr × ${Number(income.hours_per_week)} hrs/wk`;
    }
    return formatPerPeriod(income.annual_amount, "annual", format);
  }
  return formatPerPeriod(income.annual_amount, income.amount_frequency, format);
}
