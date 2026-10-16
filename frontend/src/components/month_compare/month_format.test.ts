import {
  categoryDifferences,
  fiChange,
  finalNetWorth,
  reasonText,
  shownNetWorth,
} from "./month_format";
import { outcome } from "./month_compare_test_data";
import { month } from "@/components/ledger/ledger_test_data";

const SOURCES = [
  { id: "a1", provider: "file", name: "Synthetic card", coverage: [], settled: [], waiting: false },
];

it("explains each incomplete-month reason", () => {
  const reason = (code: string, source_ids: string[] = ["a1"]) =>
    reasonText(month({ complete: false, reasons: [{ code, source_ids }] }), SOURCES);
  expect(reason("settling")).toBe("Still settling: Synthetic card.");
  expect(reason("waiting_for_history", ["gone"])).toBe("Waiting for history: An account.");
  expect(reason("partial_coverage", [])).toBe("Not fully covered: An account.");
  expect(reason("something_new")).toBe("Incomplete.");
  expect(reasonText(month({ complete: false, reasons: [] }), SOURCES)).toBe("Incomplete.");
});

it("compares FI ages and reads net worth in either currency mode", () => {
  const plan = outcome({ fi_age: 55 });
  expect(fiChange(outcome({ fi_age: 55 }), plan)).toBe("Same");
  expect(fiChange(outcome({ fi_age: 54 }), plan)).toBe("1 yr earlier");
  expect(fiChange(outcome({ fi_age: null }), plan)).toBeNull();
  const point = { year: 2030, age: 45, net_worth: 103, inflation_factor: 1.03 };
  expect(shownNetWorth(point, "nominal")).toBe(103);
  expect(shownNetWorth(point, "inflation_adjusted")).toBeCloseTo(100);
  expect(shownNetWorth({ ...point, inflation_factor: 0 }, "inflation_adjusted")).toBe(103);
  expect(
    finalNetWorth(outcome({ net_worth_path: [], final_net_worth: 7 }), "inflation_adjusted"),
  ).toBe(7);
});

it("ranks category differences by size and drops ties", () => {
  expect(categoryDifferences({ a: 10, b: 50, same: 5 }, { a: 40, c: 20, same: 5 }, 2)).toEqual([
    { key: "b", a: 50, b: 0, difference: -50 },
    { key: "a", a: 10, b: 40, difference: 30 },
  ]);
  expect(categoryDifferences({ x: 1, y: 1 }, { x: 2, y: 2 })).toEqual([
    { key: "x", a: 1, b: 2, difference: 1 },
    { key: "y", a: 1, b: 2, difference: 1 },
  ]);
});
