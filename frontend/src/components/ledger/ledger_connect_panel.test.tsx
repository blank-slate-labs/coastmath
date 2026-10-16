import type { MockInstance } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ConnectionAccount, LedgerConnection, LedgerProvider } from "@/api/ledger_connections";
import { usePlanStore } from "@/stores/plan_store";
import LedgerConnectPanel from "./ledger_connect_panel";
import { account } from "./ledger_test_data";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const mocks = vi.hoisted(() => ({
  providers: vi.fn(),
  list: vi.fn(),
  connectSimpleFIN: vi.fn(),
  sync: vi.fn(),
  disconnect: vi.fn(),
  link: vi.fn(),
  unlink: vi.fn(),
  updateAccount: vi.fn(),
  listAccounts: vi.fn(),
  listLiabilities: vi.fn(),
  startPlaid: vi.fn(),
}));
const adapter = makeAdapter({
  listAccounts: mocks.listAccounts,
  listLiabilities: mocks.listLiabilities,
});
vi.mock("@/api/ledger_connections", () => ({ ledgerConnections: mocks }));
vi.mock("@/api/ledger", () => ({ ledger: { updateAccount: mocks.updateAccount } }));
vi.mock("./plaid_link", () => ({ startPlaidConnection: mocks.startPlaid }));
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
// A hosting policy that may lock provider linking (the extension seam, not the hosted package).
const access = vi.hoisted(() => {
  class Explained extends Error {}
  return { locked: vi.fn(() => false), explain: vi.fn(), Explained };
});
vi.mock("@/extensions", () => ({
  plannerPath: () => "/",
  extensions: {
    access: {
      locked: access.locked,
      explain: access.explain,
      LockGlyph: () => <span data-testid="lock" />,
      LockedFeature: ({ feature }: { feature: string }) => (
        <div role="group" aria-label={`LockedFeature ${feature}`} />
      ),
    },
    api: { isExplained: (error: unknown) => error instanceof access.Explained },
  },
}));

const SIMPLEFIN: LedgerProvider = {
  key: "simplefin",
  label: "SimpleFIN",
  link_flow: "token",
  capabilities: ["balances", "transactions"],
  offered: true,
  reason: null,
  history_days: 365,
};
const PLAID: LedgerProvider = {
  key: "plaid",
  label: "Plaid",
  link_flow: "widget",
  capabilities: ["balances", "transactions", "webhooks"],
  offered: true,
  reason: null,
  history_days: 730,
};

function synced(overrides: Partial<ConnectionAccount> = {}): ConnectionAccount {
  return {
    ...account({ provider: "simplefin", account_type: "UNCONFIRMED", subtype: null, mask: null }),
    balance: -250,
    balance_updated_at: null,
    revision: 1,
    type_confirmed: false,
    blocked_reason: "Confirm this account's type before using its balance.",
    suggested_account_type: null,
    links: [],
    ...overrides,
  };
}

function connection(overrides: Partial<LedgerConnection> = {}): LedgerConnection {
  return {
    id: "c1",
    provider: "simplefin",
    label: "SimpleFIN",
    institution_name: "Synthetic Bank",
    status: "ACTIVE",
    error: null,
    last_success_at: "2026-10-10T12:00:00Z",
    next_check_at: null,
    created_at: "2026-10-01T00:00:00Z",
    accounts: [synced()],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  access.locked.mockReturnValue(false);
  usePlanStore.setState({ plan: makePlan({ id: "plan-1", client_id: "client-1" }) });
  mocks.providers.mockResolvedValue([SIMPLEFIN]);
  mocks.list.mockResolvedValue([connection()]);
  mocks.listAccounts.mockResolvedValue([{ id: "pa1", name: "Plan checking", balance: 100 }]);
  mocks.listLiabilities.mockResolvedValue([
    { id: "pd1", name: "Plan card", principal_balance: 40 },
  ]);
  for (const fn of [
    mocks.startPlaid,
    mocks.connectSimpleFIN,
    mocks.sync,
    mocks.disconnect,
    mocks.link,
    mocks.unlink,
    mocks.updateAccount,
  ]) {
    fn.mockResolvedValue({});
  }
});

