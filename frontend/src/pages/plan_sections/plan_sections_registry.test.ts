/** The builder registry keeps every section, in order, wherever the section components live. */

import { describe, it, expect } from "vitest";

import { extensions } from "@/extensions";
import { TRANSACTIONS_ENABLED } from "@/feature_flags";
import { PLAN_SECTIONS } from "@/pages/plan_setup";

const BEFORE_INSERTS = [
  { key: "plan_details", title: "Plan details", essential: true },
  { key: "assumptions", title: "Assumptions" },
  { key: "milestones", title: "Milestones" },
  { key: "income", title: "Income streams", essential: true },
  { key: "expenses", title: "Expenses", essential: true },
  { key: "flex", title: "Flexible spending" },
  { key: "accounts", title: "Accounts", essential: true },
];

const AFTER_INSERTS = [
  { key: "income_allocation", title: "Income allocation" },
  { key: "property_debt", title: "Property and debt" },
  { key: "drawdown", title: "Drawdown order" },
  { key: "charitable", title: "Charitable giving" },
  { key: "healthcare", title: "Health coverage" },
  { key: "estate", title: "Partner and estate" },
  { key: "notes", title: "Notes" },
];

describe("PLAN_SECTIONS", () => {
  it("lists the built-in sections in order, with inserted sections after Accounts", () => {
    const inserted = [
      ...(extensions.planner?.sections ?? []).map((s) => s.key),
      ...(TRANSACTIONS_ENABLED ? ["transactions"] : []),
    ];
    expect(PLAN_SECTIONS.map((s) => s.key)).toEqual([
      ...BEFORE_INSERTS.map((s) => s.key),
      ...inserted,
      ...AFTER_INSERTS.map((s) => s.key),
    ]);
  });

  it("keeps each built-in section's title and essential flag", () => {
    const builtIn = PLAN_SECTIONS.filter((s) =>
      [...BEFORE_INSERTS, ...AFTER_INSERTS].some((b) => b.key === s.key),
    ).map(({ key, title, essential }) => ({ key, title, ...(essential ? { essential } : {}) }));
    expect(builtIn).toEqual([...BEFORE_INSERTS, ...AFTER_INSERTS]);
  });

  it("has unique keys and a component for every section", () => {
    const keys = PLAN_SECTIONS.map((s) => s.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const section of PLAN_SECTIONS) {
      expect(typeof section.Component, section.key).toBe("function");
    }
  });
});
