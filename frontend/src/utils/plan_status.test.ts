import { describe, expect, it } from "vitest";
import type { SimulationResult } from "@/types/plan";
import { planStatus } from "./plan_status";

const result = (
  over: Record<string, unknown>,
  snaps: Record<string, unknown>[],
): SimulationResult =>
  ({
    metadata: { start_year: 2026, end_year: 2030, success: true, failure_year: null, ...over },
    yearly_snapshots: snaps.map((s) => ({
      accounts: {},
      liabilities_balance: 0,
      real_assets_value: 0,
      ...s,
    })),
  }) as unknown as SimulationResult;

describe("planStatus", () => {
  it("is on track only when spending is funded and net worth stays positive", () => {
    const status = planStatus(
      result({}, [
        { year: 2026, net_worth: 100 },
        { year: 2027, net_worth: 200 },
      ]),
    );
    expect(status?.label).toBe("Steady-return forecast: funded");
    expect(status?.tone).toBe("success");
    expect(status?.detail).toMatch(/net worth stays positive/);
  });

  it("flags negative net worth even when the engine says spending is funded", () => {
    const status = planStatus(
      result({}, [
        { year: 2026, net_worth: 100 },
        { year: 2027, net_worth: -5 },
      ]),
    );
    expect(status?.label).toBe("Net worth negative from 2027");
    expect(status?.tone).toBe("warning");
  });

  it("reports unfunded spending with its year", () => {
    const status = planStatus(
      result({ success: false, failure_year: 2050 }, [{ year: 2026, net_worth: 1 }]),
    );
    expect(status?.label).toBe("Spending unfunded from 2050");
    expect(status?.tone).toBe("danger");
  });

  it("treats runaway balances as an invalid projection, ahead of everything else", () => {
    const status = planStatus(
      result({}, [
        { year: 2026, net_worth: 1 },
        { year: 2027, net_worth: -1.6e57, liabilities_balance: 1.6e57 },
      ]),
    );
    expect(status?.label).toBe("Projection invalid from 2027");
    expect(status?.tone).toBe("danger");
  });

  it("returns null without a result", () => {
    expect(planStatus(null)).toBeNull();
  });
});
