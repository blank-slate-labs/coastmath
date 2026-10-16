import { describe, expect, it } from "vitest";
import type { Milestone } from "@/types/plan";
import {
  milestoneWindowError,
  milestoneWindowWarning,
  resolveMilestoneYear,
} from "./milestone_window";

const ms = (over: Partial<Milestone>): Milestone => ({
  id: "x",
  plan_id: "p",
  name: "M",
  trigger_type: "age",
  trigger_value: null,
  trigger_date: null,
  metric: null,
  expense_multiple: null,
  relative_to_id: null,
  offset_years: 0,
  sort_order: 0,
  ...over,
});
const retire = ms({ id: "retire", name: "Retirement", trigger_value: 47 });
const ss = ms({ id: "ss", name: "Social Security Begins", trigger_value: 70 });
const fi = ms({ id: "fi", name: "FI", trigger_type: "expense_multiple", expense_multiple: 25 });
const after = ms({
  id: "after",
  name: "Five years after retirement",
  trigger_type: "relative",
  relative_to_id: "retire",
  offset_years: 5,
});
const all = [retire, ss, fi, after];

describe("resolveMilestoneYear", () => {
  it("resolves age, date and relative milestones", () => {
    expect(resolveMilestoneYear(retire, all, 1992)).toBe(2039);
    expect(
      resolveMilestoneYear(ms({ trigger_type: "date", trigger_date: "2031-06-01" }), all, 1992),
    ).toBe(2031);
    expect(resolveMilestoneYear(after, all, 1992)).toBe(2044);
    expect(resolveMilestoneYear(fi, all, 1992)).toBeNull();
  });
});

describe("milestoneWindowError", () => {
  it("rejects a start after the end", () => {
    expect(milestoneWindowError("ss", "retire", all, 1992)).toMatch(/2062.*after.*2039/);
  });
  it("accepts ordered, open, identical and projection-dependent windows", () => {
    expect(milestoneWindowError("retire", "ss", all, 1992)).toBeNull();
    expect(milestoneWindowError("", "ss", all, 1992)).toBeNull();
    expect(milestoneWindowError("ss", "ss", all, 1992)).toBeNull();
    expect(milestoneWindowError("fi", "retire", all, 1992)).toBeNull();
  });
});

describe("milestoneWindowWarning", () => {
  const outcome = (id: string, year: number | null) => ({
    id,
    name: id,
    trigger_type: "age" as const,
    year,
  });
  it("stays quiet for fixed windows", () => {
    expect(milestoneWindowWarning("retire", "ss", all, [])).toBeNull();
    expect(milestoneWindowWarning("", "fi", all, [])).toBeNull();
  });
  it("explains that a projected milestone cannot be checked before the plan runs", () => {
    expect(milestoneWindowWarning("retire", "fi", all, null)).toMatch(
      /"FI" fires only when the projection says so/,
    );
  });
  it("reports a dead window from the latest projection", () => {
    const fired = [outcome("retire", 2039), outcome("fi", 2035)];
    expect(milestoneWindowWarning("retire", "fi", all, fired)).toMatch(
      /"Retirement" fires in 2039, after "FI" in 2035, so this never runs/,
    );
    expect(milestoneWindowWarning("fi", "retire", all, fired)).toMatch(/runs from 2035 to 2039/);
    expect(
      milestoneWindowWarning("fi", "retire", all, [outcome("retire", 2039), outcome("fi", null)]),
    ).toMatch(/"FI" never does, so this never runs/);
    expect(
      milestoneWindowWarning("retire", "fi", all, [outcome("retire", 2039), outcome("fi", null)]),
    ).toMatch(/end never fires, so it runs from "Retirement" \(2039\) onward/);
  });
});

describe("switched-off milestones", () => {
  it("have no known year, so windows bounded by them are not checked", () => {
    const off = { ...retire, is_active: false };
    expect(resolveMilestoneYear(off, [off, ss], 1980)).toBeNull();
    const chained = { ...after, relative_to_id: "retire" };
    expect(resolveMilestoneYear(chained, [off, chained], 1980)).toBeNull();
    expect(milestoneWindowError("ss", "retire", [ss, off], 1980)).toBeNull();
    expect(milestoneWindowError("ss", "retire", [ss, retire], 1980)).not.toBeNull();
  });
});
