import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, it, expect, beforeEach, describe } from "vitest";
import { usePlanStore } from "@/stores/plan_store";
import SavingsPrioritiesPanel from "./savings_priorities_panel";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
const mocks = vi.hoisted(() => ({ save: vi.fn(), accounts: vi.fn(), fetch: vi.fn() }));
const adapter = makeAdapter({
  listAccounts: mocks.accounts,
  updatePriorities: mocks.save,
  fetchPlan: mocks.fetch,
});
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
beforeEach(() => {
  sessionStorage.clear();
  mocks.fetch.mockReset().mockRejectedValue(new Error("offline"));
  usePlanStore.setState({ plan: null, simulation: null, isSimulating: false });
});

it("keeps payroll movement within its visible group and retains fields on failed save", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "a", name: "401k", account_type: "traditional_401k" },
    { id: "b", name: "Cash", account_type: "savings" },
  ]);
  mocks.save.mockRejectedValue(new Error("offline"));
  const payroll = {
    id: "1",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "income_percent",
    target_account_id: "a",
    source_income_id: "salary",
    employee_rate: 12,
    employer_match_rate: 5,
    max_annual_amount: 20000,
  };
  const reserve = {
    id: "2",
    plan_id: "p",
    priority_rank: 2,
    priority_type: "contribution",
    target_account_id: "b",
    target_balance: 50000,
  };
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [payroll, reserve],
        income_streams: [{ id: "salary", name: "Salary", is_earned_income: true }],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  expect(screen.getByRole("button", { name: "Move rule 1 down" })).toBeDisabled();
  fireEvent.change(screen.getAllByLabelText("Annual maximum ($; optional)")[0], {
    target: { value: "3000" },
  });
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("Your edits are retained"),
  );
  expect(mocks.save).toHaveBeenCalledWith(
    "p",
    [
      expect.objectContaining({
        priority_rank: 1,
        source_income_id: "salary",
        employee_rate: 12,
        employer_match_rate: 5,
        max_annual_amount: 20000,
      }),
      expect.objectContaining({ priority_rank: 2, target_balance: 50000, max_annual_amount: 3000 }),
    ],
    0,
  );
  expect(screen.getByRole("button", { name: "Save allocation" })).toBeEnabled();
});

it("saves percentage, cash amount and remaining rules with independent maximums", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "a", name: "Investments", account_type: "taxable_brokerage" },
  ]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  render(<SavingsPrioritiesPanel plan={makePlan({ id: "p" })} />);
  const add = await screen.findByRole("button", { name: "Add allocation" });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  fireEvent.change(screen.getByLabelText("Destination account"), { target: { value: "a" } });
  fireEvent.change(screen.getByLabelText("Allocate"), { target: { value: "percentage" } });
  fireEvent.change(screen.getByLabelText("Surplus percentage (%)"), { target: { value: "60" } });
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "10000" },
  });
  fireEvent.click(add);
  fireEvent.change(screen.getAllByLabelText("Destination account")[1], { target: { value: "a" } });
  fireEvent.change(screen.getAllByLabelText("Allocate")[1], { target: { value: "amount" } });
  fireEvent.change(screen.getByLabelText("Annual allocation ($)"), { target: { value: "1200" } });
  fireEvent.click(add);
  fireEvent.change(screen.getAllByLabelText("Destination account")[2], { target: { value: "a" } });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        expect.objectContaining({
          allocation_mode: "percentage",
          allocation_value: 60,
          max_annual_amount: 10000,
        }),
        expect.objectContaining({ allocation_mode: "amount", allocation_value: 1200 }),
        expect.objectContaining({ allocation_mode: "remaining", allocation_value: null }),
      ],
      0,
    ),
  );
  expect(await screen.findByText(/Allocation saved\./)).toBeVisible();
});

it("blocks changing legacy 401k funding and focuses an actionable error", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "a", name: "Work plan", account_type: "traditional_401k" },
  ]);
  mocks.save.mockReset();
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [{ id: "r", priority_rank: 1, target_account_id: "a" }],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "10000" },
  });
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "401(k) contributions must come from payroll",
  );
  expect(mocks.save).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Use payroll for this 401(k)" }));
  expect(screen.getByLabelText("Source income")).toBeRequired();
  expect(screen.getByLabelText("Priority type")).toHaveValue("pre_tax_contribution");
});

