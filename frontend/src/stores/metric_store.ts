import { create } from "zustand";

import type { YearSnapshot } from "@/types/plan";

/**
 * Display-only metric definitions. These change how dashboard figures are
 * summarised from the engine's snapshots; they never change the projection,
 * cash accounting or taxes. Stored per plan in the browser.
 *
 * Engine defaults (what every figure means when nothing is changed):
 * - Spending = every ordinary expense the engine paid in the year: essential,
 *   discretionary and uncategorised expenses, loan payments, property costs,
 *   charitable outflows and health coverage. Taxes are not spending.
 * - Effective tax rate = total taxes (federal, state, capital gains, payroll,
 *   NIIT, AMT and early-withdrawal penalties) ÷ calendar-year gross income,
 *   which includes wages, Social Security, RMDs, taxable withdrawals, employer
 *   contributions, realised gains and dividends for the year.
 */
export type TaxRateDenominator = "gross_income" | "total_outflows";

export interface MetricSettings {
  includeEssential: boolean;
  includeDiscretionary: boolean;
  includeUncategorized: boolean;
  includeTaxesInSpending: boolean;
  taxRateDenominator: TaxRateDenominator;
  includePayrollTax: boolean;
}

export const defaultMetricSettings: MetricSettings = {
  includeEssential: true,
  includeDiscretionary: true,
  includeUncategorized: true,
  includeTaxesInSpending: false,
  taxRateDenominator: "gross_income",
  includePayrollTax: true,
};

interface MetricState {
  planId: string | null;
  settings: MetricSettings;
  load: (planId: string) => void;
  update: (patch: Partial<MetricSettings>) => void;
  reset: () => void;
}

const key = (planId: string) => `coastmath:metrics:${planId}`;

function read(planId: string): MetricSettings {
  try {
    const raw = localStorage.getItem(key(planId));
    if (!raw) return defaultMetricSettings;
    return { ...defaultMetricSettings, ...(JSON.parse(raw) as Partial<MetricSettings>) };
  } catch {
    return defaultMetricSettings;
  }
}

export const useMetricStore = create<MetricState>((set, get) => ({
  planId: null,
  settings: defaultMetricSettings,
  load: (planId) => set({ planId, settings: read(planId) }),
  update: (patch) => {
    const next = { ...get().settings, ...patch };
    const planId = get().planId;
    if (planId) {
      try {
        localStorage.setItem(key(planId), JSON.stringify(next));
      } catch {
        /* storage unavailable */
      }
    }
    set({ settings: next });
  },
  reset: () => {
    const planId = get().planId;
    if (planId) {
      try {
        localStorage.removeItem(key(planId));
      } catch {
        /* storage unavailable */
      }
    }
    set({ settings: defaultMetricSettings });
  },
}));

export function isDefaultMetricSettings(s: MetricSettings): boolean {
  return (Object.keys(defaultMetricSettings) as (keyof MetricSettings)[]).every(
    (k) => s[k] === defaultMetricSettings[k],
  );
}

/** Taxes for display: the engine total, optionally without payroll tax. */
export function taxesForSnapshot(s: YearSnapshot, settings: MetricSettings): number {
  return settings.includePayrollTax ? s.taxes : Math.max(0, s.taxes - (s.fica_tax ?? 0));
}

function taxesForEffectiveRate(s: YearSnapshot, settings: MetricSettings): number {
  const taxes = taxesForSnapshot(s, settings);
  return settings.taxRateDenominator === "total_outflows" && settings.includePayrollTax
    ? (s.post_start_taxes ?? taxes)
    : taxes;
}

/**
 * Spending for display. With default settings this equals the engine's
 * `expenses` figure exactly; category toggles filter the recorded cash-flow
 * expenses (falling back to the engine total when no breakdown exists).
 */
export function spendingForSnapshot(s: YearSnapshot, settings: MetricSettings): number {
  const allCategories =
    settings.includeEssential && settings.includeDiscretionary && settings.includeUncategorized;
  let spending: number;
  if (allCategories || !s.cash_flow) {
    spending = s.expenses;
  } else {
    spending = s.cash_flow.expenses.reduce((sum, e) => {
      // A partially discretionary expense counts each part under its own toggle.
      if (e.discretionary_amount != null) {
        return (
          sum +
          (settings.includeDiscretionary ? e.discretionary_amount : 0) +
          (settings.includeEssential ? e.amount - e.discretionary_amount : 0)
        );
      }
      const include =
        e.category === "essential"
          ? settings.includeEssential
          : e.category === "discretionary"
            ? settings.includeDiscretionary
            : settings.includeUncategorized;
      return include ? sum + e.amount : sum;
    }, 0);
  }
  return settings.includeTaxesInSpending ? spending + taxesForSnapshot(s, settings) : spending;
}

/** Effective tax rate for display; the engine default is taxes ÷ gross income. */
export function effectiveRateForSnapshot(s: YearSnapshot, settings: MetricSettings): number {
  const taxes = taxesForSnapshot(s, settings);
  if (settings.taxRateDenominator === "gross_income") {
    if (settings.includePayrollTax) return s.effective_rate;
    const annualGross = s.calendar_year_gross_income ?? s.gross_income;
    return annualGross > 0 ? taxes / annualGross : 0;
  }
  const periodTaxes = taxesForEffectiveRate(s, settings);
  const outflows = periodTaxes + s.expenses;
  return outflows > 0 ? periodTaxes / outflows : 0;
}

export function lifetimeEffectiveRate(snapshots: YearSnapshot[], settings: MetricSettings): number {
  if (settings.taxRateDenominator === "gross_income") {
    const taxes = snapshots.reduce((sum, s) => sum + taxesForSnapshot(s, settings), 0);
    const income = snapshots.reduce(
      (sum, s) => sum + (s.calendar_year_gross_income ?? s.gross_income),
      0,
    );
    return income > 0 ? taxes / income : 0;
  }
  const taxes = snapshots.reduce((sum, s) => sum + taxesForEffectiveRate(s, settings), 0);
  const outflows = snapshots.reduce(
    (sum, s) => sum + taxesForEffectiveRate(s, settings) + s.expenses,
    0,
  );
  return outflows > 0 ? taxes / outflows : 0;
}
