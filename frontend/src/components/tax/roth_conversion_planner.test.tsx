import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi, it, expect } from "vitest";
import { RothConversionPlanner } from "./roth_conversion_planner";
import { usePlanStore } from "@/stores/plan_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
const mocks = vi.hoisted(() => ({ save: vi.fn(), accounts: vi.fn() }));
const adapter = makeAdapter({ listAccounts: mocks.accounts, updatePriorities: mocks.save });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
it("restricts conversion ownership, preserves payroll rules and retains failed-save inputs", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "t", name: "Traditional", account_type: "traditional_ira", owner: "self" },
    { id: "r", name: "Roth", account_type: "roth_ira", owner: "self" },
    { id: "s", name: "Spouse Roth", account_type: "roth_ira", owner: "spouse" },
  ]);
  mocks.save.mockRejectedValue(new Error("offline"));
  usePlanStore.setState({
    plan: makePlan({
      id: "p",
      spouse: { name: "Sam", birth_year: 1982 },
      priorities: [
        {
          id: "pay",
          plan_id: "p",
          priority_rank: 1,
          priority_type: "income_percent",
          source_income_id: "salary",
          employee_rate: 12,
          employer_match_rate: 5,
          target_balance: 50000,
        },
      ],
    }),
  });
  render(<RothConversionPlanner snapshots={[]} />);
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: "Traditional (Primary person)" }),
    ).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText("Traditional source"), { target: { value: "t" } });
  expect(
    within(screen.getByLabelText("Roth destination")).queryByText("Spouse Roth (Partner)"),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Roth destination"), { target: { value: "r" } });
  fireEvent.change(screen.getByLabelText("Annual conversion cap ($)"), {
    target: { value: "20000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add conversion rule" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not save"));
  expect(mocks.save).toHaveBeenCalledWith(
    "p",
    [
      expect.objectContaining({
        source_income_id: "salary",
        employee_rate: 12,
        employer_match_rate: 5,
        target_balance: 50000,
      }),
      expect.objectContaining({
        source_account_id: "t",
        target_account_id: "r",
        max_annual_amount: 20000,
      }),
    ],
    0,
  );
  expect(screen.getByLabelText("Annual conversion cap ($)")).toHaveValue("20,000");
});

it("switches a conversion rule to the plan tax target and back", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "t", name: "Traditional", account_type: "traditional_ira", owner: "self" },
    { id: "r", name: "Roth", account_type: "roth_ira", owner: "self" },
  ]);
  mocks.save.mockReset();
  mocks.save.mockResolvedValue(undefined);
  const conversion = {
    id: "c",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "roth_conversion",
    source_account_id: "t",
    target_account_id: "r",
    max_annual_amount: 30000,
    conversion_mode: "fixed",
    bracket_ceiling_rate: null,
  };
  usePlanStore.setState({
    plan: makePlan({ id: "p", priorities: [conversion] }),
    loadPlan: vi.fn(),
  } as never);
  render(<RothConversionPlanner snapshots={[]} />);
  const toggle = await screen.findByRole("checkbox", { name: "Use plan tax target" });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  fireEvent.click(toggle);
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        expect.objectContaining({
          conversion_mode: "fill_bracket",
          use_plan_tax_target: true,
          max_annual_amount: 30000,
        }),
      ],
      0,
    ),
  );
});

it("returns a target-sized rule without its own bracket to its fallback", async () => {
  const { withPlanTarget } = await import("./roth_conversion_planner");
  const base = {
    plan_id: "p",
    priority_rank: 1,
    target_account_id: null,
    max_annual_amount: null,
    source_income_id: null,
    employee_rate: 0,
    employer_match_rate: 0,
    target_balance: null,
    conversion_mode: "fill_bracket" as const,
    bracket_ceiling_rate: null,
    use_plan_tax_target: true,
  };
  const items = [
    { ...base, id: "c", priority_type: "roth_conversion", source_account_id: "t" },
    { ...base, id: "h", priority_type: "gain_harvest", source_account_id: "b", priority_rank: 2 },
  ];
  expect(withPlanTarget(items, "c", false)[0]).toMatchObject({
    conversion_mode: "fixed",
    use_plan_tax_target: false,
  });
  expect(withPlanTarget(items, "h", false)[1]).toMatchObject({
    conversion_mode: "fill_bracket",
    bracket_ceiling_rate: 0,
    use_plan_tax_target: false,
  });
});

it("labels a conversion ceiling the plan's brackets no longer include", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "t", name: "Traditional", account_type: "traditional_ira", owner: "self" },
    { id: "r", name: "Roth", account_type: "roth_ira", owner: "self" },
  ]);
  const rule = (id: string, rate: number) => ({
    id,
    plan_id: "p",
    priority_rank: 1,
    priority_type: "roth_conversion",
    source_account_id: "t",
    target_account_id: "r",
    max_annual_amount: null,
    conversion_mode: "fill_bracket",
    bracket_ceiling_rate: rate,
  });
  usePlanStore.setState({
    plan: makePlan({
      id: "p",
      priorities: [rule("a", 0.12), rule("b", 0.2)],
      tax_settings: {
        federal_brackets: [
          [50000, 0.1],
          [1e9, 0.2],
        ],
      },
    }),
  });
  render(<RothConversionPlanner snapshots={[]} />);
  expect(
    await screen.findByText(/fill to the 12% bracket \(not in this plan's brackets\)/),
  ).toBeInTheDocument();
  expect(screen.getByText(/fill to the 20% bracket \/ year/)).toBeInTheDocument();
});

it("names the person who lacks a Roth account by label, not by owner value", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "t", name: "Traditional", account_type: "traditional_ira", owner: "spouse" },
    { id: "r", name: "Roth", account_type: "roth_ira", owner: "self" },
  ]);
  usePlanStore.setState({ plan: makePlan({ id: "p", spouse: { name: "Sam", birth_year: 1982 } }) });
  render(<RothConversionPlanner snapshots={[]} />);
  await screen.findByRole("option", { name: "Traditional (Partner)" });
  fireEvent.change(screen.getByLabelText("Traditional source"), { target: { value: "t" } });
  expect(screen.getByRole("status")).toHaveTextContent(
    "No Roth account belongs to the partner. Add a Roth account for the same person",
  );
});