it("saves other allocations and reordering with unchanged legacy 401k funding", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "a", name: "Work plan", account_type: "traditional_401k" },
    { id: "b", name: "Cash", account_type: "savings" },
  ]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [
          { id: "r", priority_rank: 1, target_account_id: "a", max_annual_amount: 23500 },
          { id: "cash", priority_rank: 2, target_account_id: "b", max_annual_amount: 20000 },
        ],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getAllByLabelText("Annual maximum ($; optional)")[1], {
    target: { value: "3000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Move rule 1 down" }));
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        expect.objectContaining({ target_account_id: "b", max_annual_amount: 3000 }),
        expect.objectContaining({ target_account_id: "a", max_annual_amount: 23500 }),
      ],
      0,
    ),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("offers account-load retry and refreshes account choices after account edits", async () => {
  mocks.accounts
    .mockReset()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue([{ id: "b", name: "New savings", account_type: "savings" }]);
  render(<SavingsPrioritiesPanel plan={makePlan({ id: "p" })} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load accounts");
  fireEvent.click(screen.getByRole("button", { name: "Retry loading accounts" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Add allocation" }));
  expect(screen.getByRole("option", { name: "New savings" })).toBeInTheDocument();
});

it("keeps confirmation and refreshes the forecast after saving, without reloading the editor", async () => {
  const priorities = [
    { id: "cash", plan_id: "p", priority_rank: 1, target_account_id: "b", max_annual_amount: 3000 },
  ];
  const plan = makePlan({ id: "p", priorities: [{ ...priorities[0], max_annual_amount: 20000 }] });
  mocks.accounts.mockResolvedValue([{ id: "b", name: "Cash", account_type: "savings" }]);
  mocks.save.mockReset().mockResolvedValue({ items: priorities, revision: 1 });
  const run = vi.spyOn(usePlanStore.getState(), "runSimulation").mockResolvedValue();
  usePlanStore.setState({ plan });
  function ConnectedEditor() {
    const current = usePlanStore((s) => s.plan);
    return <SavingsPrioritiesPanel plan={current!} />;
  }
  render(<ConnectedEditor />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "3000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() => expect(run).toHaveBeenCalledWith("p"));
  expect(await screen.findByText(/Allocation saved\./)).toBeVisible();
  expect(screen.getByLabelText("Annual maximum ($; optional)")).toHaveValue("3,000");
  expect(screen.getByRole("button", { name: "Retry projection" })).toBeInTheDocument();
  run.mockRestore();
});

it("recovers drafts across reload and plan switches, scopes by user, and reconciles newer rules explicitly", async () => {
  const plan = makePlan({
    id: "recover",
    user_id: "u",
    priorities_revision: 4,
    priorities: [{ id: "r", priority_rank: 1, target_account_id: "b", max_annual_amount: 2000 }],
  });
  mocks.accounts.mockResolvedValue([{ id: "b", name: "Cash", account_type: "savings" }]);
  mocks.save.mockReset();
  const view = render(<SavingsPrioritiesPanel plan={plan} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "3333" },
  });
  view.rerender(<SavingsPrioritiesPanel plan={{ ...plan, id: "other" }} />);
  expect(screen.getByLabelText("Annual maximum ($; optional)")).toHaveValue("2,000");
  view.rerender(<SavingsPrioritiesPanel plan={plan} />);
  expect(screen.getByLabelText("Annual maximum ($; optional)")).toHaveValue("3,333");
  expect(screen.getByText(/Unsaved draft recovered/)).toBeVisible();
  view.unmount();
  const latest = {
    ...plan,
    priorities_revision: 5,
    priorities: [{ ...plan.priorities[0], max_annual_amount: 4444 }],
  };
  render(<SavingsPrioritiesPanel plan={latest} />);
  expect(screen.getByLabelText("Annual maximum ($; optional)")).toHaveValue("3,333");
  expect(screen.getByRole("region", { name: "Review allocation conflict" })).toHaveTextContent(
    "$4,444",
  );
  expect(screen.getByRole("button", { name: "Save allocation" })).toBeDisabled();
  expect(mocks.save).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Keep my draft after reviewing these rules" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save allocation" })).toBeEnabled(),
  );
  mocks.save.mockResolvedValue({ items: latest.priorities, revision: 6 });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "recover",
      [expect.objectContaining({ max_annual_amount: 3333 })],
      5,
    ),
  );
  await waitFor(() => expect(sessionStorage.getItem("allocation-draft:v1:u:recover")).toBeNull());
});

