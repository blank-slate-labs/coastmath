import { act, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AccountsSection, BuilderModeContext } from "@/pages/plan_setup";
import { usePlanStore } from "@/stores/plan_store";
import type { Account } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));
const adapter = makeAdapter({ listAccounts: mocks.list });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

it("does not offer an empty household while accounts are loading", async () => {
  let resolve!: (accounts: Account[]) => void;
  mocks.list.mockReturnValue(
    new Promise<Account[]>((r) => {
      resolve = r;
    }),
  );
  usePlanStore.setState({ plan: null, accountsRevision: 0 });
  render(
    <BuilderModeContext.Provider value="sheet">
      <AccountsSection />
    </BuilderModeContext.Provider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Loading accounts");
  expect(screen.queryByText(/No accounts yet/)).not.toBeInTheDocument();
  expect(screen.queryByText("0 items")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Add account/ })).not.toBeInTheDocument();
  await act(async () => resolve([]));
  expect(screen.getByText(/No accounts yet/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Add account/ })).toBeEnabled();
});

it("reports a failed account load instead of claiming there are no accounts", async () => {
  mocks.list.mockRejectedValue(new Error("offline"));
  render(
    <BuilderModeContext.Provider value="sheet">
      <AccountsSection />
    </BuilderModeContext.Provider>,
  );
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load accounts"),
  );
  expect(screen.queryByText(/No accounts yet/)).not.toBeInTheDocument();
});

const ownedAccounts = [
  { id: "a1", name: "Mine", balance: 1000, account_type: "savings", owner: "self" },
  { id: "a2", name: "Theirs", balance: 2000, account_type: "savings", owner: "spouse" },
  { id: "a3", name: "Shared", balance: 3000, account_type: "brokerage", owner: "joint" },
] as Account[];

it("names account owners with person labels, never raw owner values", async () => {
  mocks.list.mockResolvedValue(ownedAccounts);
  usePlanStore.setState({
    plan: makePlan({ id: "p", spouse: { name: "Sam", birth_year: 1982 } }),
    accountsRevision: 0,
  });
  const { container } = render(
    <BuilderModeContext.Provider value="sheet">
      <AccountsSection />
    </BuilderModeContext.Provider>,
  );
  await screen.findByText("Mine");
  expect(container).toHaveTextContent("(Primary person)");
  expect(container).toHaveTextContent("(Partner)");
  expect(container).toHaveTextContent("(Joint)");
  expect(container.textContent).not.toMatch(/\((self|spouse|joint)\)/);
});

it("omits the primary person's suffix on a single-person plan", async () => {
  mocks.list.mockResolvedValue([ownedAccounts[0]]);
  usePlanStore.setState({ plan: makePlan({ id: "p" }), accountsRevision: 0 });
  const { container } = render(
    <BuilderModeContext.Provider value="sheet">
      <AccountsSection />
    </BuilderModeContext.Provider>,
  );
  await screen.findByText("Mine");
  expect(container.textContent).not.toMatch(/\((self|Primary person)\)/);
});
