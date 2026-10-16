import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./app";
import { PLAN_SECTIONS } from "@/pages/plan_setup";
import { useAuthStore } from "@/stores/auth_store";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { useThemeStore } from "@/stores/theme_store";
import type { SimulationResult, User } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
vi.hoisted(() => {
  window.matchMedia = vi.fn(() => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});
// Shell tests keep routing/state/render decisions real. Complex leaf content has its own suites.
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => testAdapter),
);
vi.mock("@/components/dashboard_view", () => ({
  default: ({ onEditAllocation }: { onEditAllocation: (rank?: number) => void }) => (
    <div>
      Dashboard content<button onClick={() => onEditAllocation()}>Allocate income</button>
      <button onClick={() => onEditAllocation(2)}>Review rule</button>
      <button id="allocation-rule-2">Rule two</button>
    </div>
  ),
}));
vi.mock("@/components/monte_carlo_dashboard", () => ({
  default: () => <div>Monte Carlo content</div>,
}));
vi.mock("@/components/withdrawal_strategies_panel", () => ({
  default: () => <div>Withdrawal content</div>,
}));
vi.mock("@/components/historical_stress_test", () => ({
  default: () => <div>Stress content</div>,
}));
vi.mock("@/components/annual_report", () => ({ default: () => <div>Annual content</div> }));
vi.mock("@/components/metric_definitions_panel", () => ({
  default: () => <div>Definitions content</div>,
}));
vi.mock("@/components/progress_history", () => ({ default: () => <div>Progress content</div> }));
vi.mock("@/components/tax/tax_tools_panel", () => ({ default: () => <div>Tax content</div> }));
vi.mock("@/components/printable_report", () => ({
  default: ({ onClose }: { onClose: () => void }) => (
    <div role="document">
      Print content<button onClick={onClose}>Return from report</button>
    </div>
  ),
}));
vi.mock("@/components/edit_sheet", () => ({
  default: ({
    index,
    onClose,
    onIndexChange,
  }: {
    index: number;
    onClose: () => void;
    onIndexChange: (n: number) => void;
  }) => (
    <div role="dialog">
      Section {index}
      <button onClick={onClose}>Close editor</button>
      <button onClick={() => onIndexChange(index - 1)}>Next section</button>
    </div>
  ),
}));
vi.mock("@/components/plan_section_nav", () => ({
  default: ({ onEdit }: { onEdit: (key: string) => void }) => (
    <button onClick={() => onEdit("notes")}>Edit Notes</button>
  ),
}));
const testAdapter = makeAdapter();
const plan = makePlan({ id: "p", name: "Primary", birth_year: 1990 });
const simulation = {
  metadata: { start_year: 2026, success: true, warnings: [] },
  yearly_snapshots: [
    { year: 2026, age: 36, net_worth: 10000 },
    { year: 2027, age: 37, net_worth: 20000 },
  ],
} as unknown as SimulationResult;
const ensureSession = vi.fn().mockResolvedValue(undefined),
  loadPlans = vi.fn().mockResolvedValue(undefined),
  loadPlan = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
  useAuthStore.setState({
    user: { id: "u", is_anonymous: false, email: "test@example.test" } as User,
    isLoading: false,
    error: null,
    ensureSession,
  });
  usePlanStore.setState({
    ...usePlanStore.getInitialState(),
    plan,
    plans: [plan, { ...plan, id: "other", name: "Other" }],
    simulation,
    loadPlans,
    loadPlan,
  });
  useSaveStore.setState({ pending: 0, failed: [], lastSavedAt: null });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it("starts a session and shows loading until it settles", async () => {
  useAuthStore.setState({ isLoading: true });
  render(<App />);
  expect(ensureSession).toHaveBeenCalledOnce();
  expect(screen.queryByRole("heading", { name: "Primary" })).not.toBeInTheDocument();
  act(() => useAuthStore.setState({ isLoading: false }));
  expect(await screen.findByRole("heading", { name: "Primary" })).toBeVisible();
});
it("shows session failure and retries through the visible control", async () => {
  useAuthStore.setState({ error: "Network unavailable" });
  render(<App />);
  expect(screen.getByRole("alert")).toHaveTextContent("Network unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry opening planner" }));
  expect(ensureSession).toHaveBeenCalledTimes(2);
  act(() => useAuthStore.setState({ error: null }));
  expect(await screen.findByRole("heading", { name: "Primary" })).toBeVisible();
});
it("navigates every enabled workspace and closes printable output", async () => {
  render(<App />);
  await waitFor(() => expect(loadPlans).toHaveBeenCalledOnce());
  for (const [tab, text] of [
    ["Success odds", "Monte Carlo content"],
    ["Historical Stress Test", "Stress content"],
    ["Tax tools", "Tax content"],
    ["Track actuals", "Progress content"],
    ["Exports", "Annual content"],
    ["Overview", "Dashboard content"],
  ]) {
    fireEvent.click(screen.getByRole("button", { name: tab }));
    expect(await screen.findByText(text)).toBeVisible();
  }
  fireEvent.click(screen.getByRole("button", { name: "Exports" }));
  fireEvent.click(screen.getByRole("button", { name: "Open printable report" }));
  expect(await screen.findByRole("document")).toBeVisible();
  // The report is a step in history: Back closes it and returns to the tab it opened from.
  expect(window.location.search).toContain("view=print");
  act(() => window.history.back());
  await waitFor(() => expect(screen.queryByRole("document")).not.toBeInTheDocument());
  expect(window.location.search).toContain("tab=reports");
  expect(window.location.search).not.toContain("view=print");
  fireEvent.click(screen.getByRole("button", { name: "Open printable report" }));
  expect(screen.getByRole("document")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Return from report" }));
  await waitFor(() => expect(screen.queryByRole("document")).not.toBeInTheDocument());
});
it("marks which edges of the view tabs hide more tabs, and reveals a focused tab", async () => {
  render(<App />);
  await waitFor(() => expect(loadPlans).toHaveBeenCalledOnce());
  const row = screen.getByRole("navigation", { name: "Plan views" });
  // jsdom lays nothing out: give the row 300px more tabs than it shows.
  let scrollLeft = 0;
  Object.defineProperties(row, {
    scrollWidth: { configurable: true, value: 960 },
    clientWidth: { configurable: true, value: 660 },
    scrollLeft: {
      configurable: true,
      get: () => scrollLeft,
      set: (value: number) => {
        scrollLeft = value;
      },
    },
  });
  const edges = () => [
    row.hasAttribute("data-overflow-start"),
    row.hasAttribute("data-overflow-end"),
  ];
  fireEvent.scroll(row);
  expect(edges()).toEqual([false, true]);
  scrollLeft = 150;
  fireEvent.scroll(row);
  expect(edges()).toEqual([true, true]);
  scrollLeft = 300;
  fireEvent.scroll(row);
  expect(edges()).toEqual([true, false]);

  scrollLeft = 0;
  row.getBoundingClientRect = () => ({ left: 0, right: 660, width: 660 }) as DOMRect;
  const last = screen.getByRole("button", { name: "Track actuals" });
  last.getBoundingClientRect = () => ({ left: 880, right: 980, width: 100 }) as DOMRect;
  act(() => last.focus());
  // Scrolled until the tab clears the 48px edge fade.
  expect(scrollLeft).toBe(980 - (660 - 48));
});
it("keeps the Compare months tab and the Transactions section out while transactions are off", async () => {
  // App_transactions.test.tsx covers both with TRANSACTIONS_ENABLED on.
  render(<App />);
  await waitFor(() => expect(loadPlans).toHaveBeenCalledOnce());
  expect(screen.queryByRole("button", { name: "Compare months" })).not.toBeInTheDocument();
  expect(PLAN_SECTIONS.map((s) => s.key)).not.toContain("transactions");
});
it.each(["save", "simulation", "empty"])("blocks report launch while %s", async (phase) => {
  if (phase === "save") useSaveStore.setState({ pending: 1 });
  else
    usePlanStore.setState(phase === "simulation" ? { isSimulating: true } : { simulation: null });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Exports" }));
  expect(await screen.findByRole("button", { name: "Open printable report" })).toBeDisabled();
});
it("switches plans and opens and closes the plan editor from expanded and collapsed navigation", async () => {
  render(<App />);
  fireEvent.change(screen.getByRole("combobox", { name: "Active plan" }), {
    target: { value: "other" },
  });
  expect(loadPlan).toHaveBeenCalledWith("other");
  fireEvent.click(screen.getByRole("button", { name: "Edit Notes" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  const before = screen.getByRole("dialog").textContent;
  fireEvent.click(screen.getByRole("button", { name: "Next section" }));
  expect(screen.getByRole("dialog").textContent).not.toBe(before);
  fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
  fireEvent.click(screen.getByTitle("Collapse plan builder"));
  fireEvent.click(screen.getByRole("button", { name: "Edit plan details" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("Section 0");
  fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
  fireEvent.click(screen.getByRole("button", { name: "Open plan builder" }));
  expect(screen.getByRole("combobox", { name: "Active plan" })).toBeVisible();
});
it("opens allocation editing and focuses the requested rule", async () => {
  vi.useFakeTimers();
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Allocate income" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
  fireEvent.click(screen.getByRole("button", { name: "Review rule" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(160);
  });
  expect(scroll).toHaveBeenCalledWith({ block: "center" });
  expect(screen.getByRole("button", { name: "Rule two" })).toHaveFocus();
});
it("shows errors, persists theme choices and starts collapsed at narrow widths", async () => {
  vi.mocked(window.matchMedia).mockReturnValue({ matches: false } as MediaQueryList);
  usePlanStore.setState({ error: "Save unavailable" });
  render(<App />);
  fireEvent.click(screen.getByTitle("Expand plan builder"));
  expect(screen.getByRole("alert")).toHaveTextContent("Save unavailable");
  for (const [title, preference] of [
    ["Dark", "dark"],
    ["Light", "light"],
    ["System", "system"],
  ] as const) {
    fireEvent.click(screen.getByTitle(title));
    expect(useThemeStore.getState().preference).toBe(preference);
  }
});
it.each(["other", "missing", "unavailable"])(
  "restores the active plan with storage value %s",
  async (saved) => {
    usePlanStore.setState({ plan: null, simulation: null });
    localStorage.setItem("coastmath:active-plan:u", saved);
    if (saved === "unavailable")
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new Error("Denied");
      });
    render(<App />);
    await waitFor(() => expect(loadPlan).toHaveBeenCalledWith(saved === "other" ? "other" : "p"));
  },
);
it("offers creation for an empty household", async () => {
  usePlanStore.setState({ plan: null, plans: [], simulation: null });
  render(<App />);
  expect(screen.getByRole("heading", { name: "Projection dashboard" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Create plan" })).toBeVisible();
});
it("compares only matching years and converts the displayed difference to start-year currency", async () => {
  usePlanStore.setState({
    currencyMode: "nominal",
    compareMode: true,
    baselineSimulation: {
      ...simulation,
      yearly_snapshots: [{ year: 2027, net_worth: -600 }],
    } as SimulationResult,
  });
  render(<App />);
  expect(screen.getByText(/\+\$21k vs baseline in 2027/)).toBeVisible();
  act(() => usePlanStore.setState({ currencyMode: "inflation_adjusted" }));
  expect(screen.getByText(/\+\$20k vs baseline in 2027/)).toBeVisible();
  act(() =>
    usePlanStore.setState({
      baselineSimulation: {
        ...simulation,
        yearly_snapshots: [{ year: 2050, net_worth: -600 }],
      } as SimulationResult,
    }),
  );
  expect(screen.queryByText(/vs baseline/)).not.toBeInTheDocument();
});

it("shows no edit countdown, duplicates directly, and restores an open archived plan", async () => {
  const restorePlan = vi.fn().mockResolvedValue(true);
  usePlanStore.setState({
    plans: [plan],
    plan: {
      ...plan,
      id: "old",
      name: "Old plan",
      archived_at: "2026-09-20T00:00:00Z",
      editable: false,
    },
    restorePlan,
  });
  render(<App />);
  expect(screen.queryByTestId("edit-countdown")).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Old plan (archived)" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Restore" }));
  expect(restorePlan).toHaveBeenCalledWith("old");
  fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
  expect(screen.getByRole("button", { name: "Duplicate plan" })).toBeVisible();
});
it("describes a workspace copy as independent and a legacy copy as sharing balances", async () => {
  usePlanStore.setState({ plans: [plan], plan: { ...plan, client_id: "c" } });
  const view = render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
  expect(
    screen.getByText(
      "Copy “Primary”. The copy starts identical, then keeps its own balances and inputs. The original is unchanged.",
    ),
  ).toBeVisible();
  view.unmount();
  usePlanStore.setState({ plan: { ...plan, client_id: null } });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
  expect(
    screen.getByText(
      "Copy “Primary”. Both plans use the same current account balances; balance edits affect both.",
    ),
  ).toBeVisible();
});
it("deletes the active plan after confirmation and opens the next plan", async () => {
  const other = { ...plan, id: "other", name: "Other" };
  const deletePlan = vi.fn().mockImplementation(async () => {
    usePlanStore.setState({ plan: null, plans: [other] });
    return true;
  });
  usePlanStore.setState({ plans: [plan, other], plan: { ...plan, client_id: "c" }, deletePlan });
  render(<App />);
  await waitFor(() => expect(loadPlans).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  const dialog = screen.getByRole("dialog", { name: "Delete plan" });
  expect(dialog).toHaveTextContent(
    "Deletes “Primary”, its inputs and its own accounts. This can’t be undone.",
  );
  expect(deletePlan).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Delete plan" }));
  await waitFor(() => expect(deletePlan).toHaveBeenCalledWith("p"));
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "Delete plan" })).not.toBeInTheDocument(),
  );
  await waitFor(() => expect(loadPlan).toHaveBeenCalledWith("other"));
});
it("keeps the delete confirmation open with the error when deletion fails, and cancels without a request", async () => {
  const deletePlan = vi.fn().mockImplementation(async () => {
    usePlanStore.setState({ error: "Plan could not be deleted." });
    return false;
  });
  usePlanStore.setState({ deletePlan });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(screen.getByRole("dialog", { name: "Delete plan" })).toHaveTextContent(
    "Deletes “Primary” and its inputs; shared accounts stay.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete plan" }));
  await waitFor(() => expect(deletePlan).toHaveBeenCalledOnce());
  const dialog = screen.getByRole("dialog", { name: "Delete plan" });
  expect(dialog).toHaveTextContent("Plan could not be deleted.");
  expect(screen.getByRole("button", { name: "Delete plan" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog", { name: "Delete plan" })).not.toBeInTheDocument();
  expect(deletePlan).toHaveBeenCalledOnce();
});

// Scenarios: plans linked to a Main plan (parent_plan_id).
const notScenario = {
  plan_id: "s",
  parent_plan_id: "p",
  parent_name: "Primary",
  status: "ok",
  synced_at: null,
  plan_fields: [],
  items: [],
  skipped: [],
};
const main = makePlan({ ...plan, client_id: "c" });
const scenario = makePlan({
  ...plan,
  id: "s",
  name: "Retire at 55",
  client_id: "c",
  parent_plan_id: "p",
});
const independent = makePlan({ ...plan, id: "i", name: "Solo", client_id: "c" });
it("lists each Main plan’s scenarios under it in the native plan select", async () => {
  Object.assign(testAdapter, { fetchInheritance: vi.fn().mockResolvedValue(notScenario) });
  usePlanStore.setState({
    plans: [main, independent, scenario, { ...scenario, id: "s2", name: "Part-time" }],
    plan: main,
  });
  render(<App />);
  const select = screen.getByRole("combobox", { name: "Active plan" });
  expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
    "Primary",
    "Retire at 55",
    "Part-time",
    "Solo",
  ]);
  const group = screen.getByRole("group", { name: "Scenarios of Primary" });
  expect([...group.querySelectorAll("option")].map((o) => o.value)).toEqual(["s", "s2"]);
  fireEvent.change(select, { target: { value: "s2" } });
  expect(loadPlan).toHaveBeenCalledWith("s2");
});
it.each([
  ["a Main plan", main, "p", "Primary (scenario)"],
  ["a scenario, as a sibling from its Main", scenario, "p", "Primary (scenario)"],
  ["an independent plan", independent, "i", "Solo (scenario)"],
])(
  "creates a named scenario of %s and closes the dialog",
  async (_label, open, sourceId, defaultName) => {
    const createScenario = vi.fn().mockResolvedValue(true);
    Object.assign(testAdapter, { fetchInheritance: vi.fn().mockResolvedValue(notScenario) });
    usePlanStore.setState({ plans: [main, independent, scenario], plan: open, createScenario });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
    const dialog = screen.getByRole("dialog", { name: "New scenario" });
    const name = screen.getByRole("textbox", { name: "Scenario name" });
    expect(name).toHaveValue(defaultName);
    expect(dialog).toHaveTextContent(
      `“${defaultName.replace(" (scenario)", "")}” stays the Main plan.`,
    );
    fireEvent.change(name, { target: { value: "  Retire early  " } });
    fireEvent.click(screen.getByRole("button", { name: "Create scenario" }));
    await waitFor(() => expect(createScenario).toHaveBeenCalledWith(sourceId, "Retire early"));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "New scenario" })).not.toBeInTheDocument(),
    );
  },
);
it("keeps the New scenario dialog open with the error when creation fails", async () => {
  const createScenario = vi.fn().mockImplementation(async () => {
    usePlanStore.setState({ error: "Create it from the Main plan." });
    return false;
  });
  usePlanStore.setState({ plans: [main], plan: main, createScenario });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Scenario name" }), {
    target: { value: " " },
  });
  expect(screen.getByRole("button", { name: "Create scenario" })).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "Scenario name" }), {
    target: { value: "Early" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create scenario" }));
  await waitFor(() =>
    expect(screen.getByRole("dialog", { name: "New scenario" })).toHaveTextContent(
      "Create it from the Main plan.",
    ),
  );
});
it("says a deleted Main plan’s scenarios become independent and a scenario’s copy is independent", async () => {
  Object.assign(testAdapter, { fetchInheritance: vi.fn().mockResolvedValue(notScenario) });
  usePlanStore.setState({
    plans: [main, scenario, { ...scenario, id: "s2", name: "Part-time" }],
    plan: main,
  });
  const view = render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(screen.getByRole("dialog", { name: "Delete plan" })).toHaveTextContent(
    "2 scenarios will become independent plans and keep their current values.",
  );
  view.unmount();
  usePlanStore.setState({ plans: [main, scenario], plan: main });
  const single = render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(screen.getByRole("dialog", { name: "Delete plan" })).toHaveTextContent(
    "1 scenario will become an independent plan and keep its current values.",
  );
  single.unmount();
  usePlanStore.setState({ plans: [main, scenario], plan: scenario });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  const scenarioDialog = screen.getByRole("dialog", { name: "Delete scenario" });
  expect(scenarioDialog).not.toHaveTextContent("independent");
  expect(within(scenarioDialog).getByRole("button", { name: "Delete scenario" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Delete plan" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
  expect(
    screen.getByText(
      "Copy “Retire at 55”. The copy is an independent plan: it starts with this scenario’s values and doesn’t receive changes from “Primary”. This scenario is unchanged.",
    ),
  ).toBeVisible();
});
it("shows the scenario banner only for a scenario", async () => {
  const fetchInheritance = vi.fn().mockResolvedValue({
    ...notScenario,
    plan_fields: [{ field: "life_expectancy", value: 90, parent_value: 95 }],
  });
  Object.assign(testAdapter, { fetchInheritance });
  usePlanStore.setState({ plans: [main, scenario], plan: main });
  const view = render(<App />);
  expect(screen.queryByRole("region", { name: "Scenario" })).not.toBeInTheDocument();
  expect(fetchInheritance).not.toHaveBeenCalled();
  view.unmount();
  usePlanStore.setState({ plan: scenario });
  render(<App />);
  expect(await screen.findByText("Scenario of Primary")).toBeVisible();
  expect(screen.getByRole("region", { name: "Scenario" })).toHaveTextContent(
    "Scenario of Primary · 1 change",
  );
  expect(fetchInheritance).toHaveBeenCalledWith("s");
});
