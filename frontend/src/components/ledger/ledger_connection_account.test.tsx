import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ConnectionAccount } from "@/api/ledger_connections";
import { usePlanStore } from "@/stores/plan_store";
import type { Account, Liability } from "@/types/plan";
import LedgerConnectionAccount, { ACCOUNT_KINDS } from "./ledger_connection_account";
import { account } from "./ledger_test_data";
import { makePlan } from "@/test_support/plan_builder";

function synced(overrides: Partial<ConnectionAccount> = {}): ConnectionAccount {
  return {
    ...account({
      provider: "simplefin",
      account_type: "DEPOSITORY",
      subtype: "SAVINGS",
      currency: null,
    }),
    balance: 500,
    balance_updated_at: null,
    revision: 2,
    type_confirmed: true,
    blocked_reason: null,
    suggested_account_type: "savings",
    links: [],
    ...overrides,
  };
}

const planAccounts = [{ id: "pa1", name: "Plan savings", balance: 450 }] as Account[];
const planDebts = [{ id: "pd1", name: "Plan mortgage", principal_balance: 1000 }] as Liability[];

beforeEach(() => {
  usePlanStore.setState({ plan: makePlan({ id: "plan-1", client_id: "c1" }) });
});

function show(
  item: ConnectionAccount,
  extra: Partial<Parameters<typeof LedgerConnectionAccount>[0]> = {},
) {
  const handlers = { onConfirmType: vi.fn(), onLink: vi.fn(), onUnlink: vi.fn() };
  render(
    <ul>
      <LedgerConnectionAccount
        account={item}
        planId="plan-1"
        sharedPlan={false}
        planAccounts={planAccounts}
        planDebts={planDebts}
        busy={false}
        {...handlers}
        {...extra}
      />
    </ul>,
  );
  return handlers;
}

it("preselects a confirmed kind and offers every kind", () => {
  show(synced());
  expect(screen.getByLabelText("Account type for Synthetic card")).toHaveValue("savings");
  expect(screen.getAllByRole("option").length).toBeGreaterThanOrEqual(ACCOUNT_KINDS.length + 1);
  expect(screen.queryByRole("button", { name: "Confirm type" })).toBeNull();
});

it("falls back to the type when the subtype has no preset", () => {
  show(synced({ account_type: "INVESTMENT", subtype: "PLAN_529" }));
  expect(screen.getByLabelText("Account type for Synthetic card")).toHaveValue("brokerage");
  show(synced({ id: "x", name: "Odd", account_type: "UNKNOWN_KIND", subtype: null }));
  expect(screen.getByLabelText("Account type for Odd")).toHaveValue("");
});

it("shows why a balance cannot link", () => {
  show(synced({ blocked_reason: "Only USD balances can be used.", balance: null }));
  expect(screen.getByText("Only USD balances can be used.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Link balance" })).toBeNull();
});