it("moves surplus rules across intervening payroll slots visibly and retains payroll timing", async () => {
  const rules = [
    { id: "a", priority_rank: 1, target_account_id: "a" },
    {
      id: "pay",
      priority_rank: 2,
      target_account_id: "work",
      priority_type: "income_percent",
      source_income_id: "salary",
      employee_rate: 10,
    },
    { id: "b", priority_rank: 3, target_account_id: "b" },
  ];
  mocks.accounts.mockResolvedValue([
    { id: "a", name: "First", account_type: "savings" },
    { id: "b", name: "Second", account_type: "savings" },
    { id: "work", name: "Work", account_type: "traditional_401k" },
  ]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "mixed",
        priorities: rules,
        income_streams: [{ id: "salary", is_earned_income: true }],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  // Each list numbers its own rules: the payroll rule leaves no gap among the after-spending ones.
  expect(
    screen.getByRole("button", { name: "Move payroll or transfer rule 1 down" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Move rule 2 up" }));
  expect(ruleTitles()).toEqual(["1. Second", "2. First"]);
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "mixed",
      [
        expect.objectContaining({ target_account_id: "b", priority_rank: 1 }),
        expect.objectContaining({ target_account_id: "work", priority_rank: 2 }),
        expect.objectContaining({ target_account_id: "a", priority_rank: 3 }),
      ],
      0,
    ),
  );
});

it("isolates recovered drafts by user and warns only while changes are unsaved", async () => {
  const plan = makePlan({
    id: "scope",
    user_id: "one",
    priorities_revision: 2,
    priorities: [{ id: "r", priority_rank: 1, target_account_id: "b", max_annual_amount: 100 }],
  });
  mocks.accounts.mockResolvedValue([{ id: "b", name: "Cash", account_type: "savings" }]);
  mocks.save.mockReset().mockRejectedValueOnce(new Error("offline"));
  const view = render(<SavingsPrioritiesPanel plan={plan} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "222" },
  });
  const warning = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(warning);
  expect(warning.defaultPrevented).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await screen.findByRole("alert");
  expect(JSON.parse(sessionStorage.getItem("allocation-draft:v1:one:scope")!).revision).toBe(2);
  view.rerender(<SavingsPrioritiesPanel plan={{ ...plan, user_id: "two" }} />);
  expect(screen.getByLabelText("Annual maximum ($; optional)")).toHaveValue("100");
  expect(screen.queryByText(/Unsaved draft recovered/)).not.toBeInTheDocument();
  view.rerender(<SavingsPrioritiesPanel plan={plan} />);
  expect(screen.getByLabelText("Annual maximum ($; optional)")).toHaveValue("222");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save allocation" })).toBeEnabled(),
  );
  mocks.save.mockResolvedValue({ items: plan.priorities, revision: 3 });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await screen.findByText(/Allocation saved/);
  const savedWarning = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(savedWarning);
  expect(savedWarning.defaultPrevented).toBe(false);
});

it.each([4, 5])(
  "discards a draft against saved revision %s without submitting or recovering it",
  async (latestRevision) => {
    const plan = makePlan({
      id: "discard",
      user_id: "u",
      priorities_revision: 4,
      priorities: [{ id: "r", priority_rank: 1, target_account_id: "b", max_annual_amount: 20000 }],
    });
    const latest = { ...plan, priorities_revision: latestRevision };
    mocks.accounts.mockResolvedValue([{ id: "b", name: "Cash", account_type: "savings" }]);
    mocks.fetch.mockResolvedValue(latest);
    mocks.save.mockReset();
    usePlanStore.setState({ plan });
    function Connected() {
      const current = usePlanStore((s) => s.plan)!;
      return <SavingsPrioritiesPanel plan={current} />;
    }
    const view = render(<Connected />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled(),
    );
    fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
      target: { value: "19000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review latest saved rules" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Use latest rules and discard my draft" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save allocation" })).toBeDisabled(),
    );
    expect(screen.getByLabelText("Annual maximum ($; optional)")).toHaveValue("20,000");
    expect(sessionStorage.getItem("allocation-draft:v1:u:discard")).toBeNull();
    expect(screen.queryByText(/Unsaved changes/)).not.toBeInTheDocument();
    const warning = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(warning);
    expect(warning.defaultPrevented).toBe(false);
    expect(mocks.save).not.toHaveBeenCalled();
    view.unmount();
    render(<Connected />);
    expect(screen.queryByText(/Unsaved draft recovered/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Annual maximum ($; optional)")).toHaveValue("20,000");
  },
);

it("offers a backdoor Roth toggle on Roth IRA surplus rules and saves it", async () => {
  mocks.accounts.mockResolvedValue([{ id: "r", name: "Roth IRA", account_type: "roth_ira" }]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [
          { id: "1", priority_rank: 1, priority_type: "contribution", target_account_id: "r" },
        ],
      })}
    />,
  );
  const toggle = await screen.findByLabelText(/Backdoor Roth/);
  expect(toggle).not.toBeChecked();
  expect(screen.getByText(/Income eligibility and shared IRA limits apply/)).toBeInTheDocument();
  fireEvent.click(toggle);
  expect(screen.getByText(/IRA limits and pro-rata taxation apply/)).toBeInTheDocument();
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [expect.objectContaining({ target_account_id: "r", backdoor_roth: true })],
      0,
    ),
  );
});

it("describes the traditional IRA deduction as phased out by income and workplace-plan coverage", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "t", name: "Traditional IRA", account_type: "traditional_ira" },
  ]);
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [
          { id: "1", priority_rank: 1, priority_type: "contribution", target_account_id: "t" },
        ],
      })}
    />,
  );
  expect(
    await screen.findByText(
      /Deductible, but phased out by income when the owner or their spouse contributes to a workplace plan/,
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/treated as nondeductible/)).not.toBeInTheDocument();
});

