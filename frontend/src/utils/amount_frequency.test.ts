import { describe, expect, it } from "vitest";
import {
  AMOUNT_FREQUENCIES,
  AMOUNT_LABELS,
  FREQUENCY_LABELS,
  PERIODS_PER_YEAR,
  PERIOD_SUFFIXES,
  SHORT_PERIOD_SUFFIXES,
  entryAnnual,
  entryDisplay,
  formatPerPeriod,
  fromAnnual,
  initialEntry,
  openingFrequency,
  toAnnual,
  type AmountEntry,
  type AmountFrequency,
} from "./amount_frequency";

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

describe("amount frequency units", () => {
  it("covers each unit once with its periods per year and every label", () => {
    expect([...AMOUNT_FREQUENCIES].sort()).toEqual([
      "annual",
      "biweekly",
      "monthly",
      "quarterly",
      "semimonthly",
      "weekly",
    ]);
    expect(PERIODS_PER_YEAR).toEqual({
      annual: 1,
      quarterly: 4,
      monthly: 12,
      semimonthly: 24,
      biweekly: 26,
      weekly: 52,
    });
    for (const labels of [
      FREQUENCY_LABELS,
      AMOUNT_LABELS,
      PERIOD_SUFFIXES,
      SHORT_PERIOD_SUFFIXES,
    ]) {
      expect(Object.keys(labels).sort()).toEqual([...AMOUNT_FREQUENCIES].sort());
    }
  });

  it.each(AMOUNT_FREQUENCIES)("round-trips %s amounts that fit the unit exactly", (unit) => {
    // 31,200 divides evenly into every unit.
    expect(toAnnual(fromAnnual(31200, unit), unit)).toBe(31200);
    for (const perPeriod of [0, 1234.56, 2500.25, 0.01, -100.25]) {
      expect(fromAnnual(toAnnual(perPeriod, unit), unit)).toBe(perPeriod);
    }
  });

  it("rounds non-annual display to cents and leaves annual exact", () => {
    expect(fromAnnual(100000, "biweekly")).toBe(3846.15);
    expect(fromAnnual(100000, "weekly")).toBe(1923.08);
    expect(fromAnnual(100000, "semimonthly")).toBe(4166.67);
    expect(fromAnnual(1000, "monthly")).toBe(83.33);
    expect(fromAnnual(1000.01, "quarterly")).toBe(250);
    expect(fromAnnual(100000.015, "annual")).toBe(100000.015);
    // Half a cent rounds away from zero in both directions, as PostgreSQL does.
    expect(fromAnnual(0.5, "quarterly")).toBe(0.13);
    expect(fromAnnual(-0.5, "quarterly")).toBe(-0.13);
    expect(fromAnnual(-1000.01, "monthly")).toBe(-83.33);
  });

  it("annualizes to cents without float noise and passes annual values through", () => {
    expect(1000.01 * 12).not.toBe(12000.12);
    expect(toAnnual(1000.01, "monthly")).toBe(12000.12);
    expect(toAnnual(1002.6, "biweekly")).toBe(26067.6);
    expect(toAnnual(2500.25, "monthly")).toBe(30003);
    expect(toAnnual(1250, "semimonthly")).toBe(30000);
    expect(toAnnual(7123.456, "annual")).toBe(7123.456);
    expect(toAnnual(Number("1e308"), "monthly")).toBe(Infinity);
    expect(toAnnual(Number.NaN, "weekly")).toBeNaN();
  });
});

describe("amount entries", () => {
  it("opens a saved amount as its exact annual value and a new one in the default unit", () => {
    expect(initialEntry(100000.01, "biweekly")).toEqual({
      value: "100000.01",
      frequency: "annual",
    });
    expect(initialEntry(undefined, "monthly")).toEqual({ value: "0", frequency: "monthly" });
    expect(openingFrequency(null, "annual")).toBe("annual");
    expect(openingFrequency(undefined, "annual")).toBe("annual");
    expect(openingFrequency("weekly", "annual")).toBe("weekly");
  });

  it("switching the displayed unit without editing preserves the exact annual amount", () => {
    const entry = initialEntry(100000.01, "annual");
    const shown = Object.fromEntries(
      AMOUNT_FREQUENCIES.map((unit) => [unit, entryDisplay(entry, unit)]),
    );
    expect(shown).toEqual({
      weekly: "1923.08",
      biweekly: "3846.15",
      semimonthly: "4166.67",
      monthly: "8333.33",
      quarterly: "25000",
      annual: "100000.01",
    });
    // Displaying never rewrites the entry, so every unit still saves the same amount.
    expect(entry).toEqual({ value: "100000.01", frequency: "annual" });
    expect(entryAnnual(entry)).toBe(100000.01);
  });

  it("shows an edited value verbatim in its own unit and converted in others", () => {
    const entry: AmountEntry = { value: "1153.85", frequency: "biweekly" };
    expect(entryAnnual(entry)).toBe(30000.1);
    expect(entryDisplay(entry, "biweekly")).toBe("1153.85");
    expect(entryDisplay(entry, "monthly")).toBe("2500.01");
    expect(entryDisplay(entry, "annual")).toBe("30000.1");
    expect(entryDisplay({ value: " ", frequency: "weekly" }, "annual")).toBe(" ");
  });
});

describe("summaries", () => {
  it.each<[AmountFrequency | null | undefined, string]>([
    [null, "$31,200.00/yr"],
    [undefined, "$31,200.00/yr"],
    ["annual", "$31,200.00/yr"],
    ["quarterly", "$7,800.00/qtr"],
    ["monthly", "$2,600.00/mo"],
    ["semimonthly", "$1,300.00 2×/mo"],
    ["biweekly", "$1,200.00/2 wks"],
    ["weekly", "$600.00/wk"],
  ])("formats a %s row in its saved unit", (unit, text) => {
    expect(formatPerPeriod(31200, unit, money.format)).toBe(text);
  });

  it("formats a sentence suffix", () => {
    expect(formatPerPeriod(30000, "semimonthly", money.format, PERIOD_SUFFIXES)).toBe(
      "$1,250.00 twice a month",
    );
    expect(formatPerPeriod(31200, "biweekly", money.format, PERIOD_SUFFIXES)).toBe(
      "$1,200.00 every 2 weeks",
    );
  });
});
