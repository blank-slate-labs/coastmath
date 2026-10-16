import { describe, expect, it } from "vitest";
import type { Milestone, SimulationResult } from "@/types/plan";
import { financialIndependence, resolveFinancialIndependence } from "./financial_independence";
import { timelineEvents } from "./timeline_events";
import { makePlan } from "@/test_support/plan_builder";

type Estimate = {
  year: number | null;
  basis_year: number | null;
  target: number | null;
  multiple: number;
};
const reached: Estimate = { year: 2027, basis_year: 2026, target: 2250000, multiple: 25 };

const result = (
  snaps: Record<string, unknown>[],
  outcomes: { id: string; year: number | null }[] = [],
  fiEstimate: Estimate | null = reached,
) =>
  ({
    metadata: {
      start_year: 2026,
      end_year: 2026 + snaps.length,
      first_year_fraction: 0.5,
      milestone_outcomes: outcomes,
      fi_estimate: fiEstimate,
    },
    yearly_snapshots: snaps.map((s) => ({ liabilities_balance: 0, ...s })),
  }) as unknown as SimulationResult;

const fiMilestone = {
  id: "m1",
  name: "My FI",
  trigger_type: "expense_multiple",
  expense_multiple: 30,
  metric: "liquid_net_worth",
  sort_order: 0,
} as Milestone;
const plan = (milestones: Milestone[] = []) => makePlan({ birth_year: 1990, milestones });

describe("financialIndependence", () => {
  const snaps = [
    { year: 2026, age: 36, expenses: 45000, accounts: { a: 2300000 } },
    { year: 2027, age: 37, expenses: 99000, accounts: { a: 2600000 } },
  ];

  it("reads the engine's estimate and the snapshot of the year it lands", () => {
    const fi = financialIndependence(result(snaps));
    expect(fi.snapshot).toMatchObject({ year: 2027, age: 37 });
    expect(fi).toMatchObject({ basisYear: 2026, target: 2250000, multiple: 25 });
  });

  it("shows no estimate when the engine never reaches it", () => {
    const fi = financialIndependence(
      result(snaps, [], { year: null, basis_year: null, target: null, multiple: 25 }),
    );
    expect(fi).toEqual({ snapshot: null, basisYear: null, target: null, multiple: 25 });
  });

  it("never recomputes the estimate in the browser when the result lacks it", () => {
    // These snapshots would cross 25× spending; only the engine decides.
    const absent = result(snaps);
    delete absent.metadata.fi_estimate;
    expect(financialIndependence(absent).snapshot).toBeNull();
    expect(financialIndependence(result(snaps, [], null)).snapshot).toBeNull();
    expect(financialIndependence(null).snapshot).toBeNull();
  });

  it("shows nothing for a landing year outside the projected snapshots", () => {
    expect(
      financialIndependence(result(snaps, [], { ...reached, year: 2030, basis_year: 2029 }))
        .snapshot,
    ).toBeNull();
  });
});

describe("resolveFinancialIndependence", () => {
  const snaps = [
    { year: 2026, expenses: 45000, accounts: { a: 2300000 } },
    { year: 2027, expenses: 90000, accounts: { a: 2600000 } },
  ];

  it("uses the estimate when the plan has no FI milestone", () => {
    expect(resolveFinancialIndependence(plan(), result(snaps), false)).toMatchObject({
      source: "estimate",
      year: 2027,
    });
  });

  it("prefers the user's own FI milestone over the estimate", () => {
    const fi = resolveFinancialIndependence(
      plan([fiMilestone]),
      result(snaps, [{ id: "m1", year: null }]),
      false,
    );
    expect(fi).toMatchObject({ source: "milestone", year: null });
  });

  it("returns nothing once the estimate is removed and no FI milestone exists", () => {
    expect(resolveFinancialIndependence(plan(), result(snaps), true)).toBeNull();
  });
});

describe("timelineEvents FI estimate", () => {
  const snaps = [
    { year: 2026, expenses: 45000, accounts: { a: 2300000 } },
    { year: 2027, expenses: 90000, accounts: { a: 2600000 } },
  ];
  const fiEvents = (events: ReturnType<typeof timelineEvents>) =>
    events.filter((e) => e.kind === "fi");

  it("labels the automatic marker as the CoastMath estimate", () => {
    expect(fiEvents(timelineEvents(plan(), result(snaps)))).toMatchObject([
      { year: 2027, label: "Financial independence (CoastMath estimate)" },
    ]);
  });

  it("drops the estimate when the user has their own FI milestone or removed it", () => {
    const own = timelineEvents(
      plan([fiMilestone]),
      result(snaps, [{ id: "m1", name: "My FI", year: 2027 } as never]),
    );
    expect(fiEvents(own)).toEqual([]);
    expect(own.map((e) => e.label)).toEqual(["My FI"]);
    expect(fiEvents(timelineEvents(plan(), result(snaps), { fiEstimateHidden: true }))).toEqual([]);
  });
});
