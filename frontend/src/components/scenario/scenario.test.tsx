import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, expect, it, vi } from "vitest";

import AssetsDebtPanel from "@/components/assets_debt_panel";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { useScenarioStore } from "@/stores/scenario_store";
import type { PlanInheritance } from "@/types/scenario";
import { ScenarioBadge } from "./scenario_badge";
import { ScenarioBanner } from "./scenario_banner";
import { PRIORITIES_CONFLICT } from "./scenario_changes_panel";
import { formatScenarioValue } from "./scenario_format";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const scenario = makePlan({
  id: "s",
  name: "Retire at 55",
  client_id: "c",
  parent_plan_id: "p",
  priorities_revision: 7,
  milestones: [
    { id: "m1", name: "Retirement" },
    { id: "m2", name: "Move abroad" },
  ],
  income_streams: [{ id: "inc", name: "Salary" }],
  real_assets: [
    { id: "house", name: "House", current_value: 500000, annual_appreciation_rate: 0.03 },
  ],
  liabilities: [{ id: "loan", name: "Mortgage", principal_balance: 200000, interest_rate: 5 }],
});

const inheritance: PlanInheritance = {
  plan_id: "s",
  parent_plan_id: "p",
  parent_name: "Primary",
  status: "ok",
  synced_at: "2026-10-10T12:00:00Z",
  plan_fields: [{ field: "life_expectancy", value: 90, parent_value: 95 }],
  items: [
    {
      kind: "income",
      row_id: "inc",
      parent_row_id: "pinc",
      name: "Salary",
      state: "changed",
      fields: [
        { field: "annual_amount", value: 135000, parent_value: 120000 },
        { field: "end_milestone_id", value: "m2", parent_value: "m1" },
      ],
    },
    {
      kind: "real_asset",
      row_id: "house",
      parent_row_id: "phouse",
      name: "House",
      state: "inherited",
      fields: [],
    },
    {
      kind: "liability",
      row_id: "loan",
      parent_row_id: null,
      name: "Mortgage",
      state: "scenario_only",
      fields: [],
    },
    {
      kind: "expense",
      row_id: null,
      parent_row_id: "pcar",
      name: "New car",
      state: "removed",
      fields: [],
    },
    {
      kind: "priorities",
      row_id: null,
      parent_row_id: null,
      name: "Savings rules",
      state: "changed",
      fields: [],
    },
    {
      kind: "drawdown",
      row_id: null,
      parent_row_id: null,
      name: "Withdrawal order",
      state: "inherited",
      fields: [],
    },
  ],
  skipped: [],
};

const loadPlan = vi.fn().mockResolvedValue(undefined);
const setBaselinePlan = vi.fn().mockResolvedValue(undefined);
const detachScenario = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  adapter.fetchInheritance.mockResolvedValue(inheritance);
  adapter.listAccounts.mockResolvedValue([]);
  useScenarioStore.setState({ byPlan: {} });
  useSaveStore.setState({ pending: 0, failed: [], lastSavedAt: null });
  usePlanStore.setState({
    ...usePlanStore.getInitialState(),
    plan: scenario,
    plans: [
      { id: "p", name: "Primary", client_id: "c", plan_type: "standard", created_at: "" },
      scenario,
    ],
    loadPlan,
    setBaselinePlan,
    detachScenario,
  } as never);
});

it("shows the Main plan and change count, and compares only when asked", async () => {
  render(<ScenarioBanner />);
  const banner = screen.getByRole("region", { name: "Scenario" });
  expect(banner).toHaveTextContent("Scenario of Primary");
  await waitFor(() => expect(banner).toHaveTextContent("Scenario of Primary · 5 changes"));
  expect(adapter.fetchInheritance).toHaveBeenCalledWith("s");
  expect(setBaselinePlan).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Compare with Primary" }));
  expect(setBaselinePlan).toHaveBeenCalledWith("p");
  expect(within(banner).queryByRole("status")).not.toBeInTheDocument();
});

it("refreshes inheritance after a confirmed save on the scenario", async () => {
  render(<ScenarioBanner />);
  await waitFor(() => expect(adapter.fetchInheritance).toHaveBeenCalledOnce());
  act(() => useSaveStore.setState({ lastSavedAt: Date.now() }));
  await waitFor(() => expect(adapter.fetchInheritance).toHaveBeenCalledTimes(2));
});