it("renders nothing when no synced provider is offered or connected", async () => {
  mocks.providers.mockResolvedValue([{ ...SIMPLEFIN, offered: false, reason: "Off" }]);
  mocks.list.mockResolvedValue([]);
  const { container } = render(<LedgerConnectPanel onChanged={vi.fn()} />);
  await waitFor(() => expect(mocks.list).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

it("connects with a setup token", async () => {
  mocks.list.mockResolvedValue([]);
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  const input = await screen.findByLabelText("SimpleFIN setup token");
  expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
  fireEvent.change(input, { target: { value: " synthetic-token " } });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() =>
    expect(mocks.connectSimpleFIN).toHaveBeenCalledWith("synthetic-token", undefined),
  );
  await waitFor(() => expect(input).toHaveValue(""));
});

it("marks a refused setup token on its field", async () => {
  mocks.list.mockResolvedValue([]);
  mocks.connectSimpleFIN.mockRejectedValueOnce(new Error("This is not a SimpleFIN setup token."));
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  const input = await screen.findByLabelText("SimpleFIN setup token");
  fireEvent.change(input, { target: { value: "not-a-token" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("This is not a SimpleFIN setup token.");
  expect(alert).toHaveClass("field-error");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(input).toHaveAttribute("aria-describedby", alert.id);
  expect(input).toHaveAccessibleDescription("This is not a SimpleFIN setup token.");
  // Editing the token clears the error.
  fireEvent.change(input, { target: { value: "another-token" } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(input).not.toHaveAttribute("aria-invalid");
  expect(input).not.toHaveAttribute("aria-describedby");
});

it("shows status, syncs, reconnects and surfaces errors", async () => {
  mocks.list.mockResolvedValue([
    connection({ error: "Synthetic Bank needs attention at your bridge." }),
    connection({
      id: "c2",
      status: "RECONNECT_REQUIRED",
      institution_name: "Other Bank",
      accounts: [],
    }),
  ]);
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  const first = await screen.findByRole("article", { name: "SimpleFIN: Synthetic Bank" });
  expect(within(first).getByText(/SimpleFIN · Synced/)).toBeInTheDocument();
  expect(
    within(first).getByText("Synthetic Bank needs attention at your bridge."),
  ).toBeInTheDocument();
  fireEvent.click(within(first).getByRole("button", { name: "Sync now" }));
  await waitFor(() => expect(mocks.sync).toHaveBeenCalledWith("c1"));
  const second = screen.getByRole("article", { name: "SimpleFIN: Other Bank" });
  expect(within(second).getByText("SimpleFIN · Reconnect needed")).toBeInTheDocument();
  expect(within(second).queryByRole("button", { name: "Sync now" })).toBeNull();
  fireEvent.click(within(second).getByRole("button", { name: "Reconnect" }));
  const input = screen.getByLabelText("New setup token for Other Bank");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByLabelText("SimpleFIN setup token")).toBeInTheDocument();
  fireEvent.click(within(second).getByRole("button", { name: "Reconnect" }));
  const replacement = screen.getByLabelText("New setup token for Other Bank");
  fireEvent.change(replacement, { target: { value: "new-token" } });
  fireEvent.click(within(replacement.closest("form")!).getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(mocks.connectSimpleFIN).toHaveBeenCalledWith("new-token", "c2"));
  expect(input).toBeTruthy();
  mocks.sync.mockRejectedValueOnce(
    new Error("This connection synced moments ago. Try again in a few minutes."),
  );
  fireEvent.click(within(first).getByRole("button", { name: "Sync now" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("synced moments ago");
});

it.each([
  ["NEW", "Waiting for first sync"],
  ["SYNCING", "Syncing"],
  ["RETRYING", "Retrying"],
  ["PAYMENT_REQUIRED", "Payment needed at your bridge"],
] as const)("labels %s connections", async (status, label) => {
  mocks.list.mockResolvedValue([connection({ status, last_success_at: null })]);
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  expect(await screen.findByText(`SimpleFIN · ${label}`)).toBeInTheDocument();
});

it("labels a success without a time", async () => {
  mocks.list.mockResolvedValue([connection({ last_success_at: null })]);
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  expect(await screen.findByText("SimpleFIN · Synced")).toBeInTheDocument();
});

function pollTick(spy: MockInstance<typeof window.setInterval>): () => void {
  const call = spy.mock.calls.find((args) => args[1] === 15000);
  return call![0] as () => void;
}

it("polls while a sync is pending and refreshes the section once it finishes", async () => {
  const intervals = vi.spyOn(window, "setInterval");
  mocks.list
    .mockResolvedValueOnce([connection({ status: "NEW" })])
    .mockResolvedValue([connection()]);
  const onChanged = vi.fn();
  render(<LedgerConnectPanel onChanged={onChanged} />);
  expect(await screen.findByText("SimpleFIN · Waiting for first sync")).toBeInTheDocument();
  expect(onChanged).not.toHaveBeenCalled();
  await act(async () => {
    pollTick(intervals)();
  });
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(mocks.list).toHaveBeenCalledTimes(2);
  intervals.mockRestore();
});

it("reports a failed poll", async () => {
  const intervals = vi.spyOn(window, "setInterval");
  mocks.list
    .mockResolvedValueOnce([connection({ status: "SYNCING" })])
    .mockRejectedValue(new Error("Offline"));
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  expect(await screen.findByText("SimpleFIN · Syncing")).toBeInTheDocument();
  await act(async () => {
    pollTick(intervals)();
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
  intervals.mockRestore();
});

it("disconnects with the remove-data choice", async () => {
  const onChanged = vi.fn();
  render(<LedgerConnectPanel onChanged={onChanged} />);
  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  const again = await screen.findByRole("dialog");
  fireEvent.click(
    within(again).getByRole("checkbox", {
      name: "Also delete these accounts and their transactions",
    }),
  );
  expect(within(again).getByText("Deleted transactions cannot be restored.")).toBeInTheDocument();
  fireEvent.click(within(again).getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(mocks.disconnect).toHaveBeenCalledWith("c1", true));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});

it("confirms a type, links and unlinks balances", async () => {
  const onChanged = vi.fn();
  mocks.list.mockResolvedValue([
    connection({
      accounts: [
        synced(),
        synced({
          id: "s2",
          name: "Synced checking",
          account_type: "DEPOSITORY",
          subtype: "CHECKING",
          type_confirmed: true,
          blocked_reason: null,
          balance: 120,
          revision: 3,
        }),
        synced({
          id: "s3",
          name: "Synced card",
          account_type: "CREDIT",
          subtype: "CREDIT_CARD",
          type_confirmed: true,
          blocked_reason: null,
          balance: 60,
          links: [
            {
              id: "l1",
              source_id: "s3",
              plan_id: "plan-1",
              account_id: null,
              liability_id: "pd1",
              last_applied_balance: 60,
              error: "Synthetic link problem",
            },
          ],
        }),
      ],
    }),
  ]);
  render(<LedgerConnectPanel onChanged={onChanged} />);
  fireEvent.change(await screen.findByLabelText("Account type for Synthetic card"), {
    target: { value: "credit_card" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirm type" }));
  await waitFor(() =>
    expect(mocks.updateAccount).toHaveBeenCalledWith("a1", {
      account_type: "CREDIT",
      subtype: "CREDIT_CARD",
    }),
  );
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Link balance" }));
  fireEvent.change(screen.getByLabelText("Planning record"), { target: { value: "pa1" } });
  fireEvent.click(screen.getByRole("button", { name: "Link" }));
  await waitFor(() =>
    expect(mocks.link).toHaveBeenCalledWith("s2", {
      plan_id: "plan-1",
      source_revision: 3,
      expected_balance: 100,
      acknowledge_shared_accounts: false,
      account_id: "pa1",
    }),
  );
  expect(screen.getByText("Balance updates Plan card.")).toBeInTheDocument();
  expect(screen.getByText("Synthetic link problem")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Unlink balance" }));
  await waitFor(() => expect(mocks.unlink).toHaveBeenCalledWith("l1"));
});

it("connects with Plaid when only Plaid is offered", async () => {
  mocks.providers.mockResolvedValue([{ ...SIMPLEFIN, offered: false, reason: "Off" }, PLAID]);
  mocks.list.mockResolvedValue([]);
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Connect with Plaid" }));
  await waitFor(() => expect(mocks.startPlaid).toHaveBeenCalledWith());
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  expect(screen.queryByLabelText("SimpleFIN setup token")).toBeNull();
  mocks.startPlaid.mockRejectedValueOnce(new Error("Plaid Link did not load. Try again."));
  fireEvent.click(screen.getByRole("button", { name: "Connect with Plaid" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Plaid Link did not load.");
});

it("reconnects a Plaid connection through update mode", async () => {
  mocks.providers.mockResolvedValue([PLAID]);
  const plaid = { provider: "plaid", label: "Plaid", accounts: [] };
  mocks.list.mockResolvedValue([
    connection({ ...plaid, id: "p1", status: "RECONNECT_REQUIRED" }),
    connection({ ...plaid, id: "p2", institution_name: "Other Bank" }),
  ]);
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  const broken = await screen.findByRole("article", { name: "Plaid: Synthetic Bank" });
  const healthy = screen.getByRole("article", { name: "Plaid: Other Bank" });
  expect(within(healthy).queryByRole("button", { name: "Reconnect" })).toBeNull();
  fireEvent.click(within(broken).getByRole("button", { name: "Reconnect" }));
  await waitFor(() => expect(mocks.startPlaid).toHaveBeenCalledWith("p1"));
});

describe("when the access policy locks provider linking", () => {
  beforeEach(() => {
    access.locked.mockReturnValue(true);
  });

  it("shows the access prompt instead of starting a connection", async () => {
    mocks.providers.mockResolvedValue([SIMPLEFIN, PLAID]);
    mocks.list.mockResolvedValue([]);
    render(<LedgerConnectPanel onChanged={vi.fn()} />);
    expect(
      await screen.findByRole("group", { name: "LockedFeature bank_linking" }),
    ).toBeInTheDocument();
    expect(access.locked).toHaveBeenCalledWith(null, "bank_linking");
    expect(screen.queryByLabelText("SimpleFIN setup token")).toBeNull();
    expect(screen.queryByRole("button", { name: "Connect with Plaid" })).toBeNull();
  });

  it("explains sync and reconnect instead of calling them; disconnect stays available", async () => {
    mocks.providers.mockResolvedValue([SIMPLEFIN, PLAID]);
    mocks.list.mockResolvedValue([
      connection(),
      connection({
        id: "p1",
        provider: "plaid",
        label: "Plaid",
        status: "RECONNECT_REQUIRED",
        accounts: [],
      }),
    ]);
    render(<LedgerConnectPanel onChanged={vi.fn()} />);
    const simplefin = await screen.findByRole("article", { name: "SimpleFIN: Synthetic Bank" });
    const plaid = screen.getByRole("article", { name: "Plaid: Synthetic Bank" });
    fireEvent.click(within(simplefin).getByRole("button", { name: "Sync now" }));
    fireEvent.click(within(simplefin).getByRole("button", { name: "Reconnect" }));
    fireEvent.click(within(plaid).getByRole("button", { name: "Reconnect" }));
    expect(access.explain).toHaveBeenCalledTimes(3);
    expect(access.explain).toHaveBeenCalledWith("bank_linking");
    expect(within(simplefin).getAllByTestId("lock")).toHaveLength(2);
    expect(mocks.sync).not.toHaveBeenCalled();
    expect(mocks.startPlaid).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("New setup token for Synthetic Bank")).toBeNull();
    fireEvent.click(within(simplefin).getByRole("button", { name: "Disconnect" }));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Disconnect" }),
    );
    await waitFor(() => expect(mocks.disconnect).toHaveBeenCalledWith("c1", false));
  });
});

it("leaves an explained refusal to its prompt instead of repeating it", async () => {
  mocks.sync.mockRejectedValueOnce(new access.Explained("Connecting accounts is not available."));
  render(<LedgerConnectPanel onChanged={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));
  await waitFor(() => expect(mocks.sync).toHaveBeenCalledWith("c1"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Sync now" })).toBeEnabled());
  expect(screen.queryByRole("alert")).toBeNull();
});
