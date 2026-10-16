import type { AssumptionCurve, YearSnapshot } from "@/types/plan";
import { catmullRomInterpolate } from "@/utils/spline";
import type { ControlPoint as SplinePoint } from "@/utils/spline";

export type CurrencyMode = "nominal" | "inflation_adjusted";

/**
 * Convert a nominal (future) value to today's dollars.
 */
export function deflate(nominal: number, inflationRate: number, years: number): number {
  return nominal / Math.pow(1 + inflationRate, years);
}

/**
 * Build an array of cumulative deflator factors that match the engine's
 * `inflation_factor` compounding: factor[0] = 1 (year 0 is present value),
 * factor[i] = factor[i-1] * (1 + rate[i-1]).
 *
 * In curve mode the per-year rate is interpolated from the assumption curve's
 * control points via shape-preserving PCHIP at the person's age for that year.
 * In fixed mode (or when the curve is undefined) the flat fixed_rate is used,
 * falling back to `fallbackRate`.
 */
export function buildDeflators(
  curve: AssumptionCurve | undefined,
  fallbackRate: number,
  startYear: number,
  years: number,
  birthYear: number,
): number[] {
  const deflators: number[] = [1];

  // Pre-compute spline control points (plan {x,y} -> spline {age,value})
  let splinePoints: SplinePoint[] | null = null;
  if (curve?.mode === "curve" && curve.control_points.length > 0) {
    splinePoints = curve.control_points.map((cp) => ({
      age: cp.x,
      value: cp.y,
    }));
  }

  for (let i = 1; i <= years; i++) {
    let rate: number;
    if (splinePoints) {
      const age = startYear + (i - 1) - birthYear;
      rate = catmullRomInterpolate(splinePoints, age);
    } else {
      rate = curve?.fixed_rate ?? fallbackRate;
    }
    deflators.push(deflators[i - 1] * (1 + rate));
  }

  return deflators;
}

/**
 * Adjust an entire simulation timeline to inflation-adjusted (real) dollars.
 * Returns data as-is when mode is 'nominal'.
 *
 * `deflators` is a pre-built array from `buildDeflators` where deflators[i]
 * is the cumulative inflation factor for year i relative to the start year.
 */
export function adjustTimeline(
  timeline: YearSnapshot[],
  deflators: number[],
  mode: CurrencyMode,
): YearSnapshot[] {
  if (mode === "nominal") return timeline;
  if (!Array.isArray(timeline)) return [];
  return timeline.map((snap, i) => {
    const factor = deflators[i] ?? 1;
    return {
      ...snap,
      gross_income: snap.gross_income / factor,
      calendar_year_gross_income:
        snap.calendar_year_gross_income == null
          ? snap.calendar_year_gross_income
          : snap.calendar_year_gross_income / factor,
      taxes: snap.taxes / factor,
      post_start_taxes:
        snap.post_start_taxes == null ? snap.post_start_taxes : snap.post_start_taxes / factor,
      expenses: snap.expenses / factor,
      net_cash_flow: snap.net_cash_flow / factor,
      net_worth: snap.net_worth / factor,
      real_assets_value: snap.real_assets_value / factor,
      liabilities_balance: snap.liabilities_balance / factor,
      investment_growth: snap.investment_growth / factor,
      investment_fees:
        snap.investment_fees == null ? snap.investment_fees : snap.investment_fees / factor,
      unfunded_expenses:
        snap.unfunded_expenses == null ? snap.unfunded_expenses : snap.unfunded_expenses / factor,
      tax_balance: snap.tax_balance == null ? snap.tax_balance : snap.tax_balance / factor,
      deduction_amount: snap.deduction_amount / factor,
      accounts: Object.fromEntries(Object.entries(snap.accounts).map(([k, v]) => [k, v / factor])),
    };
  });
}