it("adds a Max 401(k) payroll rule with no annual maximum from the owner's largest earned income", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "a", name: "Work", account_type: "traditional_401k", owner: "self" },
    { id: "s", name: "Partner Roth", account_type: "roth_401k", owner: "spouse" },
    { id: "b", name: "Cash", account_type: "savings", owner: "self" },
  ]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  const incomes = [
    {
      id: "side",
      name: "Side gig",
      annual_amount: 20000,
      is_active: true,
      is_earned_income: true,
      owner: "self",
    },
    {
      id: "salary",
      name: "Salary",
      annual_amount: 180000,
      is_active: true,
      is_earned_income: true,
      owner: "self",
    },
    {
      id: "ss",
      name: "Partner SS",
      annual_amount: 30000,
      is_active: true,
      is_earned_income: false,
      is_social_security: true,
      owner: "spouse",
    },
  ];
  render(<SavingsPrioritiesPanel plan={makePlan({ id: "p", income_streams: incomes })} />);
  const max = await screen.findByRole("button", { name: "Max 401(k) · Work" });
  expect(
    screen.queryByRole("button", { name: /Max 401\(k\) · Partner Roth/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(max);
  expect(screen.queryByRole("button", { name: /Max 401\(k\)/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        {
          priority_rank: 1,
          priority_type: "pre_tax_contribution",
          target_account_id: "a",
          source_income_id: "salary",
          allocation_mode: "remaining",
          allocation_value: null,
          max_annual_amount: null,
        },
      ],
      0,
    ),
  );
});

it("saves a mega backdoor Roth rule from W-2 wages into a Roth 401(k) and explains an unfunded year", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "t", name: "401k", account_type: "traditional_401k" },
    { id: "r", name: "Roth 401k", account_type: "roth_401k" },
  ]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  const rule = {
    id: "1",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "after_tax_401k",
    target_account_id: "r",
    source_income_id: "salary",
    employee_rate: 0,
    employer_match_rate: 0,
    max_annual_amount: null,
  };
  usePlanStore.setState({
    simulation: {
      yearly_snapshots: [
        {
          cash_flow: {
            contributions: [
              {
                name: "Roth 401k",
                account_id: "r",
                amount: 0,
                source: "payroll",
                priority_rank: 1,
                funding_reasons: ["contribution_limit"],
              },
            ],
          },
        },
      ],
    } as never,
  });
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [rule],
        income_streams: [
          { id: "salary", name: "Salary", is_earned_income: true },
          { id: "biz", name: "Consulting", is_earned_income: true, is_self_employed: true },
        ],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  expect(screen.getByLabelText("Priority type")).toHaveValue("after_tax_401k");
  expect(screen.getByText(/mega backdoor Roth$/)).toBeInTheDocument();
  expect(screen.getByText("Fills the 415(c) room left by the rules above.")).toBeInTheDocument();
  expect(screen.getByText(/contribution limit has been reached/)).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "401k" })).toBeDisabled();
  expect(screen.queryByRole("option", { name: "Consulting" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Employee contribution (%)")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "30000" },
  });
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        expect.objectContaining({
          priority_type: "after_tax_401k",
          target_account_id: "r",
          source_income_id: "salary",
          max_annual_amount: 30000,
        }),
      ],
      0,
    ),
  );
});

it("rejects a mega backdoor Roth rule funded by self-employment income", async () => {
  mocks.accounts.mockResolvedValue([{ id: "r", name: "Roth 401k", account_type: "roth_401k" }]);
  mocks.save.mockReset();
  const rule = {
    id: "1",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "after_tax_401k",
    target_account_id: "r",
    source_income_id: "biz",
  };
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [rule],
        income_streams: [
          { id: "biz", name: "Consulting", is_earned_income: true, is_self_employed: true },
        ],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "1000" },
  });
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "choose a Roth 401(k) and W-2 wages belonging to the same person",
  );
  expect(mocks.save).not.toHaveBeenCalled();
});

it("sets a rule's start and end milestones and keeps the draft through a conflict review", async () => {
  const milestones = [
    { id: "ret", name: "Retirement" },
    { id: "fi", name: "Financial independence" },
  ];
  const payroll = {
    id: "pay",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "income_percent",
    target_account_id: "work",
    source_income_id: "salary",
    employee_rate: 10,
    start_milestone_id: null,
    end_milestone_id: null,
  };
  const plan = makePlan({
    id: "p",
    user_id: "u",
    priorities_revision: 2,
    priorities: [payroll],
    milestones,
    income_streams: [{ id: "salary", name: "Salary", is_earned_income: true }],
  });
  mocks.accounts.mockResolvedValue([
    { id: "work", name: "Work", account_type: "traditional_401k" },
  ]);
  mocks.save.mockReset().mockRejectedValue(new Error("Rules changed elsewhere."));
  const latest = {
    ...plan,
    priorities_revision: 3,
    priorities: [{ ...payroll, end_milestone_id: "fi" }],
  };
  mocks.fetch.mockReset().mockResolvedValue(latest);
  const run = vi.spyOn(usePlanStore.getState(), "runSimulation").mockResolvedValue();
  usePlanStore.setState({ plan });
  function ConnectedEditor() {
    const current = usePlanStore((s) => s.plan);
    return <SavingsPrioritiesPanel plan={current!} />;
  }
  render(<ConnectedEditor />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  expect(screen.getByLabelText("Start milestone")).toHaveValue("");
  expect(screen.getByRole("option", { name: "End of plan" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("End milestone"), { target: { value: "ret" } });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [expect.objectContaining({ start_milestone_id: null, end_milestone_id: "ret" })],
      2,
    ),
  );
  const review = await screen.findByRole("region", { name: "Review allocation conflict" });
  expect(review).toHaveTextContent("ends Financial independence");
  expect(screen.getByLabelText("End milestone")).toHaveValue("ret");
  expect(screen.getByRole("button", { name: "Save allocation" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Keep my draft after reviewing these rules" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save allocation" })).toBeEnabled(),
  );
  mocks.save
    .mockReset()
    .mockResolvedValue({ items: [{ ...payroll, end_milestone_id: "ret" }], revision: 4 });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [expect.objectContaining({ end_milestone_id: "ret" })],
      3,
    ),
  );
  run.mockRestore();
});