it("lists skipped changes when the sync needs review and syncs on request", async () => {
  adapter.fetchInheritance.mockResolvedValue({
    ...inheritance,
    status: "needs_review",
    skipped: [
      {
        kind: "expense",
        parent_row_id: "pcar",
        name: "New car",
        field: "start_milestone_id",
        reason: "Its start milestone was removed in this scenario.",
      },
    ],
  });
  adapter.syncInheritance.mockResolvedValue({ ...inheritance, status: "ok", skipped: [] });
  render(<ScenarioBanner />);
  const review = await screen.findByRole("status");
  expect(review).toHaveTextContent("Some changes from Primary weren’t applied to this scenario:");
  expect(review).toHaveTextContent("New car: Its start milestone was removed in this scenario.");
  fireEvent.click(within(review).getByRole("button", { name: "Sync now" }));
  await waitFor(() => expect(adapter.syncInheritance).toHaveBeenCalledWith("s"));
  await waitFor(() => expect(screen.queryByText(/weren’t applied/)).not.toBeInTheDocument());
  expect(loadPlan).toHaveBeenCalledWith("s");
});

it("lists whole-plan problems that have no field, each once", async () => {
  const failed =
    "Main’s latest changes could not be applied to this scenario. Use Sync now to try again.";
  const review =
    "After Main’s latest changes this scenario needs review: Life expectancy is too low.";
  adapter.fetchInheritance.mockResolvedValue({
    ...inheritance,
    status: "needs_review",
    skipped: [
      { kind: "plan", parent_row_id: "p", name: "Retire at 55", field: null, reason: failed },
      { kind: "plan", parent_row_id: "p", name: "Retire at 55", field: null, reason: review },
    ],
  });
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<ScenarioBanner />);
    const rows = within(await screen.findByRole("status")).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      `Retire at 55: ${failed}`,
      `Retire at 55: ${review}`,
    ]);
    expect(screen.getAllByText(failed, { exact: false })).toHaveLength(1);
    expect(screen.getAllByText(review, { exact: false })).toHaveLength(1);
    expect(consoleError).not.toHaveBeenCalled();
  } finally {
    consoleError.mockRestore();
  }
});

