import { describe, expect, it } from "vitest";

import {
  categoryForPercent,
  flexibleLabel,
  formatPercent,
  openingShareMode,
  parsePercent,
} from "./discretionary_share";

describe("discretionary share", () => {
  it("mirrors the server's category rule", () => {
    expect([0, 49.99, 50, 100].map(categoryForPercent)).toEqual([
      "essential",
      "essential",
      "discretionary",
      "discretionary",
    ]);
  });

  it("labels only partial splits as flexible", () => {
    expect(flexibleLabel(40)).toBe("40% flexible");
    expect(flexibleLabel(12.345)).toBe("12.35% flexible");
    expect([0, 100, null, undefined].map(flexibleLabel)).toEqual([null, null, null, null]);
    expect(formatPercent(62.5)).toBe("62.5%");
  });

  it("opens presets for category-only and all-or-nothing records", () => {
    expect(openingShareMode(null, "discretionary")).toBe("discretionary");
    expect(openingShareMode(undefined, null)).toBe("essential");
    expect(openingShareMode(0, "essential")).toBe("essential");
    expect(openingShareMode(100, "discretionary")).toBe("discretionary");
    expect(openingShareMode(40, "essential")).toBe("custom");
  });

  it("parses only percents from 0 to 100", () => {
    expect(["0", "100", "33.3"].map(parsePercent)).toEqual([0, 100, 33.3]);
    expect(["", " ", "-1", "100.1", "abc", "Infinity"].map(parsePercent)).toEqual([
      null,
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});