it("funds 403(b) and 457(b) plans from payroll and keeps a 401(a) employer-only", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "b", name: "Teacher plan", account_type: "traditional_403b", owner: "self" },
    { id: "g", name: "Deferred comp", account_type: "roth_457b", owner: "self" },
    { id: "a", name: "Pension plan", account_type: "traditional_401a", owner: "self" },
  ]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  const salary = {
    id: "salary",
    name: "Salary",
    annual_amount: 90000,
    is_active: true,
    is_earned_income: true,
    owner: "self",
  };
  const employee401a = {
    id: "r",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "income_percent",
    target_account_id: "a",
    source_income_id: "salary",
    employee_rate: 5,
    employer_match_rate: 10,
  };
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({ id: "p", priorities: [employee401a], income_streams: [salary] })}
    />,
  );
  expect(
    await screen.findByRole("button", { name: "Max 403(b) · Teacher plan" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Max 457(b) · Deferred comp" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Max 401\(a\)/ })).not.toBeInTheDocument();
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent("a 401(a) takes employer contributions only");
  expect(mocks.save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Employee contribution (%)"), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Max 403(b) · Teacher plan" }));
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        expect.objectContaining({
          target_account_id: "a",
          employee_rate: 0,
          employer_match_rate: 10,
        }),
        expect.objectContaining({
          priority_type: "pre_tax_contribution",
          target_account_id: "b",
          source_income_id: "salary",
        }),
      ],
      0,
    ),
  );
});

it("saves a tiered employer match formula and a lower plan limit on a payroll rule", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "a", name: "401k", account_type: "traditional_401k" },
    { id: "r", name: "Roth 401k", account_type: "roth_401k" },
  ]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  const payroll = {
    id: "1",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "income_percent",
    target_account_id: "a",
    source_income_id: "salary",
    employee_rate: 6,
    employer_match_rate: 4,
    max_annual_amount: null,
  };
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [payroll],
        income_streams: [{ id: "salary", name: "Salary", is_earned_income: true }],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Employer contribution"), {
    target: { value: "formula" },
  });
  expect(screen.queryByLabelText("Employer contribution (% of income)")).toBeNull();
  fireEvent.change(screen.getByLabelText("of the next (% of pay)"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Add match tier" }));
  fireEvent.change(screen.getByLabelText("Annual employer cap ($, today’s dollars; optional)"), {
    target: { value: "5000" },
  });
  fireEvent.click(screen.getByLabelText("True up the match at year end"));
  fireEvent.click(screen.getByLabelText("Roth employer contributions"));
  fireEvent.change(screen.getByLabelText("Contribution limit"), { target: { value: "custom" } });
  fireEvent.change(screen.getByLabelText("Plan annual limit ($, today’s dollars)"), {
    target: { value: "15000" },
  });
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        expect.objectContaining({
          employer_match_rate: 0,
          employer_match: {
            tiers: [
              { match_percent: 100, up_to_percent_of_pay: 3 },
              { match_percent: 50, up_to_percent_of_pay: 2 },
            ],
            cap_amount: 5000,
            nonelective_percent: 0,
            true_up: false,
            roth: true,
          },
          limit_mode: "custom",
          custom_annual_limit: 15000,
        }),
      ],
      0,
    ),
  );
});

it("blocks a Roth employer match without a Roth account in the same plan", async () => {
  mocks.accounts.mockResolvedValue([{ id: "a", name: "401k", account_type: "traditional_401k" }]);
  mocks.save.mockReset();
  const payroll = {
    id: "1",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "income_percent",
    target_account_id: "a",
    source_income_id: "salary",
    employee_rate: 6,
    employer_match_rate: 0,
    employer_match: {
      tiers: [{ match_percent: 100, up_to_percent_of_pay: 6 }],
      true_up: true,
      roth: true,
    },
  };
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [payroll],
        income_streams: [{ id: "salary", name: "Salary", is_earned_income: true }],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Employee contribution (%)"), { target: { value: "8" } });
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent("add a Roth 401(k) for the same person");
  expect(mocks.save).not.toHaveBeenCalled();
});