it("keeps the banner without counts when the read fails, and retries", async () => {
  adapter.fetchInheritance.mockRejectedValueOnce(new Error("Network unavailable"));
  render(<ScenarioBanner />);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Couldn’t load what this scenario changed.");
  const banner = screen.getByRole("region", { name: "Scenario" });
  expect(banner).not.toHaveTextContent("change ·");
  expect(banner).not.toHaveTextContent(/\d+ changes?/);
  expect(screen.getByRole("button", { name: "View changes" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Compare with Primary" })).toBeEnabled();
  fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(banner).toHaveTextContent("5 changes"));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

async function openPanel() {
  render(<ScenarioBanner />);
  await waitFor(() => expect(screen.getByRole("button", { name: "View changes" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "View changes" }));
  return screen.getByRole("dialog", { name: "Changes in this scenario" });
}

it("groups changes by section with Main’s and this scenario’s values", async () => {
  const panel = await openPanel();
  const sections = within(panel)
    .getAllByRole("region")
    .map((section) => section.getAttribute("aria-label"));
  expect(sections).toEqual([
    "Plan details",
    "Income streams",
    "Expenses",
    "Income allocation",
    "Property and debt",
  ]);
  const income = within(panel).getByRole("region", { name: "Income streams" });
  expect(income).toHaveTextContent("Annual amount Main: $120,000 · This scenario: $135,000");
  expect(income).toHaveTextContent("Ends at Main: Retirement · This scenario: Move abroad");
  expect(within(panel).getByRole("region", { name: "Plan details" })).toHaveTextContent(
    "Longevity age Main: 95 · This scenario: 90",
  );
  expect(within(panel).getByRole("region", { name: "Expenses" })).toHaveTextContent(
    "New carRemoved in this scenario",
  );
  expect(within(panel).getByRole("region", { name: "Property and debt" })).toHaveTextContent(
    "MortgageOnly in this scenario",
  );
  expect(panel).not.toHaveTextContent("House");
  expect(panel).not.toHaveTextContent("Withdrawal order");
});

it("uses Main’s value for a field, a row or plan settings, and restores a removed item", async () => {
  const updated = {
    ...inheritance,
    items: inheritance.items.filter((item) => item.kind !== "income"),
  };
  adapter.resetInheritance.mockResolvedValue(updated);
  adapter.restoreInheritance.mockResolvedValue(updated);
  const panel = await openPanel();
  fireEvent.click(
    within(panel).getByRole("button", { name: "Use Main’s value for Annual amount of Salary" }),
  );
  await waitFor(() =>
    expect(adapter.resetInheritance).toHaveBeenCalledWith("s", {
      kind: "income",
      row_id: "inc",
      fields: ["annual_amount"],
    }),
  );
  await waitFor(() => expect(loadPlan).toHaveBeenCalledWith("s"));
  await waitFor(() =>
    expect(within(panel).queryByRole("region", { name: "Income streams" })).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("region", { name: "Scenario" })).toHaveTextContent("4 changes");

  // One changed setting has one button; the group button appears for two or more.
  expect(
    within(panel).queryByRole("button", { name: "Use Main’s values for plan settings" }),
  ).not.toBeInTheDocument();
  await waitFor(() =>
    expect(
      within(panel).getByRole("button", {
        name: "Use Main’s value for Longevity age of plan settings",
      }),
    ).toBeEnabled(),
  );
  fireEvent.click(
    within(panel).getByRole("button", {
      name: "Use Main’s value for Longevity age of plan settings",
    }),
  );
  await waitFor(() =>
    expect(adapter.resetInheritance).toHaveBeenLastCalledWith("s", {
      kind: "plan",
      fields: ["life_expectancy"],
    }),
  );

  await waitFor(() =>
    expect(within(panel).getByRole("button", { name: "Restore New car" })).toBeEnabled(),
  );
  fireEvent.click(within(panel).getByRole("button", { name: "Restore New car" }));
  await waitFor(() =>
    expect(adapter.restoreInheritance).toHaveBeenCalledWith("s", {
      kind: "expense",
      parent_row_id: "pcar",
    }),
  );
});

it("syncs from the panel at any time", async () => {
  adapter.syncInheritance.mockResolvedValue(inheritance);
  const panel = await openPanel();
  fireEvent.click(within(panel).getByRole("button", { name: "Sync now" }));
  await waitFor(() => expect(adapter.syncInheritance).toHaveBeenCalledWith("s"));
  await waitFor(() => expect(loadPlan).toHaveBeenCalledWith("s"));
});

it("resets a whole changed row", async () => {
  adapter.resetInheritance.mockResolvedValue(inheritance);
  const panel = await openPanel();
  fireEvent.click(within(panel).getByRole("button", { name: "Use Main’s values for Salary" }));
  await waitFor(() =>
    expect(adapter.resetInheritance).toHaveBeenCalledWith("s", { kind: "income", row_id: "inc" }),
  );
});

it("shows the server’s reason when a restore depends on another removed item", async () => {
  adapter.restoreInheritance.mockRejectedValue(
    new Error("Restore the milestone “Move abroad” first."),
  );
  const panel = await openPanel();
  fireEvent.click(within(panel).getByRole("button", { name: "Restore New car" }));
  expect(await within(panel).findByRole("alert")).toHaveTextContent(
    "Restore the milestone “Move abroad” first.",
  );
  expect(loadPlan).not.toHaveBeenCalled();
});

it("sends the allocation revision with Use Main’s rules and reloads on a conflict without applying anything", async () => {
  const config = { headers: new AxiosHeaders() } as never;
  adapter.resetInheritance.mockRejectedValue(
    new AxiosError("Conflict", "ERR_BAD_REQUEST", config, undefined, {
      status: 409,
      statusText: "Conflict",
      headers: {},
      config,
      data: {
        error: {
          code: "CONFLICT",
          message: "Revision changed",
          details: [{ field: "expected_revision", reason: "stale" }],
        },
      },
    }),
  );
  const panel = await openPanel();
  fireEvent.click(within(panel).getByRole("button", { name: "Use Main’s rules: Savings rules" }));
  await waitFor(() =>
    expect(adapter.resetInheritance).toHaveBeenCalledWith("s", {
      kind: "priorities",
      expected_revision: 7,
    }),
  );
  expect(await within(panel).findByRole("alert")).toHaveTextContent(PRIORITIES_CONFLICT);
  expect(loadPlan).toHaveBeenCalledWith("s");
  await waitFor(() => expect(adapter.fetchInheritance).toHaveBeenCalledTimes(2));
  expect(useScenarioStore.getState().byPlan.s.data).toEqual(inheritance);
});

it("makes the scenario independent only after confirming", async () => {
  detachScenario.mockImplementation(async () => {
    usePlanStore.setState({ plan: { ...scenario, parent_plan_id: null } });
    return true;
  });
  const panel = await openPanel();
  fireEvent.click(within(panel).getByRole("button", { name: "Make independent…" }));
  expect(panel).toHaveTextContent(
    "“Retire at 55” keeps its current values and stops receiving changes from “Primary”.",
  );
  expect(detachScenario).not.toHaveBeenCalled();
  fireEvent.click(within(panel).getByRole("button", { name: "Make independent" }));
  await waitFor(() => expect(detachScenario).toHaveBeenCalledWith("s"));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.queryByRole("region", { name: "Scenario" })).not.toBeInTheDocument();
  expect(useScenarioStore.getState().byPlan.s).toBeUndefined();
});

it("keeps the panel open with the error when making independent fails", async () => {
  detachScenario.mockImplementation(async () => {
    usePlanStore.setState({ error: "Plan is archived." });
    return false;
  });
  const panel = await openPanel();
  fireEvent.click(within(panel).getByRole("button", { name: "Make independent…" }));
  fireEvent.click(within(panel).getByRole("button", { name: "Make independent" }));
  expect(await within(panel).findByRole("alert")).toHaveTextContent("Plan is archived.");
});

it("badges changed and scenario-only rows, never inherited rows or ordinary plans", async () => {
  useScenarioStore.setState({
    byPlan: { s: { data: inheritance, loading: false, failed: false } },
  });
  const view = render(<AssetsDebtPanel plan={scenario} />);
  await waitFor(() => expect(adapter.listAccounts).toHaveBeenCalled());
  expect(screen.getByText("Mortgage").parentElement).toHaveTextContent(
    "MortgageOnly in this scenario",
  );
  expect(screen.getByText("House").parentElement).not.toHaveTextContent(/in (this )?scenario/);
  act(() =>
    useScenarioStore.setState({
      byPlan: {
        s: {
          data: {
            ...inheritance,
            items: inheritance.items.map((item) =>
              item.row_id === "house" ? { ...item, state: "changed" as const } : item,
            ),
          },
          loading: false,
          failed: false,
        },
      },
    }),
  );
  expect(screen.getByText("House").parentElement).toHaveTextContent("HouseChanged in scenario");
  view.unmount();
  render(
    <>
      <ScenarioBadge rowId="inc" />
      <ScenarioBadge rowId="loan" />
      <ScenarioBadge rowId="missing" />
      <ScenarioBadge rowId={null} />
    </>,
  );
  expect(screen.getAllByText(/in (this )?scenario/).map((badge) => badge.textContent)).toEqual([
    "Changed in scenario",
    "Only in this scenario",
  ]);
  act(() => usePlanStore.setState({ plan: { ...scenario, parent_plan_id: null } }));
  expect(screen.queryByText(/in (this )?scenario/)).not.toBeInTheDocument();
});

it("formats values in each field’s own unit", () => {
  const ctx = { plan: scenario, accounts: [{ id: "a1", name: "Roth IRA" }] as never };
  expect(formatScenarioValue("annual_amount", 120000, ctx)).toBe("$120,000");
  expect(formatScenarioValue("annual_appreciation_rate", 0.035, ctx)).toBe("3.5%");
  expect(formatScenarioValue("growth_rate", 3, ctx)).toBe("3%");
  expect(formatScenarioValue("interest_rate", 6.25, ctx)).toBe("6.25%");
  expect(formatScenarioValue("start_milestone_id", "m1", ctx)).toBe("Retirement");
  expect(formatScenarioValue("target_account_id", "a1", ctx)).toBe("Roth IRA");
  expect(formatScenarioValue("start_date", "2027-03-01", ctx)).toBe("March 1, 2027");
  expect(formatScenarioValue("start_month", 7, ctx)).toBe("July");
  expect(formatScenarioValue("claiming_age", 70, ctx)).toBe("70");
  expect(formatScenarioValue("filing_status", "married_joint", ctx)).toBe("married joint");
  expect(formatScenarioValue("end_milestone_id", null, ctx)).toBe("None");
  expect(formatScenarioValue("is_active", false, ctx)).toBe("No");
  expect(formatScenarioValue("spending_rules", { floor: 1 }, ctx)).toBe('{"floor":1}');
});
