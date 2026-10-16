import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import DrawdownEditor from "./drawdown_editor";
import type { DrawdownEntry, Account } from "@/types/plan";

// Mock the plan store
const mockUpdateDrawdownOrder = vi.fn();
vi.mock("@/stores/plan_store", () => ({
  usePlanStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ updateDrawdownOrder: mockUpdateDrawdownOrder }),
}));

// ── Fixtures ──────────────────────────────────────────────────────

const accounts: Account[] = [
  {
    id: "acc-1",
    user_id: "u1",
    name: "401k",
    account_type: "traditional_401k",
    balance: 50000,
    owner: "self",
  },
  {
    id: "acc-2",
    user_id: "u1",
    name: "Roth IRA",
    account_type: "roth_ira",
    balance: 25000,
    owner: "self",
  },
  {
    id: "acc-3",
    user_id: "u1",
    name: "Brokerage",
    account_type: "taxable_brokerage",
    balance: 10000,
    owner: "self",
  },
];

const entries: DrawdownEntry[] = [
  { id: "d1", plan_id: "plan-1", rank: 1, source_account_id: "acc-1" },
  { id: "d2", plan_id: "plan-1", rank: 2, source_account_id: "acc-2" },
];

// ── Tests ─────────────────────────────────────────────────────────

describe("DrawdownEditor", () => {
  it("activates keyboard dragging from the focusable handle and cancels without saving", async () => {
    render(<DrawdownEditor planId="plan-1" entries={entries} accounts={accounts} />);
    const handle = screen.getByRole("button", { name: "Reorder 401k" });
    handle.focus();
    expect(handle).toHaveFocus();
    fireEvent.keyDown(handle, { code: "Space", key: " " });
    await waitFor(() => expect(handle).toHaveAttribute("aria-pressed", "true"));
    fireEvent.keyDown(document, { code: "Escape", key: "Escape" });
    await waitFor(() => expect(handle).not.toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("status")).toHaveTextContent("Dragging was cancelled");
    expect(mockUpdateDrawdownOrder).not.toHaveBeenCalled();
  });
  beforeEach(() => {
    mockUpdateDrawdownOrder.mockClear();
  });

  it("renders entries in rank order", () => {
    render(<DrawdownEditor planId="plan-1" entries={entries} accounts={accounts} />);

    expect(screen.getByText("401k")).toBeInTheDocument();
    expect(screen.getByText("Roth IRA")).toBeInTheDocument();

    // Rank numbers visible
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("calls updateDrawdownOrder when adding an entry", () => {
    render(<DrawdownEditor planId="plan-1" entries={entries} accounts={accounts} />);

    // acc-3 (Brokerage) is available since it's not in entries
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "acc-3" } });

    const addButton = screen.getByText("Add Account");
    fireEvent.click(addButton);

    expect(mockUpdateDrawdownOrder).toHaveBeenCalledWith(
      "plan-1",
      expect.arrayContaining([
        expect.objectContaining({ rank: 1, source_account_id: "acc-1" }),
        expect.objectContaining({ rank: 2, source_account_id: "acc-2" }),
        expect.objectContaining({ rank: 3, source_account_id: "acc-3" }),
      ]),
    );
  });

  it("calls updateDrawdownOrder when deleting, and re-ranks", () => {
    render(<DrawdownEditor planId="plan-1" entries={entries} accounts={accounts} />);

    // Delete first entry (401k)
    const deleteButton = screen.getByLabelText("Remove 401k");
    fireEvent.click(deleteButton);

    expect(mockUpdateDrawdownOrder).toHaveBeenCalledWith("plan-1", [
      { rank: 1, source_account_id: "acc-2" },
    ]);
  });

  it("shows empty state when no entries", () => {
    render(<DrawdownEditor planId="plan-1" entries={[]} accounts={accounts} />);

    expect(screen.getByText(/no drawdown accounts configured/i)).toBeInTheDocument();
  });
});
