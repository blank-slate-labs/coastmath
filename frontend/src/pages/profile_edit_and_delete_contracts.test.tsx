import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BuilderModeContext, IncomeSection, PlanHeader, PLAN_SECTIONS } from "./plan_setup";
import EditSheet from "@/components/edit_sheet";
import HealthcareForm from "@/components/healthcare_form";
import EstateSettingsForm from "@/components/estate_settings_form";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import type { PlanCreate, PlanData } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

// The app's own discard dialog, answered by each test.
const confirmDiscard = vi.hoisted(() => vi.fn<(message?: string) => Promise<boolean>>());
vi.mock("@/components/confirm_dialog", () => ({
  confirmDiscard,
  confirmDelete: () => Promise.resolve(true),
}));

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
let persisted: PlanData;
beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  persisted = makePlan({
    id: "p",
    user_id: "u",
    name: "Original",
    birth_year: 1990,
    state_code: "TX",
    life_expectancy: 90,
    healthcare_settings: null,
  });
  usePlanStore.setState({ ...usePlanStore.getInitialState(), plan: persisted });
  setStorageAdapter(adapter);
  adapter.listAccounts.mockResolvedValue([]);
  adapter.fetchPlan.mockImplementation(async () => persisted);
  adapter.updatePlan.mockImplementation(async (_id: string, data: Partial<PlanCreate>) => {
    persisted = { ...persisted, ...data } as PlanData;
    return persisted;
  });
});
async function header() {
  await act(async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <PlanHeader />
      </BuilderModeContext.Provider>,
    );
  });
}

it("a stale tab's state edit and untouched blurs preserve newer saved name and birth year", async () => {
  await header();
  persisted = { ...persisted, name: "Saved in tab B", birth_year: 1985 };
  fireEvent.blur(screen.getByLabelText("Plan name"));
  fireEvent.blur(screen.getByLabelText("Birth year"));
  expect(adapter.updatePlan).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("State"), { target: { value: "FL" } });
  await waitFor(() => expect(screen.getByLabelText("Birth year")).toHaveValue(1985));
  expect(adapter.updatePlan).toHaveBeenCalledExactlyOnceWith("p", { state_code: "FL" });
  expect(persisted).toMatchObject({ name: "Saved in tab B", birth_year: 1985, state_code: "FL" });
});

