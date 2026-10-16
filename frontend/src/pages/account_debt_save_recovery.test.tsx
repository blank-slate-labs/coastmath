import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { ApiStorageAdapter } from "@/storage/adapter";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { AccountsSection, BuilderModeContext } from "./plan_setup";
import AssetsDebtPanel from "@/components/assets_debt_panel";
import SessionStatus from "@/components/session_status";
import type { Account, PlanData } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";

// The app's own discard dialog, answered by each test.
const confirmDiscard = vi.hoisted(() => vi.fn<(message?: string) => Promise<boolean>>());
vi.mock("@/components/confirm_dialog", () => ({
  confirmDiscard,
  confirmDelete: () => Promise.resolve(true),
}));

const holder = vi.hoisted(() => ({ adapter: null as unknown }));
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => holder.adapter),
);
const originalAdapter = api.defaults.adapter;
let account: Account;
let plan: PlanData;
const accountName = "UX account " + "A".repeat(250);
const debtName = "UX debt " + "B".repeat(250);
beforeEach(() => {
  useSaveStore.setState(useSaveStore.getInitialState());
  account = {
    id: "a",
    name: "Emergency Fund",
    balance: 20000,
    account_type: "savings",
    owner: "self",
  } as Account;
  plan = makePlan({ id: "p", name: "Synthetic household" });
  usePlanStore.setState({ ...usePlanStore.getInitialState(), plan });
  const storage = new ApiStorageAdapter();
  holder.adapter = storage;
  setStorageAdapter(storage);
  api.defaults.adapter = async (config) => {
    const body = JSON.parse(config.data ?? "{}");
    const response = {
      config,
      status: 200,
      statusText: "OK",
      headers: new AxiosHeaders(),
      data: {},
    };
    if (body.name?.length > 255)
      throw new AxiosError("Rejected", "ERR_BAD_REQUEST", config, undefined, {
        ...response,
        status: 422,
        data: {
          error: {
            message: "Validation failed",
            details: [{ field: "name", reason: "String should have at most 255 characters" }],
          },
        },
      });
    if (config.method === "get")
      return { ...response, data: config.url?.endsWith("accounts") ? [account] : plan };
    if (config.url?.includes("accounts")) {
      account = { ...account, ...body };
      return { ...response, data: account };
    }
    if (config.url?.endsWith("liabilities")) {
      const debt = { id: "d", ...body };
      plan = { ...plan, liabilities: [debt] };
      return { ...response, data: debt };
    }
    return response;
  };
});
afterEach(() => {
  api.defaults.adapter = originalAdapter;
  vi.restoreAllMocks();
});
async function openAccount() {
  render(
    <>
      <SessionStatus />
      <BuilderModeContext.Provider value="sheet">
        <AccountsSection />
      </BuilderModeContext.Provider>
    </>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
}
async function failAccount() {
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: accountName } });
  fireEvent.click(screen.getByRole("button", { name: "Update Account" }));
  await screen.findByRole("alert");
}
it("account rejection is actionable, retains the draft across attempted exits, and corrects persisted data", async () => {
  const confirm = confirmDiscard.mockReset().mockResolvedValue(false);
  await openAccount();
  await failAccount();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Name: String should have at most 255 characters",
  );
  expect(screen.getByRole("alert")).toHaveFocus();
  expect(useSaveStore.getState().failed).toEqual(["put /plans/p/accounts/a"]);
  fireEvent.keyDown(document, { key: "Escape" });
  fireEvent.click(screen.getByLabelText("Close"));
  fireEvent.click(screen.getByText("Cancel"));
  expect(confirm).toHaveBeenCalledTimes(3);
  expect(screen.getByLabelText("Name")).toHaveValue(accountName);
  expect(account.name).toBe("Emergency Fund");
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "UX account control" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Account" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(account).toMatchObject({
    name: "UX account control",
    balance: 20000,
    account_type: "savings",
    owner: "self",
  });
  expect(useSaveStore.getState().failed).toEqual([]);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Name")).toHaveValue("UX account control");
});
it("account explicit discard acknowledges only that rejected request", async () => {
  confirmDiscard.mockReset().mockResolvedValue(true);
  await openAccount();
  await failAccount();
  act(() => {
    const s = useSaveStore.getState();
    s.finish("post /plans/other/liabilities", false, s.begin("post /plans/other/liabilities"), {
      message: "Other debt failure",
      rejected: true,
    });
  });
  fireEvent.click(screen.getByLabelText("Close"));
  await waitFor(() =>
    expect(useSaveStore.getState().failed).toEqual(["post /plans/other/liabilities"]),
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Name")).toHaveValue("Emergency Fund");
});
it("debt rejection exposes the reason, preserves all inputs, and corrects without duplicate creation", async () => {
  const confirm = confirmDiscard.mockReset().mockResolvedValue(false);
  render(
    <>
      <SessionStatus />
      <AssetsDebtPanel plan={plan} />
    </>,
  );
  await waitFor(() => expect(screen.getByText("Add loan or debt")).toBeEnabled());
  fireEvent.click(screen.getByText("Add loan or debt"));
  for (const [label, value] of [
    ["Name", debtName],
    ["Principal balance ($)", "12000"],
    ["Interest rate (% per year)", "5"],
    ["Term (months)", "60"],
    ["Monthly payment ($)", "230"],
  ]) {
    fireEvent.change(screen.getByLabelText(label, { exact: false }), { target: { value } });
  }
  fireEvent.click(screen.getByText("Save loan or debt"));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Name: String should have at most 255 characters",
    ),
  );
  expect(screen.getByRole("alert")).toHaveFocus();
  fireEvent.click(screen.getByLabelText("Close"));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(confirm).toHaveBeenCalledTimes(2);
  expect(screen.getByLabelText("Name")).toHaveValue(debtName);
  expect(screen.getByLabelText("Principal balance ($)")).toHaveValue("12,000");
  expect(plan.liabilities).toEqual([]);
  await act(async () => {
    await api.put("/plans/p/accounts/a", { name: "Unrelated control" });
  });
  expect(useSaveStore.getState().failed).toEqual(["post /plans/p/liabilities"]);
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "UX debt control" } });
  fireEvent.click(screen.getByText("Save loan or debt"));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(plan.liabilities).toHaveLength(1);
  expect(plan.liabilities[0]).toMatchObject({
    name: "UX debt control",
    principal_balance: 12000,
    interest_rate: 5,
    term_months: 60,
    monthly_payment: 230,
  });
  expect(useSaveStore.getState().failed).toEqual([]);
});
