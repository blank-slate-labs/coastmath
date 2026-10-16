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
const mockListAccounts = vi.fn<() => Promise<Account[]>>();
const adapter = makeAdapter({ listAccounts: mockListAccounts });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const accounts = [
  {
    id: "chk",
    user_id: "u",
    name: "Checking",
    account_type: "checking",
    balance: 20000,
    owner: "self",
  },
  {
    id: "sav",
    user_id: "u",
    name: "Savings",
    account_type: "savings",
    balance: 50000,
    owner: "self",
  },
  {
    id: "brk",
    user_id: "u",
    name: "Brokerage",
    account_type: "taxable_brokerage",
    balance: 90000,
    owner: "self",
  },
] as Account[];
const basePlan = makePlan({ id: "plan-1", user_id: "u", cash_reserve_settings: null });

describe("CashReserveControl", () => {
  beforeEach(() => {
    mockUpdatePlan.mockReset().mockResolvedValue(undefined);
    mockListAccounts.mockResolvedValue(accounts);
    mockPlan = { ...basePlan };
  });

  it("is off by default and offers only checking and savings accounts", async () => {
    render(<CashReserveControl />);
    expect(screen.getByLabelText("Enabled")).not.toBeChecked();
    fireEvent.click(screen.getByLabelText("Enabled"));
    expect(await screen.findByLabelText(/Checking/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Savings/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Brokerage/)).toBeNull();
  });

  it("requires an account and an amount, then saves them in the chosen spending order", async () => {
    render(<CashReserveControl />);
    fireEvent.click(screen.getByLabelText("Enabled"));
    expect(screen.getByRole("button", { name: "Save cash reserve" })).toBeDisabled();
    fireEvent.click(await screen.findByLabelText(/Checking/));
    fireEvent.click(screen.getByLabelText(/Savings/));
    fireEvent.change(screen.getByLabelText(/Reserve amount/), { target: { value: "30000" } });
    fireEvent.click(screen.getByRole("button", { name: "Spend Savings earlier" }));
    fireEvent.click(screen.getByRole("button", { name: "Save cash reserve" }));
    await waitFor(() =>
      expect(mockUpdatePlan).toHaveBeenCalledWith("plan-1", {
        cash_reserve_settings: {
          enabled: true,
          account_ids: ["sav", "chk"],
          reserve_amount: 30000,
        },
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("saved");
  });

  it("turns a saved reserve off without discarding it", async () => {
    mockPlan = makePlan({
      ...basePlan,
      cash_reserve_settings: { enabled: true, account_ids: ["chk"], reserve_amount: 10000 },
    });
    render(<CashReserveControl />);
    fireEvent.click(screen.getByLabelText("Enabled"));
    fireEvent.click(screen.getByRole("button", { name: "Save cash reserve" }));
    await waitFor(() =>
      expect(mockUpdatePlan).toHaveBeenCalledWith("plan-1", {
        cash_reserve_settings: { enabled: false, account_ids: ["chk"], reserve_amount: 10000 },
      }),
    );
  });
});
