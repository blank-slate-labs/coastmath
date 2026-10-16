import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import TransactionsSection from "./transactions_section";
import { account, CATEGORIES, month, rule } from "./ledger_test_data";
import { usePlanStore } from "@/stores/plan_store";
import { makePlan } from "@/test_support/plan_builder";

const mocks = vi.hoisted(() => ({
  categories: vi.fn(),
  accounts: vi.fn(),
  rules: vi.fn(),
  months: vi.fn(),
  transactions: vi.fn(),
  updateAccount: vi.fn(),
  updateRule: vi.fn(),
  deleteRule: vi.fn(),
  updateTransaction: vi.fn(),
  loadPlan: vi.fn(),
  sample: false,
}));
vi.mock("@/api/ledger", () => ({ ledger: mocks }));
const suggestionMocks = vi.hoisted(() => ({ status: vi.fn(), run: vi.fn() }));
vi.mock("@/api/ledger_suggestions", () => ({ ledgerSuggestions: suggestionMocks }));
const importMocks = vi.hoisted(() => ({ list: vi.fn(), deleteAccount: vi.fn() }));
vi.mock("@/api/ledger_imports", () => ({ ledgerImports: importMocks, fileToBase64: vi.fn() }));
vi.mock("@/api/ledger_connections", () => ({
  ledgerConnections: {
    providers: vi.fn().mockResolvedValue([]),
    list: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(null, {
    sample: () => mocks.sample,
  }),
);
// The plan's feed control (month_compare/spending_feed_control.tsx) has its own tests.
vi.mock("@/components/month_compare/spending_feed_control", () => ({ default: () => null }));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.sample = false;
  usePlanStore.setState({ plan: makePlan({ id: "plan-1" }), loadPlan: mocks.loadPlan });
  mocks.categories.mockResolvedValue(CATEGORIES);
  mocks.accounts.mockResolvedValue([
    account(),
    account({ id: "a2", name: "Synthetic copy", mask: null }),
  ]);
  mocks.rules.mockResolvedValue([rule()]);
  mocks.months.mockResolvedValue({
    currency: "USD",
    months: [month()],
    sources: [
      {
        id: "a1",
        provider: "file",
        name: "Synthetic card",
        coverage: [],
        settled: [],
        waiting: false,
      },
    ],
    duplicates: [{ source_ids: ["a1", "a2"], matched: 9, compared: 12 }],
  });
  mocks.transactions.mockResolvedValue({ transactions: [], total: 0 });
  suggestionMocks.status.mockResolvedValue({
    offered: false,
    running: false,
    pending: null,
    last_run: null,
  });
  for (const fn of [mocks.updateAccount, mocks.updateRule, mocks.deleteRule])
    fn.mockResolvedValue({});
  importMocks.list.mockResolvedValue([]);
  importMocks.deleteAccount.mockResolvedValue(undefined);
});

it("loads the plan's months and every panel", async () => {
  render(<TransactionsSection />);
  expect(await screen.findByText("Synthetic card ··0001")).toBeInTheDocument();
  expect(mocks.months).toHaveBeenCalledWith({ plan_id: "plan-1" });
  expect(
    screen.getByText(/Synthetic card and An account share 9 of 12 transactions/),
  ).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Spending by month" })).toBeInTheDocument();
  // The review loads after the section, so its empty state can land a render later.
  expect(await screen.findByText("No transactions yet.")).toBeInTheDocument();
});

it("saves account and rule changes, then reloads the plan", async () => {
  render(<TransactionsSection />);
  await screen.findByText("Synthetic card ··0001");
  fireEvent.click(screen.getAllByRole("checkbox", { name: "Count spending" })[0]);
  await waitFor(() =>
    expect(mocks.updateAccount).toHaveBeenCalledWith("a1", { include_in_spending: false }),
  );
  await waitFor(() => expect(mocks.loadPlan).toHaveBeenCalledWith("plan-1"));
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "Rule category" })).not.toBeDisabled(),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Rule category" }), {
    target: { value: "dining" },
  });
  await waitFor(() => expect(mocks.updateRule).toHaveBeenCalledWith("r1", { category: "dining" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Delete" })).not.toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(mocks.deleteRule).toHaveBeenCalledWith("r1"));
});

it("restores the default when a toggle matches eligibility", async () => {
  mocks.accounts.mockResolvedValue([
    account({ counts_toward_spending: false, include_in_spending: false }),
  ]);
  render(<TransactionsSection />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "Count spending" }));
  await waitFor(() =>
    expect(mocks.updateAccount).toHaveBeenCalledWith("a1", { include_in_spending: null }),
  );
});

it("reports load and save failures", async () => {
  mocks.updateAccount.mockRejectedValueOnce(
    new Error("Transactions are unavailable in this release."),
  );
  render(<TransactionsSection />);
  fireEvent.click((await screen.findAllByRole("checkbox", { name: "Count spending" }))[0]);
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable in this release");
});

it("shows a load failure", async () => {
  mocks.categories.mockRejectedValueOnce(new Error("Offline"));
  render(<TransactionsSection />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
});

it("renders nothing for the read-only sample or without a plan", () => {
  mocks.sample = true;
  const { container, rerender } = render(<TransactionsSection />);
  expect(container).toBeEmptyDOMElement();
  mocks.sample = false;
  act(() => {
    usePlanStore.setState({ plan: null } as never);
  });
  rerender(<TransactionsSection />);
  expect(container).toBeEmptyDOMElement();
  expect(mocks.categories).not.toHaveBeenCalled();
});

it("renders the import panel", async () => {
  render(<TransactionsSection />);
  expect(await screen.findByRole("region", { name: "Import transactions" })).toBeInTheDocument();
});

it("removes a file account, then reloads the section, the import lists and the plan", async () => {
  render(<TransactionsSection />);
  await screen.findByText("Synthetic card ··0001");
  await waitFor(() => expect(importMocks.list).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Remove Synthetic card" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove account" }));
  await waitFor(() => expect(importMocks.deleteAccount).toHaveBeenCalledWith("a1"));
  await waitFor(() => expect(mocks.loadPlan).toHaveBeenCalledWith("plan-1"));
  await waitFor(() => expect(mocks.accounts.mock.calls.length).toBeGreaterThanOrEqual(3));
  await waitFor(() => expect(importMocks.list).toHaveBeenCalledTimes(2));
});

it("shows a refused removal", async () => {
  importMocks.deleteAccount.mockRejectedValueOnce(new Error("Account not found."));
  render(<TransactionsSection />);
  await screen.findByText("Synthetic card ··0001");
  fireEvent.click(screen.getByRole("button", { name: "Remove Synthetic card" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove account" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Account not found.");
  expect(mocks.loadPlan).not.toHaveBeenCalled();
});
