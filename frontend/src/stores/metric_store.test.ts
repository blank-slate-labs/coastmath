import { describe, it, expect, beforeEach } from "vitest";

import {
  defaultMetricSettings,
  effectiveRateForSnapshot,
  spendingForSnapshot,
  taxesForSnapshot,
  useMetricStore,
} from "./metric_store";
import type { YearSnapshot } from "@/types/plan";

const snap = {
  year: 2030,
  age: 40,
  gross_income: 100000,
  calendar_year_gross_income: 200000,
  taxes: 25000,
  fica_tax: 7000,
  post_start_taxes: 8000,
  expenses: 60000,
  effective_rate: 0.125,
  cash_flow: {
    expenses: [
      { name: "Housing", amount: 30000, category: "essential" },
      { name: "Travel", amount: 20000, category: "discretionary" },
      { name: "Misc", amount: 10000, category: null },
    ],
  },
} as unknown as YearSnapshot;

describe("metric definitions", () => {
  beforeEach(() => {
    localStorage.clear();
    useMetricStore.setState({ planId: null, settings: defaultMetricSettings });
  });

  it("reproduces engine figures with default settings", () => {
    expect(spendingForSnapshot(snap, defaultMetricSettings)).toBe(60000);
    expect(effectiveRateForSnapshot(snap, defaultMetricSettings)).toBe(0.125);
    expect(taxesForSnapshot(snap, defaultMetricSettings)).toBe(25000);
  });

  it("filters spending by category and can count taxes as spending", () => {
    expect(
      spendingForSnapshot(snap, { ...defaultMetricSettings, includeDiscretionary: false }),
    ).toBe(40000);
    expect(
      spendingForSnapshot(snap, {
        ...defaultMetricSettings,
        includeUncategorized: false,
        includeEssential: false,
      }),
    ).toBe(20000);
    expect(
      spendingForSnapshot(snap, { ...defaultMetricSettings, includeTaxesInSpending: true }),
    ).toBe(85000);
    // Without a cash-flow breakdown the engine total is used.
    expect(
      spendingForSnapshot({ ...snap, cash_flow: null } as unknown as YearSnapshot, {
        ...defaultMetricSettings,
        includeDiscretionary: false,
      }),
    ).toBe(60000);
  });

  it("recomputes the effective rate for the chosen denominator and payroll toggle", () => {
    expect(
      effectiveRateForSnapshot(snap, { ...defaultMetricSettings, includePayrollTax: false }),
    ).toBeCloseTo(0.09);
    expect(
      effectiveRateForSnapshot(snap, {
        ...defaultMetricSettings,
        taxRateDenominator: "total_outflows",
      }),
    ).toBeCloseTo(8000 / 68000);
    expect(
      effectiveRateForSnapshot(snap, {
        ...defaultMetricSettings,
        taxRateDenominator: "total_outflows",
        includePayrollTax: false,
      }),
    ).toBeCloseTo(18000 / 78000);
  });

  it("persists settings per plan in the browser and resets to defaults", () => {
    const store = useMetricStore.getState();
    store.load("p1");
    store.update({ includeDiscretionary: false });
    expect(JSON.parse(localStorage.getItem("coastmath:metrics:p1")!)).toMatchObject({
      includeDiscretionary: false,
    });
    store.load("p2");
    expect(useMetricStore.getState().settings.includeDiscretionary).toBe(true);
    store.load("p1");
    expect(useMetricStore.getState().settings.includeDiscretionary).toBe(false);
    useMetricStore.getState().reset();
    expect(localStorage.getItem("coastmath:metrics:p1")).toBeNull();
    expect(useMetricStore.getState().settings).toEqual(defaultMetricSettings);
  });
});
import { lifetimeEffectiveRate } from "./metric_store";
it("weights lifetime effective rate by the chosen denominator instead of averaging yearly rates", () => {
  const snapshots = [
    {
      taxes: 100,
      gross_income: 500,
      calendar_year_gross_income: 2000,
      post_start_taxes: 50,
      expenses: 500,
    },
    { taxes: 600, gross_income: 1500, calendar_year_gross_income: 6000, expenses: 1000 },
  ] as YearSnapshot[];
  expect(lifetimeEffectiveRate(snapshots, defaultMetricSettings)).toBe(0.0875);
  expect(
    lifetimeEffectiveRate(snapshots, {
      ...defaultMetricSettings,
      taxRateDenominator: "total_outflows",
    }),
  ).toBeCloseTo(650 / 2150);
});

it("splits a partially discretionary expense between the essential and discretionary toggles", () => {
  const split = {
    ...snap,
    expenses: 70000,
    cash_flow: {
      expenses: [
        ...snap.cash_flow!.expenses,
        { name: "Groceries", amount: 10000, category: "essential", discretionary_amount: 3200 },
      ],
    },
  } as unknown as YearSnapshot;
  expect(spendingForSnapshot(split, defaultMetricSettings)).toBe(70000);
  // Essential only: housing + the 6,800 essential part of groceries.
  expect(
    spendingForSnapshot(split, {
      ...defaultMetricSettings,
      includeDiscretionary: false,
      includeUncategorized: false,
    }),
  ).toBe(36800);
  // Discretionary only: travel + the 3,200 discretionary part.
  expect(
    spendingForSnapshot(split, {
      ...defaultMetricSettings,
      includeEssential: false,
      includeUncategorized: false,
    }),
  ).toBe(23200);
});
