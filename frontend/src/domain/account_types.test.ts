import { describe, expect, it } from "vitest";
import {
  ACCOUNT_TYPE_GROUPS,
  ACCOUNT_TYPE_LABELS,
  ACCOUNT_TYPE_OPTIONS,
  EARLY_WITHDRAWAL_PENALTY_TYPES,
  ELECTIVE_DEFERRAL_TYPES,
  EMPLOYER_PLAN_TYPES,
  INDIVIDUAL_ONLY_ACCOUNT_TYPES,
  PAYROLL_TARGET_TYPES,
  RETIREMENT_ACCOUNT_TYPES,
  ROTH_TYPES,
  SEPP_ELIGIBLE_TYPES,
  TRADITIONAL_RETIREMENT_TYPES,
  accountTypeLabel,
  employerPlanFamily,
} from "./account_types";

const NEW_TYPES = [
  "traditional_403b",
  "roth_403b",
  "traditional_457b",
  "roth_457b",
  "traditional_401a",
];

describe("account type choices", () => {
  it("groups every labeled type exactly once", () => {
    const grouped = ACCOUNT_TYPE_GROUPS.flatMap((group) => group.types);
    expect(new Set(grouped).size).toBe(grouped.length);
    expect(new Set(grouped)).toEqual(new Set(Object.keys(ACCOUNT_TYPE_LABELS)));
    expect(ACCOUNT_TYPE_GROUPS.map((group) => group.label)).toEqual([
      "Employer plans",
      "IRAs",
      "Taxable and cash",
      "Other",
    ]);
    expect(ACCOUNT_TYPE_OPTIONS.map((option) => option.value)).toEqual(grouped);
  });

  it("names the new employer plans", () => {
    expect(NEW_TYPES.map((type) => accountTypeLabel(type))).toEqual([
      "Traditional 403(b)",
      "Roth 403(b)",
      "Traditional 457(b)",
      "Roth 457(b)",
      "401(a)",
    ]);
    expect(accountTypeLabel("legacy_type")).toBe("legacy_type");
    expect(accountTypeLabel("legacy_type", "Other")).toBe("Other");
    expect(employerPlanFamily("roth_403b")).toBe("403(b)");
    expect(employerPlanFamily("traditional_ira")).toBeNull();
  });
});

describe("account type families", () => {
  it("treats every new type as an individually owned retirement account", () => {
    for (const type of NEW_TYPES) {
      expect(EMPLOYER_PLAN_TYPES.has(type)).toBe(true);
      expect(RETIREMENT_ACCOUNT_TYPES.has(type)).toBe(true);
      expect(INDIVIDUAL_ONLY_ACCOUNT_TYPES.has(type)).toBe(true);
      expect(PAYROLL_TARGET_TYPES.has(type)).toBe(true);
    }
    expect(INDIVIDUAL_ONLY_ACCOUNT_TYPES.has("taxable_brokerage")).toBe(false);
  });

  it("splits traditional and Roth plans", () => {
    expect(
      TRADITIONAL_RETIREMENT_TYPES.has("traditional_403b") &&
        TRADITIONAL_RETIREMENT_TYPES.has("traditional_401a"),
    ).toBe(true);
    expect(ROTH_TYPES.has("roth_457b") && !ROTH_TYPES.has("traditional_457b")).toBe(true);
  });

  it("gives a 401(a) no employee deferrals", () => {
    expect(ELECTIVE_DEFERRAL_TYPES.has("traditional_401a")).toBe(false);
    expect(
      ELECTIVE_DEFERRAL_TYPES.has("traditional_403b") && ELECTIVE_DEFERRAL_TYPES.has("roth_457b"),
    ).toBe(true);
  });

  it("exempts the 457(b) from the 10% tax and from 72(t) series", () => {
    for (const type of ["traditional_457b", "roth_457b"]) {
      expect(EARLY_WITHDRAWAL_PENALTY_TYPES.has(type)).toBe(false);
      expect(SEPP_ELIGIBLE_TYPES.has(type)).toBe(false);
    }
    expect(EARLY_WITHDRAWAL_PENALTY_TYPES.has("traditional_403b")).toBe(true);
    expect([...SEPP_ELIGIBLE_TYPES].sort()).toEqual([
      "traditional_401a",
      "traditional_401k",
      "traditional_403b",
      "traditional_ira",
    ]);
  });
});