const loans = [
  { id: "loan-1", name: "Car loan" },
  { id: "loan-2", name: "Student loan" },
];

it("adds a debt payment rule that targets a loan and saves it without a destination account", async () => {
  mocks.accounts.mockResolvedValue([{ id: "b", name: "Cash", account_type: "savings" }]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  render(<SavingsPrioritiesPanel plan={makePlan({ id: "p", liabilities: loans })} />);
  const add = await screen.findByRole("button", { name: "Add debt payment" });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  expect(screen.queryByLabelText("Destination account")).toBeNull();
  expect(screen.queryByLabelText("Stop at account balance ($; optional)")).toBeNull();
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent("choose the loan");
  expect(mocks.save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Loan to pay down"), { target: { value: "loan-2" } });
  expect(screen.getByText(/Pay down Student loan/, { selector: "summary" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "2400" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        expect.objectContaining({
          priority_type: "debt_payment",
          target_liability_id: "loan-2",
          max_annual_amount: 2400,
          priority_rank: 1,
        }),
      ],
      0,
    ),
  );
});

it("hides the debt payment button when the plan has no loans and ranks debt rules with surplus rules", async () => {
  mocks.accounts.mockResolvedValue([{ id: "b", name: "Cash", account_type: "savings" }]);
  const rules = [
    {
      id: "d",
      plan_id: "p",
      priority_rank: 1,
      priority_type: "debt_payment",
      target_liability_id: "loan-1",
      allocation_mode: "remaining",
    },
    {
      id: "c",
      plan_id: "p",
      priority_rank: 2,
      priority_type: "contribution",
      target_account_id: "b",
      allocation_mode: "remaining",
    },
  ];
  const { unmount } = render(
    <SavingsPrioritiesPanel plan={makePlan({ id: "p", priorities: rules, liabilities: loans })} />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  expect(screen.getByText(/^1\. Pay down Car loan/, { selector: "summary" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Move rule 1 down" })).toBeEnabled();
  unmount();
  render(<SavingsPrioritiesPanel plan={makePlan({ id: "p2" })} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  expect(screen.queryByRole("button", { name: "Add debt payment" })).toBeNull();
});

it("explains an invalid transfer pairing before saving and allows a same-owner rollover", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "ira1", name: "Old IRA", account_type: "traditional_ira", owner: "self" },
    { id: "k1", name: "Old 401k", account_type: "traditional_401k", owner: "self" },
    { id: "roth", name: "Roth", account_type: "roth_ira", owner: "self" },
    { id: "cash", name: "Cash", account_type: "savings", owner: "self" },
  ]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  const transfer = (source: string, target: string, rank: number) => ({
    id: `t${rank}`,
    plan_id: "p",
    priority_rank: rank,
    priority_type: "transfer",
    source_account_id: source,
    target_account_id: target,
    allocation_mode: "remaining",
  });
  const bad = render(
    <SavingsPrioritiesPanel
      plan={makePlan({ id: "p", priorities: [transfer("cash", "roth", 1)] })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "100" },
  });
  fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent("contribution, not a transfer");
  expect(mocks.save).not.toHaveBeenCalled();
  bad.unmount();
  sessionStorage.clear();
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({ id: "p3", priorities: [transfer("ira1", "k1", 1)] })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
    target: { value: "100" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p3",
      [
        expect.objectContaining({
          priority_type: "transfer",
          source_account_id: "ira1",
          target_account_id: "k1",
        }),
      ],
      0,
    ),
  );
});

it("lists withdraw-if-short rules first, keeps their rank and keeps the draft through a 409 review", async () => {
  const cash = {
    id: "c",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "contribution",
    target_account_id: "sav",
  };
  const goal = {
    id: "g",
    plan_id: "p",
    priority_rank: 2,
    priority_type: "contribution",
    target_account_id: "brok",
    allocation_mode: "amount",
    allocation_value: 3000,
  };
  const plan = makePlan({
    id: "p",
    user_id: "u",
    priorities_revision: 5,
    priorities: [cash, goal],
  });
  mocks.accounts.mockResolvedValue([
    { id: "sav", name: "Savings", account_type: "savings" },
    { id: "brok", name: "Brokerage", account_type: "taxable_brokerage" },
  ]);
  const conflict = Object.assign(new Error("Allocation changed since you started editing."), {
    status: 409,
  });
  mocks.save.mockReset().mockRejectedValue(conflict);
  mocks.fetch.mockReset().mockResolvedValue({
    ...plan,
    priorities_revision: 6,
    priorities: [cash, { ...goal, allocation_value: 4000 }],
  });
  const run = vi.spyOn(usePlanStore.getState(), "runSimulation").mockResolvedValue();
  usePlanStore.setState({ plan });
  function ConnectedEditor() {
    const current = usePlanStore((s) => s.plan);
    return <SavingsPrioritiesPanel plan={current!} />;
  }
  render(<ConnectedEditor />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  const funding = screen.getAllByLabelText("Withdraw if surplus is short");
  expect(funding[1]).not.toBeChecked();
  fireEvent.click(funding[1]);
  const rules = screen.getAllByRole("region", { name: /Allocation rule/ });
  expect(rules[0]).toHaveAccessibleName("Allocation rule 1");
  expect(rules[0]).toHaveTextContent("withdraws if short");
  expect(rules[0]).toHaveTextContent("drawn from your withdrawal order");
  // The withdraw-if-short rule cannot be moved below an income-funded rule.
  expect(screen.getByRole("button", { name: "Move rule 1 up" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Move rule 2 down" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [
        expect.objectContaining({ priority_rank: 1, target_account_id: "sav" }),
        expect.objectContaining({
          priority_rank: 2,
          target_account_id: "brok",
          withdraw_if_short: true,
          reduce_employer_contribution: false,
        }),
      ],
      5,
    ),
  );
  const review = await screen.findByRole("region", { name: "Review allocation conflict" });
  // The review renders above the editor, far from the Save button: it takes focus.
  await waitFor(() => expect(review).toHaveFocus());
  // Listed in the editor's group and wording, with the changed rule marked.
  expect(review).toHaveTextContent("After spending");
  expect(review).toHaveTextContent("Brokerage · $4,000 a year · differs from your draft");
  expect(review).not.toHaveTextContent("Savings · remaining surplus · differs");
  expect(screen.getAllByLabelText("Withdraw if surplus is short")[0]).toBeChecked();
  fireEvent.click(
    screen.getByRole("button", { name: "Keep my draft after reviewing these rules" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save allocation" })).toBeEnabled(),
  );
  mocks.save
    .mockReset()
    .mockResolvedValue({ items: [cash, { ...goal, withdraw_if_short: true }], revision: 7 });
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      expect.arrayContaining([expect.objectContaining({ withdraw_if_short: true })]),
      6,
    ),
  );
  run.mockRestore();
});

it("offers reduced employer contributions only on income-funded flat-rate payroll rules", async () => {
  const payroll = {
    id: "1",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "income_percent",
    target_account_id: "a",
    source_income_id: "salary",
    employee_rate: 6,
    employer_match_rate: 3,
  };
  mocks.accounts.mockResolvedValue([{ id: "a", name: "401k", account_type: "traditional_401k" }]);
  mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [payroll],
        income_streams: [{ id: "salary", name: "Salary", is_earned_income: true }],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  const reduce = screen.getByLabelText("Prorate employer contribution if the deferral is cut");
  fireEvent.click(reduce);
  fireEvent.click(screen.getByLabelText("Withdraw if surplus is short"));
  expect(
    screen.queryByLabelText("Prorate employer contribution if the deferral is cut"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Withdraw if surplus is short"));
  fireEvent.click(screen.getByLabelText("Prorate employer contribution if the deferral is cut"));
  fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
  await waitFor(() =>
    expect(mocks.save).toHaveBeenCalledWith(
      "p",
      [expect.objectContaining({ withdraw_if_short: false, reduce_employer_contribution: true })],
      0,
    ),
  );
});

it("offers no funding choice on transfers", async () => {
  // A fresh render: changing the type right after a save races the save's form reset.
  const payroll = {
    id: "1",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "income_percent",
    target_account_id: "a",
    source_income_id: "salary",
    employee_rate: 6,
    employer_match_rate: 3,
  };
  mocks.accounts.mockResolvedValue([{ id: "a", name: "401k", account_type: "traditional_401k" }]);
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [payroll],
        income_streams: [{ id: "salary", name: "Salary", is_earned_income: true }],
      })}
    />,
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  expect(screen.getByLabelText("Withdraw if surplus is short")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Priority type"), { target: { value: "transfer" } });
  expect(screen.queryByLabelText("Withdraw if surplus is short")).not.toBeInTheDocument();
});

describe("Roth conversion and gain harvest rules by tax country", () => {
  const accounts = [
    { id: "ira", name: "IRA", account_type: "traditional_ira", owner: "self" },
    { id: "roth", name: "Roth", account_type: "roth_ira", owner: "self" },
    { id: "cash", name: "Cash", account_type: "savings" },
  ];
  const bracketConversion = {
    id: "c",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "roth_conversion",
    conversion_mode: "fill_bracket",
    bracket_ceiling_rate: 0.22,
    source_account_id: "ira",
    target_account_id: "roth",
  };
  const transfer = {
    id: "t",
    plan_id: "p",
    priority_rank: 1,
    priority_type: "transfer",
    source_account_id: "cash",
    target_account_id: "roth",
  };
  const abroad = {
    id: "r",
    plan_id: "p",
    country: "NZ",
    region: null,
    state_code: null,
    start_year: 2030,
    start_milestone_id: null,
  };
  const optionValues = () =>
    [...(screen.getByLabelText("Priority type") as HTMLSelectElement).options].map((o) => o.value);
  beforeEach(() => {
    mocks.accounts.mockResolvedValue(accounts);
    mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
  });

  it("offers both in a US plan without a note", async () => {
    render(<SavingsPrioritiesPanel plan={makePlan({ id: "p", priorities: [transfer] })} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled(),
    );
    expect(optionValues()).toEqual(expect.arrayContaining(["roth_conversion", "gain_harvest"]));
    expect(
      screen.queryByText(/apply only in the years you live in the US/),
    ).not.toBeInTheDocument();
  });

  it("hides both for new rules in a plan with no US year", async () => {
    render(
      <SavingsPrioritiesPanel
        plan={makePlan({ id: "p", tax_country: "NZ", priorities: [transfer] })}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled(),
    );
    expect(optionValues()).not.toContain("roth_conversion");
    expect(optionValues()).not.toContain("gain_harvest");
  });

  it("flags a saved bracket-filling conversion in a plan with no US year and blocks the save until it is removed", async () => {
    render(
      <SavingsPrioritiesPanel
        plan={makePlan({ id: "p", tax_country: "NZ", priorities: [bracketConversion] })}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled(),
    );
    expect(optionValues()).toContain("roth_conversion");
    expect(
      screen.getByText(
        /A Roth conversion that fills a federal bracket doesn.t apply in a plan taxed outside the US/,
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
      target: { value: "5000" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Payroll or transfer rule 1: a Roth conversion that fills a federal bracket can't apply",
    );
    expect(mocks.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Remove rule" }));
    fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith("p", [], 0));
  });

  it("keeps bracket-filling conversions in a plan that moves abroad, with a note", async () => {
    render(
      <SavingsPrioritiesPanel
        plan={makePlan({
          id: "p",
          tax_country: "US",
          residency_periods: [abroad],
          priorities: [bracketConversion],
        })}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled(),
    );
    expect(
      screen.getByText(
        "Bracket-filling Roth conversions and gain harvests apply only in the years you live in the US.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/doesn.t apply in a plan taxed outside the US/),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Annual maximum ($; optional)"), {
      target: { value: "5000" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Save allocation" }).closest("form")!);
    await waitFor(() => expect(mocks.save).toHaveBeenCalledOnce());
  });
});

it("labels a conversion ceiling the plan's brackets no longer include", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "t", name: "IRA", account_type: "traditional_ira", owner: "self" },
    { id: "r", name: "Roth", account_type: "roth_ira", owner: "self" },
  ]);
  const rule = (id: string, rank: number, rate: number) => ({
    id,
    priority_rank: rank,
    priority_type: "roth_conversion",
    source_account_id: "t",
    target_account_id: "r",
    conversion_mode: "fill_bracket",
    bracket_ceiling_rate: rate,
  });
  render(
    <SavingsPrioritiesPanel
      plan={makePlan({
        id: "p",
        priorities: [rule("a", 1, 0.12), rule("b", 2, 0.2)],
        tax_settings: {
          federal_brackets: [
            [50000, 0.1],
            [1e9, 0.2],
          ],
        },
      })}
    />,
  );
  expect(
    await screen.findByText(/fill to 12% \(not in this plan's brackets\)/),
  ).toBeInTheDocument();
  expect(screen.getByText(/fill to 20%$/)).toBeInTheDocument();
});

/** Surplus rule titles in display order, without the allocation summary. */
const ruleTitles = () =>
  [...document.querySelectorAll("section.allocation-rule > details > summary")].map(
    (el) => el.textContent?.split(" · ")[0],
  );

it("collapses saved rules, opens new ones and keeps a rule's open state when it moves", async () => {
  mocks.accounts.mockResolvedValue([
    { id: "a", name: "First", account_type: "savings" },
    { id: "b", name: "Second", account_type: "savings" },
  ]);
  const rules = [
    {
      id: "r1",
      plan_id: "p",
      priority_rank: 1,
      priority_type: "contribution",
      target_account_id: "a",
      allocation_mode: "amount",
      allocation_value: 7500,
    },
    {
      id: "r2",
      plan_id: "p",
      priority_rank: 2,
      priority_type: "contribution",
      target_account_id: "b",
      allocation_mode: "percentage",
      allocation_value: 20,
    },
  ];
  render(<SavingsPrioritiesPanel plan={makePlan({ id: "p", priorities: rules })} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled());
  const rule = (title: RegExp) =>
    screen.getByText(title, { selector: "summary" }).closest("details")!;
  expect(rule(/^1\. First · \$7,500 a year$/)).not.toHaveAttribute("open");
  expect(rule(/^2\. Second · 20% of surplus$/)).not.toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "Add allocation" }));
  expect(rule(/^3\. New allocation/)).toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "Move rule 3 up" }));
  expect(rule(/^2\. New allocation/)).toHaveAttribute("open");
  expect(rule(/^3\. Second/)).not.toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "Move rule 2 up" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Remove rule" })[0]);
  expect(ruleTitles()).toEqual(["1. First", "2. Second"]);
  expect(rule(/^1\. First/)).not.toHaveAttribute("open");
});
