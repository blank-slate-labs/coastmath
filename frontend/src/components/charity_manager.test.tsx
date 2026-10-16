import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { it, expect, vi, beforeEach } from "vitest";
import CharityManager from "./charity_manager";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const listCharities = vi.fn();
const createCharity = vi.fn();
const deleteCharity = vi.fn();
const runSimulation = vi.fn().mockResolvedValue({ metadata: {}, yearly_snapshots: [] });

// A stable adapter object, as the real StorageProvider supplies.
const adapter = makeAdapter({ listCharities, createCharity, deleteCharity });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

beforeEach(() => {
  listCharities.mockReset().mockResolvedValue([
    {
      id: "c1",
      plan_id: "p1",
      name: "Food bank",
      entity_type: "direct",
      annual_amount: 5000,
      start_milestone_id: null,
      end_milestone_id: "m1",
    },
  ]);
  createCharity.mockReset().mockResolvedValue({});
  deleteCharity.mockReset().mockResolvedValue(undefined);
  adapter.listAccounts.mockReset().mockResolvedValue([
    { id: "self", name: "Self IRA", account_type: "traditional_ira", owner: "self" },
    { id: "inherited", name: "Inherited IRA", account_type: "traditional_ira", owner: "self" },
    { id: "cash", name: "Cash", account_type: "checking" },
  ]);
  adapter.updateCharity.mockReset().mockResolvedValue({});
  setStorageAdapter(makeAdapter({ runSimulation }));
  usePlanStore.setState({
    plan: makePlan({ id: "p1", birth_year: 1990 }),
    simulation: null,
    isSimulating: false,
  });
});

const milestones = [
  {
    id: "m1",
    plan_id: "p1",
    name: "Retirement",
    trigger_type: "age" as const,
    trigger_value: 65,
    trigger_date: null,
    metric: null,
    expense_multiple: null,
    relative_to_id: null,
    offset_years: 0,
    sort_order: 0,
  },
];

it.each([65, 67])(
  "retains and rejects an empty or reversed giving window starting at %s",
  async (age) => {
    render(
      <CharityManager
        planId="p1"
        milestones={[
          ...milestones,
          { ...milestones[0], id: "later", name: "Later", trigger_value: age },
        ]}
      />,
    );
    await screen.findByText("Food bank");
    fireEvent.click(screen.getByText("Edit"));
    fireEvent.change(screen.getByLabelText(/Start milestone/), { target: { value: "later" } });
    fireEvent.click(screen.getByText("Update giving"));
    expect(screen.getByRole("alert")).toHaveTextContent(/later year|comes after/);
    expect(screen.getByLabelText(/Start milestone/)).toHaveValue("later");
    expect(adapter.updateCharity).not.toHaveBeenCalled();
  },
);

it("lists giving with type and milestone bounds and re-simulates after adding a QCD", async () => {
  render(<CharityManager planId="p1" milestones={milestones} />);
  expect(await screen.findByText("Food bank")).toBeInTheDocument();
  expect(screen.getByText(/Direct cash gift · \$5,000\/yr · until Retirement/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("+ Add giving"));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Church" } });
  fireEvent.change(screen.getByLabelText("Giving type"), { target: { value: "qcd" } });
  expect(screen.getByText(/70½/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/Annual amount/), { target: { value: "12000" } });
  fireEvent.click(screen.getByText("Add giving"));
  await waitFor(() =>
    expect(createCharity).toHaveBeenCalledWith("p1", {
      name: "Church",
      entity_type: "qcd",
      annual_amount: 12000,
      start_milestone_id: null,
      end_milestone_id: null,
      source_account_id: null,
    }),
  );
  await waitFor(() => expect(runSimulation).toHaveBeenCalledWith("p1"));
});

it("saves the selected IRA payer and clears it when changing giving type", async () => {
  listCharities.mockResolvedValue([
    { id: "q", name: "QCD", entity_type: "qcd", annual_amount: 20000, source_account_id: "self" },
  ]);
  render(<CharityManager planId="p1" milestones={[]} />);
  await screen.findByText(/QCD from IRA.*Self IRA/);
  fireEvent.click(screen.getByText("Edit"));
  expect(screen.getByLabelText("IRA payer")).toHaveValue("self");
  expect(screen.queryByRole("option", { name: "Cash" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("IRA payer"), { target: { value: "inherited" } });
  fireEvent.click(screen.getByText("Update giving"));
  await waitFor(() =>
    expect(adapter.updateCharity).toHaveBeenCalledWith(
      "p1",
      "q",
      expect.objectContaining({ source_account_id: "inherited" }),
    ),
  );
  await screen.findByText("Edit");
  fireEvent.click(screen.getByText("Edit"));
  fireEvent.change(screen.getByLabelText("Giving type"), { target: { value: "direct" } });
  fireEvent.click(screen.getByText("Update giving"));
  await waitFor(() =>
    expect(adapter.updateCharity).toHaveBeenLastCalledWith(
      "p1",
      "q",
      expect.objectContaining({ source_account_id: null }),
    ),
  );
});

it("rejects a non-positive amount and reports delete failures", async () => {
  deleteCharity.mockRejectedValueOnce(new Error("offline"));
  render(<CharityManager planId="p1" milestones={milestones} />);
  await screen.findByText("Food bank");
  fireEvent.click(screen.getByText("+ Add giving"));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "X" } });
  fireEvent.change(screen.getByLabelText(/Annual amount/), { target: { value: "0" } });
  fireEvent.click(screen.getByText("Add giving"));
  expect(screen.getByRole("alert")).toHaveTextContent("positive annual amount");
  expect(createCharity).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Delete"));
  // A delete asks first, naming the entry.
  const ask = await screen.findByRole("alertdialog");
  expect(ask).toHaveTextContent(/^Delete “/);
  fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("alert").some((el) => el.textContent?.includes("Could not delete")),
    ).toBe(true),
  );
});

it("funds a donor-advised fund gift with appreciated shares from a brokerage account", async () => {
  adapter.listAccounts.mockResolvedValue([
    { id: "brokerage", name: "Brokerage", account_type: "taxable_brokerage", owner: "self" },
    { id: "cash", name: "Cash", account_type: "checking" },
  ]);
  render(<CharityManager planId="p1" milestones={[]} />);
  await screen.findByText("Food bank");
  fireEvent.click(screen.getByText("+ Add giving"));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "DAF" } });
  fireEvent.change(screen.getByLabelText("Giving type"), { target: { value: "daf" } });
  fireEvent.change(screen.getByLabelText("Paid with"), { target: { value: "appreciated_shares" } });
  expect(screen.getByText(/30% of AGI/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/Annual amount/), { target: { value: "25000" } });
  fireEvent.click(screen.getByText("Add giving"));
  expect(screen.getByRole("alert")).toHaveTextContent(/brokerage account/);
  fireEvent.change(screen.getByLabelText("Shares from"), { target: { value: "brokerage" } });
  fireEvent.click(screen.getByText("Add giving"));
  await waitFor(() =>
    expect(createCharity).toHaveBeenCalledWith("p1", {
      name: "DAF",
      entity_type: "daf",
      annual_amount: 25000,
      start_milestone_id: null,
      end_milestone_id: null,
      source_account_id: "brokerage",
      funding: "appreciated_shares",
    }),
  );
});
