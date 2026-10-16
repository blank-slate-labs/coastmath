import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { ApiStorageAdapter } from "@/storage/adapter";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { BuilderModeContext, IncomeSection } from "./plan_setup";
import SessionStatus from "@/components/session_status";
import type { Income } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";

// The app's own discard dialog, answered by each test.
const confirmDiscard = vi.hoisted(() => vi.fn<(message?: string) => Promise<boolean>>());
vi.mock("@/components/confirm_dialog", () => ({
  confirmDiscard,
  confirmDelete: () => Promise.resolve(true),
}));

const originalAdapter = api.defaults.adapter;
const longName = "UX income " + "A".repeat(250);
let persisted: Income;
beforeEach(() => {
  useSaveStore.setState(useSaveStore.getInitialState());
  persisted = {
    id: "salary",
    plan_id: "p",
    name: "Salary",
    annual_amount: 100000,
    owner: "self",
    growth_rate: 3,
    growth_cap: null,
    growth_cap_inflation_linked: false,
    withholding_percent: null,
    start_milestone_id: null,
    end_milestone_id: null,
    start_month: null,
    end_month: null,
    is_social_security: false,
    is_earned_income: true,
    is_self_employed: false,
    claiming_age: null,
    is_active: true,
  };
  usePlanStore.setState({
    ...usePlanStore.getInitialState(),
    plan: makePlan({
      id: "p",
      name: "Synthetic household",
      birth_year: 1990,
      income_streams: [persisted],
    }),
  });
  const storage = new ApiStorageAdapter();
  storage.runSimulation = vi.fn().mockResolvedValue({ yearly_snapshots: [], metadata: {} });
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
    persisted = { ...persisted, ...body };
    return { ...response, data: persisted };
  };
});
afterEach(() => {
  act(() => usePlanStore.setState({ plan: null, simulation: null }));
  api.defaults.adapter = originalAdapter;
  vi.restoreAllMocks();
});

function open() {
  render(
    <>
      <SessionStatus />
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>
    </>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
}
async function fail() {
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: longName } });
  fireEvent.click(screen.getByText("Save income"));
  await screen.findByRole("alert");
}
it("keeps the rejected draft through Close, Cancel and Escape, then corrects and persists it", async () => {
  const confirm = confirmDiscard.mockReset().mockResolvedValue(false);
  open();
  await fail();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Save income “Salary” in “Synthetic household” was not saved. Name: String should have at most 255 characters",
  );
  expect(screen.getByRole("alert")).toHaveFocus();
  fireEvent.click(screen.getByLabelText("Close"));
  fireEvent.click(screen.getByText("Cancel"));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(confirm).toHaveBeenCalledTimes(3);
  expect(screen.getByLabelText("Name")).toHaveValue(longName);
  expect(persisted.name).toBe("Salary");
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Corrected salary" } });
  fireEvent.click(screen.getByText("Save income"));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(persisted.name).toBe("Corrected salary");
  await waitFor(() => expect(usePlanStore.getState().simulation?.metadata).toEqual({}));
  expect(useSaveStore.getState().failed).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Name")).toHaveValue("Corrected salary");
});

it("explicit discard clears only this rejected save and reopens the saved record", async () => {
  confirmDiscard.mockReset().mockResolvedValue(true);
  open();
  await fail();
  act(() => {
    const store = useSaveStore.getState();
    const attempt = store.begin("put /plans/other/incomes/other");
    store.finish("put /plans/other/incomes/other", false, attempt, {
      message: "Other plan failure",
      rejected: true,
    });
  });
  fireEvent.click(screen.getByLabelText("Close"));
  await waitFor(() =>
    expect(useSaveStore.getState().failed).toEqual(["put /plans/other/incomes/other"]),
  );
  expect(persisted.name).toBe("Salary");
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Name")).toHaveValue("Salary");
});

it("correcting back to the opening value reconciles rejection without an unnecessary write", async () => {
  open();
  await fail();
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Salary" } });
  fireEvent.click(screen.getByText("Save income"));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(useSaveStore.getState().failed).toEqual([]);
  expect(persisted.name).toBe("Salary");
});
