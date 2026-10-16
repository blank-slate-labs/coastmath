import { describe, it, expect } from "vitest";
import { adjustTimeline, buildDeflators, deflate } from "./currency";
import type { AssumptionCurve, YearSnapshot } from "@/types/plan";
import { makeYearSnapshot } from "@/test_support/record_builders";

/** A YearSnapshot with the dollar values these tests deflate. */
function makeSnap(overrides: Partial<YearSnapshot> = {}): YearSnapshot {
  return makeYearSnapshot({
    year: 2030,
    calendar_year_gross_income: 0,
    post_start_taxes: null,
    expenses: 80_000,
    real_assets_value: 500_000,
    liabilities_balance: 200_000,
    net_worth: 1_000_000,
    investment_growth: 100_000,
    ...overrides,
  });
}

describe("deflate", () => {
  it("returns nominal when years is 0", () => {
    expect(deflate(1000, 0.03, 0)).toBe(1000);
  });

  it("deflates by inflation rate over years", () => {
    // $1000 at 3% inflation over 10 years
    const result = deflate(1000, 0.03, 10);
    expect(result).toBeCloseTo(744.09, 1);
  });

  it("returns nominal when inflation rate is 0", () => {
    expect(deflate(500, 0, 5)).toBe(500);
  });
});

describe("buildDeflators", () => {
  it("produces correct factors for a fixed-rate curve", () => {
    const curve: AssumptionCurve = {
      id: "1",
      plan_id: "1",
      curve_type: "inflation",
      mode: "fixed",
      fixed_rate: 0.03,
      control_points: [],
    };

    const deflators = buildDeflators(curve, 0.03, 2025, 5, 1990);

    expect(deflators[0]).toBe(1);
    for (let i = 1; i <= 5; i++) {
      expect(deflators[i]).toBeCloseTo(Math.pow(1.03, i), 10);
    }
  });

  it("fixed-rate curve equivalence: matches Math.pow compounding", () => {
    const curve: AssumptionCurve = {
      id: "1",
      plan_id: "1",
      curve_type: "inflation",
      mode: "fixed",
      fixed_rate: 0.03,
      control_points: [],
    };

    const deflators = buildDeflators(curve, 0.05, 2025, 30, 1990);

    // Should use fixed_rate (0.03), not fallbackRate (0.05)
    for (let i = 0; i <= 30; i++) {
      expect(deflators[i]).toBeCloseTo(Math.pow(1.03, i), 10);
    }
  });

  it("uses fallbackRate when curve is undefined", () => {
    const deflators = buildDeflators(undefined, 0.04, 2025, 3, 1990);

    expect(deflators[0]).toBe(1);
    expect(deflators[1]).toBeCloseTo(1.04, 10);
    expect(deflators[2]).toBeCloseTo(1.04 * 1.04, 10);
    expect(deflators[3]).toBeCloseTo(1.04 ** 3, 10);
  });

  it("2-point curve produces monotonically steeper deflators than flat 3%", () => {
    // Curve: 3% at age 30 -> 5% at age 60
    // Since the rate rises above 3%, cumulative deflators should exceed flat 3%
    const curveCurve: AssumptionCurve = {
      id: "1",
      plan_id: "1",
      curve_type: "inflation",
      mode: "curve",
      fixed_rate: null,
      control_points: [
        { x: 30, y: 0.03 },
        { x: 60, y: 0.05 },
      ],
    };

    const flatCurve: AssumptionCurve = {
      id: "2",
      plan_id: "1",
      curve_type: "inflation",
      mode: "fixed",
      fixed_rate: 0.03,
      control_points: [],
    };

    const birthYear = 1990;
    const startYear = 2025; // age 35 at start
    const years = 20; // ends at age 55

    const curveDeflators = buildDeflators(curveCurve, 0.03, startYear, years, birthYear);
    const flatDeflators = buildDeflators(flatCurve, 0.03, startYear, years, birthYear);

    // Both start at 1
    expect(curveDeflators[0]).toBe(1);
    expect(flatDeflators[0]).toBe(1);

    // After a few years the curve deflators should exceed flat 3% since all
    // interpolated rates are >= 3% (the curve goes from 3% to 5%)
    // Check last deflator is strictly larger
    expect(curveDeflators[years]).toBeGreaterThan(flatDeflators[years]);

    // Verify curve deflators are monotonically increasing (inflation is positive)
    for (let i = 1; i <= years; i++) {
      expect(curveDeflators[i]).toBeGreaterThan(curveDeflators[i - 1]);
    }
  });

  it("curve mode with single control point uses constant rate", () => {
    const curve: AssumptionCurve = {
      id: "1",
      plan_id: "1",
      curve_type: "inflation",
      mode: "curve",
      fixed_rate: null,
      control_points: [{ x: 40, y: 0.04 }],
    };

    const deflators = buildDeflators(curve, 0.03, 2025, 5, 1990);

    // Single point -> constant 4% rate at every age
    for (let i = 1; i <= 5; i++) {
      expect(deflators[i]).toBeCloseTo(Math.pow(1.04, i), 10);
    }
  });
});

