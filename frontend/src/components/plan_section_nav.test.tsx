import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import PlanSectionNav from "./plan_section_nav";
import { PLAN_SECTIONS } from "@/pages/plan_setup";
import { usePlanStore } from "@/stores/plan_store";
import { useFiEstimateStore } from "@/stores/fi_estimate_store";
import type { Account, SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const empty = makePlan({ id: "a", birth_year: 1990, notes: null });
const group = (name: string) => screen.getByRole("region", { name });
const editButtons = (scope: HTMLElement = document.body) =>
  within(scope).queryAllByRole("button", { name: /^Edit / });
const filter = () => screen.getByRole("searchbox", { name: "Filter plan sections" });
beforeEach(() => {
  vi.clearAllMocks();
  adapter.listAccounts.mockResolvedValue([]);
  usePlanStore.setState({ plan: empty, simulation: null, accountsRevision: 0 });
  useFiEstimateStore.setState({ hiddenByPlan: {} });
});
it("shows four essentials, labels optional topics, and opens every section", async () => {
  const onEdit = vi.fn();
  render(<PlanSectionNav activeKey="accounts" onEdit={onEdit} />);
  expect(screen.getByText("Loading accounts…")).toBeInTheDocument();
  await screen.findByText("Add your first account");
  expect(screen.getByText("Add your first income stream")).toBeInTheDocument();
  expect(screen.getByText("Add your living expenses")).toBeInTheDocument();
  expect(screen.getByText("Growth default · inflation 3.0%")).toBeInTheDocument();
  expect(
    PLAN_SECTIONS.filter((section) => section.essential).map((section) => section.key),
  ).toEqual(["plan_details", "income", "expenses", "accounts"]);
  expect(screen.getByRole("heading", { name: "Essentials" })).toBeInTheDocument();
  // Three distinct categories, each its own labelled card.
  expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual([
    "Essentials",
    "Optional",
    "Assumptions",
  ]);
  expect(editButtons(group("Essentials")).map((b) => b.getAttribute("aria-label"))).toEqual([
    "Edit Plan details",
    "Edit Accounts",
    "Edit Income streams",
    "Edit Expenses",
  ]);
  expect(editButtons(group("Assumptions")).map((b) => b.getAttribute("aria-label"))).toEqual([
    "Edit Assumptions, optional",
  ]);
  // The built-in CoastMath FI estimate counts as a milestone until removed.
  expect(screen.getByText("Financial independence (CoastMath estimate)")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit Accounts" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(screen.getByRole("button", { name: "Edit Plan details" })).not.toHaveAttribute(
    "aria-current",
  );
  // Unconfigured optional sections wait behind "Show more"; configured and open ones stay in view.
  expect(editButtons(group("Optional")).map((b) => b.getAttribute("aria-label"))).toEqual([
    "Edit Milestones, optional",
    "Edit Charitable giving, optional",
  ]);
  expect(screen.queryByText("No savings rules.")).not.toBeInTheDocument();
  const more = screen.getByRole("button", { name: "Show 7 more optional sections" });
  expect(more).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(more);
  expect(screen.getByRole("button", { name: "Show fewer optional sections" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  expect(screen.getByText("No savings rules.")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Edit Property and debt, optional" }),
  ).toBeInTheDocument();
  for (const button of editButtons()) fireEvent.click(button);
  const opened = onEdit.mock.calls.map((call) => call[0]);
  expect(opened).toEqual([
    "plan_details",
    "accounts",
    "income",
    "expenses",
    "milestones",
    "charitable",
    "property_debt",
    "income_allocation",
    "drawdown",
    "healthcare",
    "flex",
    "estate",
    "notes",
    "assumptions",
  ]);
  // Every section is reachable exactly once.
  expect([...opened].sort()).toEqual(PLAN_SECTIONS.map((section) => section.key).sort());
  fireEvent.click(screen.getByRole("button", { name: "Show fewer optional sections" }));
  expect(screen.queryByText("No savings rules.")).not.toBeInTheDocument();
});
it("flags empty essentials as needing input and counts progress", async () => {
  render(<PlanSectionNav activeKey={null} onEdit={vi.fn()} />);
  await screen.findByText("Add your first account");
  const essentials = group("Essentials");
  expect(within(essentials).getAllByText("Needs input")).toHaveLength(3);
  expect(within(essentials).getByText("1 of 4 set")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit Income streams" })).toHaveAccessibleDescription(
    "Add your first income stream Needs input",
  );
  expect(screen.getByRole("button", { name: "Edit Plan details" })).toHaveAccessibleDescription(
    "Single · born 1990 · no state tax",
  );
  act(() =>
    usePlanStore.setState({ plan: makePlan({ ...empty, income_streams: [{}], expenses: [{}] }) }),
  );
  expect(within(essentials).getAllByText("Needs input")).toHaveLength(1);
  expect(within(essentials).getByText("3 of 4 set")).toBeInTheDocument();
  // Optional sections never say "Needs input".
  expect(within(group("Optional")).queryByText("Needs input")).not.toBeInTheDocument();
});
it("keeps an open optional section in view even when it is not set up", async () => {
  render(<PlanSectionNav activeKey="notes" onEdit={vi.fn()} />);
  await screen.findByText("Add your first account");
  expect(screen.getByRole("button", { name: "Edit Notes, optional" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(screen.getByRole("button", { name: "Show 6 more optional sections" })).toBeInTheDocument();
});
it("reconciles displayed annual totals and ordered withdrawals from saved records", async () => {
  adapter.listAccounts.mockResolvedValue([
    { id: "cash", name: "Cash", account_type: "checking", balance: 10000 },
    { id: "ira", name: "IRA", account_type: "traditional_ira", balance: 20000 },
  ]);
  usePlanStore.setState({
    plan: makePlan({
      ...empty,
      state_code: "CA",
      income_streams: [{ annual_amount: 50000 }, { annual_amount: 20000 }],
      expenses: [{ annual_amount: 12000 }, { annual_amount: 6000, recurrence_years: 5 }],
      assumption_curves: [
        { curve_type: "market_return", mode: "fixed", fixed_rate: 0.05 },
        { curve_type: "inflation", mode: "curve" },
      ],
      spending_rules: { flex_threshold: -0.1, flex_reduction: 0.2, lookback_years: 3 },
      priorities: [{ id: "rule" }],
      real_assets: [{ current_value: 400000 }],
      liabilities: [{ principal_balance: 100000 }],
      drawdown_order: [
        { rank: 2, source_account_id: "ira" },
        { rank: 1, source_account_id: "cash" },
        { rank: 3, source_account_id: "unknown" },
        { rank: 4, source_account_id: "cash" },
      ],
      healthcare_settings: { enabled: true, aca_enabled: true, medicare_enabled: true },
      spouse: { name: "Alex" },
      milestones: [{ name: "Retirement" }],
      notes: "First line\nPrivate second line",
    }),
    simulation: {
      metadata: {
        milestone_outcomes: [
          { name: "Later", year: 2040 },
          { name: "Retire", year: 2030 },
          { name: "Unreached", year: null },
        ],
      },
    } as SimulationResult,
  });
  render(<PlanSectionNav activeKey={null} onEdit={vi.fn()} />);
  await screen.findByText("$30.0K · 2 types · shared");
  // Everything is configured, so nothing hides behind "Show more".
  expect(screen.queryByRole("button", { name: /more optional sections/ })).not.toBeInTheDocument();
  expect(group("Essentials")).toHaveTextContent("All set");
  for (const text of [
    "2 sources across plan years",
    "2 expenses across plan years",
    "$400.0K assets · $100.0K debt",
    "Cash → IRA → Account → …",
    "Single · born 1990 · CA",
    "Growth 5.0% · inflation custom",
    "Cut 20% · 3-yr lookback",
    "1 savings rule",
    "Marketplace + Medicare",
    "Partner: Alex",
    "Next: Retire in 2030",
    "First line",
  ])
    expect(screen.getByText(text)).toBeInTheDocument();
  expect(screen.queryByText("Private second line")).not.toBeInTheDocument();
  expect(screen.getByText("Cash → IRA → Account → …")).toHaveAttribute(
    "title",
    "Cash → IRA → Account → …",
  );
  // Sorting a summary must not reorder source simulation data.
  expect(usePlanStore.getState().simulation?.metadata.milestone_outcomes?.[0].name).toBe("Later");
});
it("shows each assumption as its own value, using engine defaults for unsaved ones", async () => {
  const onEdit = vi.fn();
  usePlanStore.setState({
    plan: makePlan({
      ...empty,
      assumption_curves: [
        { curve_type: "market_return", mode: "curve" },
        { curve_type: "wage_growth", mode: "fixed", fixed_rate: 0.025 },
        { curve_type: "cash_yield", mode: "fixed", fixed_rate: 0.035 },
      ],
      assumption_defaults: {
        inflation: 0.028,
        market_return: 0.07,
        dividend_yield: 0,
        bond_return: 0.04,
        bond_allocation: 0,
      },
    }),
  });
  render(<PlanSectionNav activeKey="assumptions" onEdit={onEdit} />);
  await screen.findByText("Add your first account");
  const card = group("Assumptions");
  const button = within(card).getByRole("button", { name: "Edit Assumptions, optional" });
  expect(button).toHaveAttribute("aria-current", "true");
  expect(button).toHaveAccessibleDescription("Growth custom curve · inflation 2.8%");
  const lines = [...card.querySelectorAll(".plan-nav-setting")].map((line) => [
    line.querySelector(".plan-nav-name")?.textContent,
    line.querySelector(".plan-nav-value")?.textContent,
  ]);
  expect(lines).toEqual([
    ["Stock growth", "Custom curve"],
    ["Inflation", "2.8%"],
    ["Dividend yield", "0.0%"],
    ["Bond return", "4.0%"],
    ["Bond allocation", "0.0%"],
    ["Wage growth", "2.5%"],
    ["Cash yield", "3.5%"],
  ]);
  expect(within(card).getByText("2.8%")).toHaveAttribute("title", "Inflation: CoastMath default");
  expect(within(card).getByText("2.5%")).not.toHaveAttribute("title");
  fireEvent.click(within(card).getByText("Bond return"));
  expect(onEdit).toHaveBeenCalledWith("assumptions");
});
it("lists only growth and inflation when the service reports no defaults", async () => {
  render(<PlanSectionNav activeKey={null} onEdit={vi.fn()} />);
  await screen.findByText("Add your first account");
  const values = [...group("Assumptions").querySelectorAll(".plan-nav-value")].map(
    (v) => v.textContent,
  );
  expect(values).toEqual(["Default", "3.0%"]);
});
it("shows loading and error rather than old balances, then refreshes on account revision", async () => {
  let finish!: (accounts: Account[]) => void;
  adapter.listAccounts
    .mockReturnValueOnce(
      new Promise<Account[]>((resolve) => {
        finish = resolve;
      }),
    )
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce([{ name: "Cash", balance: 1234, account_type: "checking" }]);
  render(<PlanSectionNav activeKey={null} onEdit={vi.fn()} />);
  act(() => usePlanStore.setState({ plan: { ...empty, id: "b" } }));
  await screen.findByText("Could not load accounts");
  await act(async () => finish([{ balance: 999999 } as Account]));
  expect(screen.queryByText(/999/)).not.toBeInTheDocument();
  act(() => usePlanStore.setState({ accountsRevision: 1 }));
  await screen.findByText("$1.2K · 1 type · shared");
});
it("handles configured alternatives, long notes and a missing plan", async () => {
  usePlanStore.setState({
    plan: makePlan({
      ...empty,
      filing_status: "custom",
      priorities: [{}, {}],
      assumption_curves: [
        { curve_type: "market_return", mode: "curve" },
        { curve_type: "inflation", mode: "fixed", fixed_rate: 0.01 },
      ],
      healthcare_settings: { enabled: true },
      spouse: { name: " " },
      milestones: [{ name: "A" }, { name: "B" }, { name: "C" }],
      notes: "n".repeat(80),
    }),
  });
  const view = render(<PlanSectionNav activeKey={null} onEdit={vi.fn()} />);
  await screen.findByText("Add your first account");
  for (const text of [
    "Growth custom curve · inflation 1.0%",
    "2 savings rules",
    "Enabled",
    "Partner: configured",
    "A, B",
    "n".repeat(63) + "…",
  ])
    expect(screen.getByText(text)).toBeInTheDocument();
  act(() => usePlanStore.setState({ plan: null }));
  expect(view.container).toBeEmptyDOMElement();
});
it("shows no milestones once the FI estimate is removed from an empty plan", async () => {
  useFiEstimateStore.setState({ hiddenByPlan: { a: true } });
  render(<PlanSectionNav activeKey={null} onEdit={vi.fn()} />);
  await screen.findByText("Add your first account");
  expect(
    screen.queryByRole("button", { name: "Edit Milestones, optional" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show 8 more optional sections" }));
  expect(screen.getByText("No milestones yet.")).toBeInTheDocument();
});
it("filters every card by title, summary, keyword and assumption value", async () => {
  const onEdit = vi.fn();
  render(<PlanSectionNav activeKey={null} onEdit={onEdit} />);
  await screen.findByText("Add your first account");
  // A keyword reaches an unconfigured section without expanding "Show more".
  fireEvent.change(filter(), { target: { value: "Mortgage" } });
  expect(editButtons().map((b) => b.getAttribute("aria-label"))).toEqual([
    "Edit Property and debt, optional",
  ]);
  expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual(["Optional"]);
  expect(screen.queryByRole("button", { name: /more optional sections/ })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("1 section matches");
  // Summaries match too, across groups.
  fireEvent.change(filter(), { target: { value: "add your" } });
  expect(editButtons().map((b) => b.getAttribute("aria-label"))).toEqual([
    "Edit Accounts",
    "Edit Income streams",
    "Edit Expenses",
  ]);
  // Every word must match, in any order.
  fireEvent.change(filter(), { target: { value: "stream income" } });
  expect(editButtons().map((b) => b.getAttribute("aria-label"))).toEqual(["Edit Income streams"]);
  // Assumption labels are searchable.
  fireEvent.change(filter(), { target: { value: "inflation" } });
  expect(editButtons().map((b) => b.getAttribute("aria-label"))).toEqual([
    "Edit Assumptions, optional",
  ]);
  // Enter opens the first match.
  fireEvent.keyDown(filter(), { key: "Enter" });
  expect(onEdit).toHaveBeenCalledWith("assumptions");
});
it("shows an empty state, and Escape or Clear restores every section", async () => {
  render(<PlanSectionNav activeKey={null} onEdit={vi.fn()} />);
  await screen.findByText("Add your first account");
  const input = filter();
  fireEvent.change(input, { target: { value: "zzz" } });
  expect(screen.getByText("No sections match “zzz”.")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("No sections match");
  expect(editButtons()).toHaveLength(0);
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show all sections" }));
  expect(input).toHaveValue("");
  expect(input).toHaveFocus();
  expect(editButtons()).toHaveLength(7);
  // The field's own clear button does the same.
  fireEvent.change(input, { target: { value: "partner" } });
  expect(editButtons()).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Clear filter" }));
  expect(input).toHaveValue("");
  expect(screen.queryByRole("button", { name: "Clear filter" })).not.toBeInTheDocument();
  expect(editButtons()).toHaveLength(7);
  fireEvent.change(input, { target: { value: "notes" } });
  expect(editButtons()).toHaveLength(1);
  const escape = fireEvent.keyDown(input, { key: "Escape" });
  expect(escape).toBe(false); // Handled here, so it cannot also close anything behind.
  expect(input).toHaveValue("");
  expect(editButtons()).toHaveLength(7);
  // Escape on an empty field leaves it.
  input.focus();
  fireEvent.keyDown(input, { key: "Escape" });
  expect(input).not.toHaveFocus();
});
it("focuses the filter with / and Cmd/Ctrl+K, except while typing elsewhere or in a dialog", async () => {
  const ui = (collapsed: boolean) => (
    <>
      <input aria-label="Other field" />
      <div hidden={collapsed}>
        <PlanSectionNav activeKey={null} onEdit={vi.fn()} />
      </div>
    </>
  );
  const view = render(ui(false));
  await screen.findByText("Add your first account");
  const input = filter();
  expect(fireEvent.keyDown(document.body, { key: "/" })).toBe(false);
  expect(input).toHaveFocus();
  input.blur();
  fireEvent.keyDown(document.body, { key: "k", metaKey: true });
  expect(input).toHaveFocus();
  input.blur();
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  expect(input).toHaveFocus();
  // Typing "/" into another field stays there.
  const other = screen.getByRole("textbox", { name: "Other field" });
  other.focus();
  expect(fireEvent.keyDown(other, { key: "/" })).toBe(true);
  expect(fireEvent.keyDown(other, { key: "k", metaKey: true })).toBe(true);
  expect(other).toHaveFocus();
  // A modal (the Edit sheet) owns the keyboard.
  other.blur();
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  document.body.appendChild(dialog);
  expect(fireEvent.keyDown(document.body, { key: "/" })).toBe(true);
  expect(input).not.toHaveFocus();
  dialog.remove();
  // A collapsed sidebar hides the field; the shortcut leaves the key alone.
  view.rerender(ui(true));
  expect(fireEvent.keyDown(document.body, { key: "/" })).toBe(true);
  expect(input).not.toHaveFocus();
  view.rerender(ui(false));
  expect(fireEvent.keyDown(document.body, { key: "/" })).toBe(false);
  input.blur();
  // The listener goes away with the component.
  view.unmount();
  expect(fireEvent.keyDown(document.body, { key: "/" })).toBe(true);
});
it("moves between rows with the arrow keys", async () => {
  render(<PlanSectionNav activeKey={null} onEdit={vi.fn()} />);
  await screen.findByText("Add your first account");
  const input = filter();
  input.focus();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  const details = screen.getByRole("button", { name: "Edit Plan details" });
  expect(details).toHaveFocus();
  fireEvent.keyDown(details, { key: "ArrowDown" });
  expect(screen.getByRole("button", { name: "Edit Accounts" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
  expect(details).toHaveFocus();
  fireEvent.keyDown(details, { key: "ArrowUp" });
  expect(input).toHaveFocus();
  // Assumptions come last, after the optional card's "Show more" row.
  fireEvent.keyDown(details, { key: "End" });
  expect(screen.getByRole("button", { name: "Edit Assumptions, optional" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
  expect(screen.getByRole("button", { name: "Show 7 more optional sections" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Home" });
  expect(details).toHaveFocus();
});
