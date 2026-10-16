import {
  dayLabel,
  exact,
  kindFor,
  mappingFromColumns,
  rangeLabel,
  roleOf,
  valueList,
  withRole,
} from "./import_format";
import { csvDetails, csvMapping } from "./import_test_data";

it("reads and moves column roles", () => {
  const mapping = csvMapping();
  expect([0, 1, 2, 3, 4].map((i) => roleOf(mapping, i))).toEqual([
    "date",
    "description",
    "amount",
    "category",
    "ignored",
  ]);
  const moved = withRole(mapping, 4, "date");
  expect(moved.date_column).toBe(4);
  expect(roleOf(moved, 0)).toBe("ignored");
  const memo = withRole(mapping, 4, "description");
  expect(memo.description_columns).toEqual([1, 4]);
  expect(withRole(memo, 1, "ignored").description_columns).toEqual([4]);
  const split = withRole(withRole(mapping, 4, "debit"), 5, "credit");
  expect(split.amount_strategy).toBe("split");
  expect(withRole(split, 2, "amount").amount_strategy).toBe("signed");
  expect(withRole(mapping, 5, "type").amount_strategy).toBe("indicator");
  expect(withRole(withRole(mapping, 5, "debit"), 5, "type").amount_strategy).toBe("split");
});

it("builds a starting mapping from suggested column roles", () => {
  const details = csvDetails({
    decimal_separator: ",",
    columns: [
      { index: 0, name: "When", suggested_role: "date" },
      { index: 1, name: "Memo", suggested_role: "memo" },
      { index: 2, name: "Odd", suggested_role: "balance" },
      { index: 3, name: "Out", suggested_role: "debit" },
    ],
  });
  const mapping = mappingFromColumns(details);
  expect(mapping).toMatchObject({
    date_column: 0,
    description_columns: [1],
    debit_column: 3,
    amount_strategy: "split",
    date_format: null,
    decimal_separator: ",",
  });
  expect(mappingFromColumns(csvDetails()).decimal_separator).toBe(".");
});

it("formats dates, amounts, kinds and value lists", () => {
  expect(dayLabel("2026-08-03")).toContain("2026");
  expect(rangeLabel("2026-08-03", "2026-08-03")).toBe(dayLabel("2026-08-03"));
  expect(rangeLabel("2026-08-01", "2026-08-31")).toContain("–");
  expect(exact(25.5, "EUR")).toContain("25.50");
  expect(exact(25.5, null)).toContain("25.50");
  expect(kindFor("CREDIT", "CREDIT_CARD")).toBe("credit_card");
  expect(kindFor("CREDIT", "LINE_OF_CREDIT")).toBe("credit_card");
  expect(kindFor("DEPOSITORY", "MONEY_MARKET")).toBe("checking");
  expect(kindFor("DEPOSITORY", "SAVINGS")).toBe("savings");
  expect(kindFor("LOAN", null)).toBe("other");
  expect(valueList(" Debit, , WITHDRAWAL ")).toEqual(["debit", "withdrawal"]);
});
