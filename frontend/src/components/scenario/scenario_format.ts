import type { Account, PlanData } from "@/types/plan";
import type {
  PlanInheritance,
  ScenarioFieldChange,
  ScenarioItem,
  ScenarioItemKind,
} from "@/types/scenario";
import { calendarDate, fullCurrency, pct } from "@/utils/format";
import { MONTH_NAMES } from "@/domain/months";

/** Plan-builder section each kind of change belongs to, in the builder's order. */
export const SECTION_ORDER = [
  "Plan details",
  "Assumptions",
  "Milestones",
  "Income streams",
  "Expenses",
  "Accounts",
  "Income allocation",
  "Property and debt",
  "Drawdown order",
  "Charitable giving",
  "Partner and estate",
] as const;
export type ScenarioSection = (typeof SECTION_ORDER)[number];

const SECTION_OF: Record<ScenarioItemKind, ScenarioSection> = {
  spouse: "Partner and estate",
  milestone: "Milestones",
  income: "Income streams",
  expense: "Expenses",
  account: "Accounts",
  real_asset: "Property and debt",
  liability: "Property and debt",
  assumption_curve: "Assumptions",
  charity: "Charitable giving",
  priorities: "Income allocation",
  drawdown: "Drawdown order",
  residency: "Plan details",
};

export const WHOLE_LIST_KINDS = new Set<ScenarioItemKind>(["priorities", "drawdown", "residency"]);

/** The button that replaces a whole list with Main's. */
export const WHOLE_LIST_ACTION: Record<string, string> = {
  priorities: "Use Main’s rules",
  drawdown: "Use Main’s order",
  residency: "Use Main’s residency",
};

export interface ScenarioSectionGroup {
  section: ScenarioSection;
  /** Plan-level fields, only in "Plan details". */
  planFields: ScenarioFieldChange[];
  items: ScenarioItem[];
}

/** Every difference from Main, grouped by plan-builder section. Inherited items are left out. */
export function groupChanges(data: PlanInheritance): ScenarioSectionGroup[] {
  const groups = new Map<ScenarioSection, ScenarioSectionGroup>();
  const group = (section: ScenarioSection) => {
    if (!groups.has(section)) groups.set(section, { section, planFields: [], items: [] });
    return groups.get(section)!;
  };
  if (data.plan_fields.length) group("Plan details").planFields.push(...data.plan_fields);
  for (const item of data.items) {
    if (item.state !== "inherited") group(SECTION_OF[item.kind] ?? "Plan details").items.push(item);
  }
  return SECTION_ORDER.flatMap((section) => (groups.has(section) ? [groups.get(section)!] : []));
}

/** Plan-builder labels for fields whose column name doesn't read well on its own. */
const FIELD_LABELS: Record<string, string> = {
  annual_amount: "Annual amount",
  annual_appreciation_rate: "Annual value change",
  balance: "Balance",
  birth_year: "Birth year",
  birth_month: "Birth month",
  claiming_age: "Claiming age",
  cost_basis: "Cost basis",
  current_value: "Current value",
  end_milestone_id: "Ends at",
  filing_status: "Filing status",
  fixed_rate: "Rate",
  growth_rate: "Growth rate",
  interest_rate: "Interest rate",
  is_active: "Included in the plan",
  life_expectancy: "Life expectancy",
  principal_balance: "Balance",
  start_milestone_id: "Starts at",
  state_code: "State",
  trigger_value: "Trigger value",
  withholding_percent: "Withholding",
};

/** Plan settings named as Plan details names them. */
const PLAN_FIELD_LABELS: Record<string, string> = { life_expectancy: "Longevity age" };

export function fieldLabel(field: string, kind?: string): string {
  if (kind === "plan" && PLAN_FIELD_LABELS[field]) return PLAN_FIELD_LABELS[field];
  if (FIELD_LABELS[field]) return FIELD_LABELS[field];
  const words = field.replace(/_id$/, "").replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : field;
}

// Rates saved as fractions (0.03 is 3%) versus those saved in percent (3 is 3%).
const FRACTION_RATES = new Set([
  "annual_appreciation_rate",
  "fixed_rate",
  "stock_growth_rate",
  "bond_growth_rate",
  "dividend_yield",
  "expense_ratio",
]);
const PERCENT_RATES = new Set([
  "growth_rate",
  "interest_rate",
  "withholding_percent",
  "recurrence_growth_rate",
  "discretionary_percent",
]);
const MONEY =
  /(amount|balance|current_value|purchase_price|payment|cost_basis|basis|reserve|contribution|legacy_target|_cost$|_limit$|max_annual|target_balance|growth_cap$)/;

export interface FormatContext {
  plan: PlanData;
  accounts: Account[];
}

function nameOf(
  id: string,
  items: { id: string; name: string }[] | undefined,
  fallback: string,
): string {
  return items?.find((item) => item.id === id)?.name ?? fallback;
}

/**
 * A changed value as the planner shows it: money, percent in the field's own unit,
 * dates, and names for linked items resolved from the open plan. Anything else
 * falls back to a readable raw value.
 */
export function formatScenarioValue(field: string, value: unknown, ctx: FormatContext): string {
  if (value === null || value === undefined || value === "") return "None";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") {
    if (/milestone_id$/.test(field))
      return nameOf(value, ctx.plan.milestones, "A milestone not in this plan");
    if (/account_id$/.test(field)) return nameOf(value, ctx.accounts, "An account");
    if (/income_id$/.test(field)) return nameOf(value, ctx.plan.income_streams, "An income stream");
    if (/expense_id$/.test(field)) return nameOf(value, ctx.plan.expenses, "An expense");
    if (/asset_id$/.test(field)) return nameOf(value, ctx.plan.real_assets, "A property");
    if (/liability_id$/.test(field)) return nameOf(value, ctx.plan.liabilities, "A debt");
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return calendarDate(value);
    if (/^[a-z][a-z_]*$/.test(value)) return value.replace(/_/g, " ");
    return value;
  }
  if (typeof value === "number") {
    if (FRACTION_RATES.has(field)) return pct(value);
    if (PERCENT_RATES.has(field) || /_percent$/.test(field)) return `${Number(value.toFixed(2))}%`;
    if (/_month$/.test(field) && Number.isInteger(value) && value >= 1 && value <= 12)
      return MONTH_NAMES[value - 1];
    if (
      /(_year|_age|_years)$/.test(field) ||
      field === "life_expectancy" ||
      field === "trigger_value"
    )
      return String(value);
    if (MONEY.test(field)) return fullCurrency(value);
    return value.toLocaleString("en-US");
  }
  const text = JSON.stringify(value);
  return text.length > 120 ? `${text.slice(0, 117)}…` : text;
}