it("links a debt to an existing debt after review", () => {
  const handlers = show(synced({ account_type: "LOAN", subtype: "MORTGAGE", balance: 990 }));
  fireEvent.click(screen.getByRole("button", { name: "Link balance" }));
  expect(screen.getByRole("button", { name: "Link" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Planning record"), { target: { value: "pd1" } });
  expect(screen.getByText(/→/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Link" }));
  expect(handlers.onLink).toHaveBeenCalledWith(expect.objectContaining({ id: "a1" }), {
    plan_id: "plan-1",
    source_revision: 2,
    expected_balance: 1000,
    acknowledge_shared_accounts: false,
    liability_id: "pd1",
  });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Link balance" })).toBeInTheDocument();
});

it("asks to confirm a shared household account", () => {
  const handlers = show(synced(), { sharedPlan: true });
  fireEvent.click(screen.getByRole("button", { name: "Link balance" }));
  fireEvent.change(screen.getByLabelText("Planning record"), { target: { value: "pa1" } });
  expect(screen.getByRole("button", { name: "Link" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Update this account in every household plan" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Link" }));
  expect(handlers.onLink).toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({
      account_id: "pa1",
      acknowledge_shared_accounts: true,
      expected_balance: 450,
    }),
  );
});

it("names a missing planning record and an unnamed link target", () => {
  show(synced({ balance: null }), { planAccounts: [] });
  fireEvent.click(screen.getByRole("button", { name: "Link balance" }));
  expect(screen.getByText("No accounts in this plan yet.")).toBeInTheDocument();
  show(
    synced({
      id: "s9",
      name: "Linked elsewhere",
      links: [
        {
          id: "l9",
          source_id: "s9",
          plan_id: "plan-1",
          account_id: "gone",
          liability_id: null,
          last_applied_balance: 1,
          error: null,
        },
      ],
    }),
  );
  expect(screen.getByText("Balance updates a planning record.")).toBeInTheDocument();
});

it("creates a new account from the synced balance after the duplicate check", () => {
  const handlers = show(synced());
  fireEvent.click(screen.getByRole("button", { name: "Link balance" }));
  fireEvent.change(screen.getByLabelText("Planning record"), { target: { value: "new" } });
  const form = screen.getByRole("group", { name: "New account" });
  expect(form).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "This account isn’t already in the plan" }));
  expect(form).not.toBeDisabled();
  expect(within(form).getByRole("textbox", { name: "Name" })).toHaveValue("Synthetic card");
  // A prefilled new record is added, not updated.
  fireEvent.click(within(form).getByRole("button", { name: "Add Account" }));
  expect(handlers.onLink).toHaveBeenCalledWith(
    expect.objectContaining({ id: "a1" }),
    expect.objectContaining({
      plan_id: "plan-1",
      source_revision: 2,
      acknowledge_duplicate_risk: true,
      acknowledge_shared_accounts: false,
      new_account: expect.objectContaining({
        name: "Synthetic card",
        account_type: "savings",
        balance: 500,
      }),
    }),
  );
  expect(handlers.onLink.mock.calls[0][1]).not.toHaveProperty("expected_balance");
  fireEvent.click(within(form).getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Link balance" })).toBeInTheDocument();
});

it("requires cost basis for a new taxable account and keeps the draft", () => {
  const handlers = show(
    synced({
      account_type: "INVESTMENT",
      subtype: "BROKERAGE",
      suggested_account_type: "taxable_brokerage",
    }),
    { planAccounts: [] },
  );
  fireEvent.click(screen.getByRole("button", { name: "Link balance" }));
  fireEvent.change(screen.getByLabelText("Planning record"), { target: { value: "new" } });
  expect(screen.queryByRole("checkbox", { name: /already in the plan/ })).toBeNull();
  const form = screen.getByRole("group", { name: "New account" });
  fireEvent.change(within(form).getByRole("textbox", { name: "Name" }), {
    target: { value: "Edited name" },
  });
  fireEvent.click(within(form).getByRole("button", { name: /Account$/ }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Enter the cost basis for a taxable account.",
  );
  expect(handlers.onLink).not.toHaveBeenCalled();
  expect(within(form).getByRole("textbox", { name: "Name" })).toHaveValue("Edited name");
  fireEvent.change(within(form).getByLabelText("Cost basis"), { target: { value: "300" } });
  fireEvent.click(within(form).getByRole("button", { name: /Account$/ }));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(handlers.onLink).toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({
      new_account: expect.objectContaining({
        account_type: "taxable_brokerage",
        cost_basis: 300,
        balance: 500,
      }),
    }),
  );
});

it("creates a new debt with the debt editor's inputs", () => {
  const handlers = show(
    synced({
      account_type: "LOAN",
      subtype: "MORTGAGE",
      balance: 990,
      suggested_account_type: null,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Link balance" }));
  fireEvent.change(screen.getByLabelText("Planning record"), { target: { value: "new" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "This debt isn’t already in the plan" }));
  const form = screen.getByRole("group", { name: "New debt" });
  fireEvent.change(within(form).getByLabelText(/^Name/), { target: { value: "Synced mortgage" } });
  fireEvent.change(within(form).getByLabelText(/Interest rate/i), { target: { value: "0.05" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save loan or debt" }));
  expect(handlers.onLink).toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({
      acknowledge_duplicate_risk: true,
      new_liability: expect.objectContaining({ name: "Synced mortgage", principal_balance: 990 }),
    }),
  );
});

it("asks for the shared-household acknowledgement before creating an account", () => {
  show(synced(), { sharedPlan: true, planAccounts: [] });
  fireEvent.click(screen.getByRole("button", { name: "Link balance" }));
  fireEvent.change(screen.getByLabelText("Planning record"), { target: { value: "new" } });
  expect(screen.getByRole("group", { name: "New account" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Update this account in every household plan" }),
  );
  expect(screen.getByRole("group", { name: "New account" })).not.toBeDisabled();
});