it("a delayed name response preserves the focused birth-year draft and then saves it", async () => {
  let finish!: (value: PlanData) => void;
  adapter.updatePlan.mockImplementationOnce((_id, data) => {
    persisted = { ...persisted, ...data } as PlanData;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  await header();
  fireEvent.change(screen.getByLabelText("Plan name"), { target: { value: "Renamed" } });
  fireEvent.blur(screen.getByLabelText("Plan name"));
  const birth = screen.getByLabelText("Birth year");
  birth.focus();
  fireEvent.change(birth, { target: { value: "1985" } });
  await act(async () => finish(persisted));
  expect(birth).toHaveFocus();
  expect(birth).toHaveValue(1985);
  fireEvent.blur(birth);
  await waitFor(() => expect(persisted.birth_year).toBe(1985));
  expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", { birth_year: 1985 });
});

it("serializes rapid saves and preserves newer edits to the same field", async () => {
  let finish!: (value: PlanData) => void;
  adapter.updatePlan.mockImplementationOnce((_id, data) => {
    persisted = { ...persisted, ...data } as PlanData;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  await header();
  const name = screen.getByLabelText("Plan name");
  fireEvent.change(name, { target: { value: "First" } });
  fireEvent.blur(name);
  fireEvent.change(name, { target: { value: "Latest" } });
  fireEvent.blur(name);
  expect(adapter.updatePlan).toHaveBeenCalledTimes(1);
  await act(async () => finish(persisted));
  expect(name).toHaveValue("Latest");
  expect(persisted.name).toBe("Latest");
  expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", { name: "Latest" });
});

it("retains a failed profile draft through refresh and retries on blur", async () => {
  adapter.updatePlan.mockRejectedValueOnce(new Error("offline"));
  await header();
  const name = screen.getByLabelText("Plan name");
  fireEvent.change(name, { target: { value: "Retry me" } });
  fireEvent.blur(name);
  await waitFor(() => expect(usePlanStore.getState().error).toBeTruthy());
  act(() => usePlanStore.setState({ plan: { ...persisted, state_code: "FL" } }));
  expect(name).toHaveValue("Retry me");
  fireEvent.blur(name);
  await waitFor(() => expect(persisted.name).toBe("Retry me"));
});

it.each(["health", "estate"])(
  "%s status reflects edits, reversions, saves, and failed retries",
  async (kind) => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      kind === "health" ? (
        <HealthcareForm plan={persisted} onSave={save} />
      ) : (
        <EstateSettingsForm plan={persisted} onSave={save} />
      ),
    );
    if (kind === "health") fireEvent.click(screen.getByLabelText("Model health coverage costs"));
    const input = screen.getByLabelText(
      kind === "health" ? /Medical cost inflation/ : "Settlement costs: fixed ($)",
    );
    const button = screen.getByText(
      kind === "health" ? "Save health coverage" : "Save estate settings",
    );
    const saved = kind === "health" ? "Health coverage settings saved." : "Estate settings saved.";
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.click(button);
    await screen.findByText(saved);
    fireEvent.change(input, { target: { value: "7" } });
    expect(screen.queryByText(saved)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Unsaved");
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    fireEvent.change(input, { target: { value: "5" } });
    expect(screen.getByText(saved)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "7" } });
    save.mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(button);
    await screen.findByRole("alert");
    expect(input).toHaveDisplayValue("7");
    expect(screen.getByRole("status")).toHaveTextContent("Unsaved");
    fireEvent.click(button);
    await screen.findByText(saved);
    const cleanUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(cleanUnload);
    expect(cleanUnload.defaultPrevented).toBe(false);
  },
);

it.each(["healthcare", "estate"])(
  "guards %s sheet close, backdrop, Escape and navigation until discard or save",
  async (key) => {
    const index = PLAN_SECTIONS.findIndex((section) => section.key === key);
    expect(index).toBeGreaterThanOrEqual(0);
    const close = vi.fn(),
      navigate = vi.fn();
    const confirm = confirmDiscard.mockReset().mockResolvedValue(false);
    render(<EditSheet index={index} onClose={close} onIndexChange={navigate} />);
    const input =
      key === "healthcare"
        ? screen.getByLabelText("Model health coverage costs")
        : screen.getByLabelText("Settlement costs: fixed ($)");
    if (key === "healthcare") fireEvent.click(input);
    else fireEvent.change(input, { target: { value: "1000" } });
    fireEvent.click(screen.getByLabelText("Close editor"));
    fireEvent.click(document.querySelector(".edit-sheet-backdrop")!);
    fireEvent.keyDown(document, { key: "Escape" });
    const picker = screen.getByRole("combobox", { name: "Go to section" });
    fireEvent.change(picker, { target: { value: String(index + 1) } });
    fireEvent.change(picker, { target: { value: String(index - 1) } });
    expect(picker).toHaveValue(String(index));
    expect(confirm).toHaveBeenCalledTimes(5);
    await act(async () => {});
    expect(close).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
    confirm.mockResolvedValue(true);
    fireEvent.change(picker, { target: { value: String(index + 1) } });
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(index + 1));
    fireEvent.click(
      screen.getByText(key === "healthcare" ? "Save health coverage" : "Save estate settings"),
    );
    await screen.findByText(
      key === "healthcare" ? "Health coverage settings saved." : "Estate settings saved.",
    );
    confirm.mockClear();
    fireEvent.click(screen.getByLabelText("Close editor"));
    expect(confirm).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
  },
);

it("shows a blocked income deletion inside the sheet and retains the income and allocation", async () => {
  const message =
    "This income funds an allocation rule. In Income allocation, remove the rule or choose another source income and save before deleting this income.";
  persisted = {
    ...persisted,
    income_streams: [{ id: "salary", name: "Salary", annual_amount: 100000 } as never],
  };
  usePlanStore.setState({ plan: persisted });
  adapter.deleteIncome.mockRejectedValueOnce(new Error(message)).mockResolvedValue(undefined);
  render(
    <BuilderModeContext.Provider value="sheet">
      <IncomeSection />
    </BuilderModeContext.Provider>,
  );
  fireEvent.click(screen.getByText("Delete"));
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.getByText("Salary")).toBeInTheDocument();
  expect(adapter.fetchPlan).not.toHaveBeenCalled();
  persisted = { ...persisted, income_streams: [] };
  fireEvent.click(screen.getByText("Delete"));
  await waitFor(() => expect(screen.queryByText("Salary")).not.toBeInTheDocument());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
