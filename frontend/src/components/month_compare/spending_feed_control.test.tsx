import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import SpendingFeedControl from "./spending_feed_control";
import { feedState } from "./month_compare_test_data";
import { account } from "@/components/ledger/ledger_test_data";
import { usePlanStore } from "@/stores/plan_store";
import { makePlan } from "@/test_support/plan_builder";
import type { PlanOverrides } from "@/test_support/plan_builder";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), stop: vi.fn() }));
vi.mock("@/api/spending_models", async (original) => ({
  ...(await original<typeof import("@/api/spending_models")>()),
  spendingFeeds: mocks,
}));

const ACCOUNTS = [
  account(),
  account({
    id: "a2",
    name: "Synthetic savings",
    mask: null,
    account_type: "DEPOSITORY",
    subtype: "SAVINGS",
    spending_eligible: false,
    counts_toward_spending: false,
  }),
  account({
    id: "a3",
    name: "Synthetic checking",
    mask: "0003",
    account_type: "DEPOSITORY",
    subtype: "CHECKING",
  }),
];

function plan(overrides: PlanOverrides = {}) {
  usePlanStore.setState({
    plan: makePlan({ id: "plan-1", currency: "USD", expenses: [{ id: "e9" }], ...overrides }),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  plan();
  mocks.get.mockResolvedValue(feedState());
  mocks.put.mockResolvedValue(feedState({ active: true }));
  mocks.stop.mockResolvedValue(undefined);
});

it("turns spending from transactions on after the expenses acknowledgement", async () => {
  const changed = vi.fn();
  render(<SpendingFeedControl accounts={ACCOUNTS} onChanged={changed} />);
  const use = await screen.findByRole("button", { name: "Use for plan spending" });
  expect(screen.queryByRole("checkbox", { name: /Synthetic savings/ })).toBeNull();
  expect(screen.getByRole("checkbox", { name: "Synthetic card ··0001" })).toBeChecked();
  expect(use).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /double-count/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Synthetic checking ··0003" }));
  fireEvent.click(use);
  await waitFor(() =>
    expect(mocks.put).toHaveBeenCalledWith("plan-1", {
      source_ids: ["a1"],
      acknowledge_existing_expenses: true,
      basis: "trailing",
      months: [],
    }),
  );
  await waitFor(() => expect(changed).toHaveBeenCalled());
});

it("keeps a months basis when changing accounts, and turns off", async () => {
  mocks.get.mockResolvedValue(
    feedState({
      active: true,
      source_ids: ["a1", "a2"],
      basis: "months",
      basis_months: ["2026-06"],
      annual_essential: 24000,
      annual_discretionary: null,
      error: "A chosen month is no longer complete.",
    }),
  );
  const changed = vi.fn();
  render(<SpendingFeedControl accounts={ACCOUNTS} onChanged={changed} />);
  expect(await screen.findByText("Jun 2026")).toBeVisible();
  expect(screen.getByText("$24,000")).toBeVisible();
  expect(screen.getByText("—")).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("no longer complete");
  expect(screen.getByRole("checkbox", { name: "Synthetic savings" })).toBeChecked();
  expect(screen.queryByRole("checkbox", { name: /double-count/ })).toBeNull();
  fireEvent.click(screen.getByRole("checkbox", { name: "Synthetic savings" }));
  fireEvent.click(screen.getByRole("button", { name: "Update accounts" }));
  await waitFor(() =>
    expect(mocks.put).toHaveBeenCalledWith("plan-1", {
      source_ids: ["a1"],
      acknowledge_existing_expenses: false,
      basis: "months",
      months: ["2026-06"],
    }),
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Turn off" })).not.toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
  await waitFor(() => expect(mocks.stop).toHaveBeenCalledWith("plan-1"));
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(2));
});

it("shows recent months, refusals and fixed-date plans", async () => {
  plan({ plan_type: "FIXED_DATE", expenses: [] });
  mocks.get.mockResolvedValue(feedState({ active: true, source_ids: ["a1"] }));
  render(<SpendingFeedControl accounts={[]} onChanged={vi.fn()} />);
  expect(await screen.findByText("Recent months")).toBeVisible();
  expect(screen.getByText("Updates Now plans only.")).toBeVisible();
  expect(screen.getByText("No spending accounts yet.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Turn off" })).toBeDisabled();
});

it("reports a failed change and a failed load", async () => {
  plan({ expenses: [] });
  mocks.put.mockRejectedValue(new Error("Account not found."));
  const { unmount } = render(<SpendingFeedControl accounts={ACCOUNTS} onChanged={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Use for plan spending" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Account not found.");
  unmount();
  mocks.get.mockRejectedValue(new Error("Feed unavailable."));
  render(<SpendingFeedControl accounts={ACCOUNTS} onChanged={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Feed unavailable.");
});

it("renders nothing without a plan", () => {
  usePlanStore.setState({ plan: null });
  const { container } = render(<SpendingFeedControl accounts={ACCOUNTS} onChanged={vi.fn()} />);
  expect(container).toBeEmptyDOMElement();
  expect(mocks.get).not.toHaveBeenCalled();
});
