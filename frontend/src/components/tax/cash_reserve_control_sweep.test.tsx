import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CashReserveControl from "./cash_reserve_control";
import type { Account, PlanData } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const mockUpdatePlan = vi.fn();
let mockPlan: PlanData | null = null;
vi.mock("@/stores/plan_store", () => ({
  usePlanStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ plan: mockPlan, updatePlan: mockUpdatePlan }),
}));
const accounts = [
  {
    id: "chk",
    user_id: "u",
    name: "Checking",
    account_type: "checking",
    balance: 20000,
    owner: "self",
  },
] as Account[];
// One stable adapter: a new one per render would reload accounts forever.
const adapter = makeAdapter({ listAccounts: () => Promise.resolve(accounts) });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

describe("CashReserveControl sweep", () => {
  beforeEach(() => {
    mockUpdatePlan.mockReset().mockResolvedValue(undefined);
  });

  it("saves the sweep only when it is on", async () => {
    mockPlan = makePlan({
      id: "plan-1",
      cash_reserve_settings: { enabled: true, account_ids: ["chk"], reserve_amount: 10000 },
    });
    render(<CashReserveControl />);
    fireEvent.click(screen.getByRole("button", { name: "Save cash reserve" }));
    await waitFor(() =>
      expect(mockUpdatePlan).toHaveBeenLastCalledWith("plan-1", {
        cash_reserve_settings: { enabled: true, account_ids: ["chk"], reserve_amount: 10000 },
      }),
    );
    fireEvent.click(screen.getByLabelText(/Invest cash above the reserve/));
    fireEvent.click(screen.getByRole("button", { name: "Save cash reserve" }));
    await waitFor(() =>
      expect(mockUpdatePlan).toHaveBeenLastCalledWith("plan-1", {
        cash_reserve_settings: {
          enabled: true,
          account_ids: ["chk"],
          reserve_amount: 10000,
          sweep_excess: true,
        },
      }),
    );
  });

  it("opens with a saved sweep checked", () => {
    mockPlan = makePlan({
      id: "plan-1",
      cash_reserve_settings: {
        enabled: true,
        account_ids: ["chk"],
        reserve_amount: 10000,
        sweep_excess: true,
      },
    });
    render(<CashReserveControl />);
    expect(screen.getByLabelText(/Invest cash above the reserve/)).toBeChecked();
  });
});
