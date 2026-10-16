import { expect, it } from "vitest";
import { historicalYearRanges } from "./historical_year_ranges";

it("shows replay segments in order instead of a backwards or falsely continuous range", () => {
  expect(historicalYearRanges([2000, 2001, 2002, 1928, 1929])).toBe("2000–2002, then 1928–1929");
  expect(historicalYearRanges([2023, 2024, 1928, 1929, 1928])).toBe(
    "2023–2024, then 1928–1929, then 1928",
  );
  expect(historicalYearRanges([2000, 2001])).toBe("2000–2001");
  expect(historicalYearRanges([])).toBe("None");
});
