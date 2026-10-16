import { describe, it, expect, vi, beforeEach } from "vitest";

import { applyStrategyCandidate } from "./tax_strategy_apply";
import type { StrategySearchCandidate } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";

vi.mock("../savings_priorities_panel", () => ({
  priorityPayload: (items: unknown[]) => [...items],
}));

const adapter = makeAdapter();

const rule = {
  priority_type: "roth_conversion",
  source_account_id: "ira",
  target_account_id: "roth",
};

function windowCandidate(end: boolean): StrategySearchCandidate {
  const placeholder = end ? "strategy-window-1-end" : "strategy-window-1-start";
  return {
    changes: [],
    proposal: {
      priorities_to_add: [
        { ...rule, [end ? "end_milestone_id" : "start_milestone_id"]: placeholder } as never,
      ],
      tax_settings: null,
      drawdown_order: null,
      milestones_to_add: [
        end
          ? {
              id: placeholder,
              name: "Start of 2040",
              trigger_type: "date",
              trigger_value: null,
              trigger_date: "2040-01-01",
            }
          : {
              id: placeholder,
              name: "Age 65",
              trigger_type: "age",
              trigger_value: 65,
              trigger_date: null,
            },
      ],
    },
  } as unknown as StrategySearchCandidate;
}

beforeEach(() => {
  vi.clearAllMocks();
  adapter.updatePriorities.mockResolvedValue({ items: [], revision: 1 });
});

describe("applyStrategyCandidate window milestones", () => {
  it("creates a start milestone instead of reusing a switched-off one", async () => {
    adapter.fetchPlan.mockResolvedValue({
      priorities_revision: 0,
      priorities: [],
      milestones: [
        { id: "off65", name: "Age 65", trigger_type: "age", trigger_value: 65, is_active: false },
      ],
    });
    adapter.createMilestone.mockResolvedValue({ id: "new65" });
    await applyStrategyCandidate(adapter, "p1", windowCandidate(false), 0);
    expect(adapter.createMilestone).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ trigger_type: "age", trigger_value: 65 }),
    );
    expect(adapter.updatePriorities.mock.calls[0][1][0].start_milestone_id).toBe("new65");
  });

  it("creates an end milestone instead of reusing a switched-off one", async () => {
    adapter.fetchPlan.mockResolvedValue({
      priorities_revision: 0,
      priorities: [],
      milestones: [
        {
          id: "off2040",
          name: "2040",
          trigger_type: "date",
          trigger_value: null,
          trigger_date: "2040-01-01",
          is_active: false,
        },
      ],
    });
    adapter.createMilestone.mockResolvedValue({ id: "new2040" });
    await applyStrategyCandidate(adapter, "p1", windowCandidate(true), 0);
    expect(adapter.createMilestone).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ trigger_type: "date", trigger_date: "2040-01-01" }),
    );
    expect(adapter.updatePriorities.mock.calls[0][1][0].end_milestone_id).toBe("new2040");
  });

  it("reuses an active matching milestone, skipping a switched-off twin", async () => {
    adapter.fetchPlan.mockResolvedValue({
      priorities_revision: 0,
      priorities: [],
      milestones: [
        { id: "off65", name: "Old", trigger_type: "age", trigger_value: 65, is_active: false },
        { id: "on65", name: "Retire", trigger_type: "age", trigger_value: 65, is_active: true },
      ],
    });
    await applyStrategyCandidate(adapter, "p1", windowCandidate(false), 0);
    expect(adapter.createMilestone).not.toHaveBeenCalled();
    expect(adapter.updatePriorities.mock.calls[0][1][0].start_milestone_id).toBe("on65");
  });
});