describe("adjustTimeline", () => {
  it("deflates investment growth with other yearly dollar values", () => {
    // Build deflators equivalent to the old behavior: flat 3% over 6 years
    const deflators = buildDeflators(undefined, 0.03, 2025, 5, 1990);

    // Create timeline with 6 snaps so the year-2030 snap is at index 5
    const paddedTimeline = [
      makeSnap({ year: 2025 }),
      makeSnap({ year: 2026 }),
      makeSnap({ year: 2027 }),
      makeSnap({ year: 2028 }),
      makeSnap({ year: 2029 }),
      makeSnap({ year: 2030 }),
    ];

    const adjusted = adjustTimeline(paddedTimeline, deflators, "inflation_adjusted");

    expect(adjusted[5].expenses).toBeCloseTo(deflate(80_000, 0.03, 5));
    expect(adjusted[5].investment_growth).toBeCloseTo(deflate(100_000, 0.03, 5));
  });

  it("deflates real_assets_value and liabilities_balance", () => {
    const deflators = [1, 1.03]; // 2 years
    const timeline = [
      makeSnap({ year: 2025, real_assets_value: 500_000, liabilities_balance: 200_000 }),
      makeSnap({ year: 2026, real_assets_value: 510_000, liabilities_balance: 190_000 }),
    ];

    const adjusted = adjustTimeline(timeline, deflators, "inflation_adjusted");

    // Year 0: factor is 1, no deflation
    expect(adjusted[0].real_assets_value).toBe(500_000);
    expect(adjusted[0].liabilities_balance).toBe(200_000);

    // Year 1: factor is 1.03
    expect(adjusted[1].real_assets_value).toBeCloseTo(510_000 / 1.03);
    expect(adjusted[1].liabilities_balance).toBeCloseTo(190_000 / 1.03);
  });

  it("deflates the calendar-year tax basis and after-start liability with the tax lines", () => {
    const snapshot = makeSnap({
      gross_income: 50_000,
      calendar_year_gross_income: 100_000,
      taxes: 10_000,
      post_start_taxes: 4_000,
    });
    const adjusted = adjustTimeline([snapshot], [2], "inflation_adjusted")[0];
    expect(adjusted.gross_income).toBe(25_000);
    expect(adjusted.calendar_year_gross_income).toBe(50_000);
    expect(adjusted.taxes).toBe(5_000);
    expect(adjusted.post_start_taxes).toBe(2_000);
    expect(adjusted.effective_rate).toBe(snapshot.effective_rate);
  });

  it("deflates unfunded spending, the tax balance and the deduction", () => {
    const snapshot = makeSnap({
      unfunded_expenses: 6_000,
      tax_balance: -800,
      deduction_amount: 30_000,
    });
    const adjusted = adjustTimeline([snapshot], [2], "inflation_adjusted")[0];
    expect(adjusted.unfunded_expenses).toBe(3_000);
    expect(adjusted.tax_balance).toBe(-400);
    expect(adjusted.deduction_amount).toBe(15_000);
    const bare = adjustTimeline(
      [makeSnap({ unfunded_expenses: undefined, tax_balance: undefined })],
      [2],
      "inflation_adjusted",
    )[0];
    expect(bare.unfunded_expenses).toBeUndefined();
    expect(bare.tax_balance).toBeUndefined();
  });

  it("returns timeline as-is when mode is nominal", () => {
    const timeline = [makeSnap()];
    const deflators = [1, 1.03];
    const result = adjustTimeline(timeline, deflators, "nominal");
    expect(result).toBe(timeline);
  });
});
