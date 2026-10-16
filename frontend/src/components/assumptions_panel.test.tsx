import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, it, expect } from "vitest";
import AssumptionsPanel from "./assumptions_panel";
import { usePlanStore } from "@/stores/plan_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
const mocks = vi.hoisted(() => ({ create: vi.fn(), update: vi.fn(), remove: vi.fn() }));
const adapter = makeAdapter({
  createAssumption: mocks.create,
  updateAssumption: mocks.update,
  deleteAssumption: mocks.remove,
});
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const plan = makePlan({ id: "p", birth_year: 1990, life_expectancy: 90 });

it("uses server defaults while preserving a saved override", () => {
  const serverPlan = makePlan({
    ...plan,
    assumption_defaults: { inflation: 0.025, market_return: 0.08, bond_return: 0 },
    assumption_curves: [
      {
        id: "custom",
        curve_type: "market_return",
        mode: "fixed",
        fixed_rate: 0.06,
        control_points: [],
      },
    ],
  });
  render(<AssumptionsPanel plan={serverPlan} />);
  expect(screen.getByText("Inflation · 2.5% (default)")).toBeInTheDocument();
  expect(screen.getByText("Stock price growth · 6.0%")).toBeInTheDocument();
  expect(screen.getByText("Bond return · 0.0% (default)")).toBeInTheDocument();
  expect(screen.getByLabelText("Inflation percent")).toHaveValue(2.5);
});

it("shows actual defaults, saves percentage units and recalculates after persistence", async () => {
  const reload = vi.fn().mockResolvedValue(undefined);
  usePlanStore.setState({ plan, loadPlan: reload });
  mocks.create.mockResolvedValue({});
  render(<AssumptionsPanel plan={plan} />);
  expect(screen.getByText("Bond allocation · 0.0% (default)")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Inflation · 3.0% (default)"));
  fireEvent.change(screen.getByLabelText("Inflation percent"), { target: { value: "2.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Save assumptions" }));
  await waitFor(() => expect(reload).toHaveBeenCalledWith("p"));
  expect(mocks.create).toHaveBeenCalledWith(
    "p",
    expect.objectContaining({ curve_type: "inflation", fixed_rate: 0.025 }),
  );
});

it("keeps edits on a failed save and rejects duplicate curve ages", async () => {
  mocks.create.mockRejectedValue(new Error("offline"));
  render(<AssumptionsPanel plan={plan} />);
  fireEvent.click(screen.getByText("Inflation · 3.0% (default)"));
  fireEvent.change(screen.getByLabelText("Inflation percent"), { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Save assumptions" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not save"));
  expect(screen.getByLabelText("Inflation percent")).toHaveValue(4);
  fireEvent.click(screen.getAllByTestId("mode-curve")[0]);
  fireEvent.change(screen.getByLabelText("Inflation age 2"), {
    target: { value: String(new Date().getFullYear() - 1990) },
  });
  mocks.create.mockClear();
  fireEvent.click(screen.getByRole("button", { name: "Save assumptions" }));
  expect(screen.getByRole("alert")).toHaveTextContent(/^Age 2: age \d+ is already listed\.$/);
  expect(screen.getByLabelText("Inflation age 2")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByLabelText("Inflation age 2")).toHaveFocus();
  expect(mocks.create).not.toHaveBeenCalled();
});

it("offers wage growth that follows inflation until saved", async () => {
  const reload = vi.fn().mockResolvedValue(undefined);
  const inflated = makePlan({
    ...plan,
    assumption_curves: [
      { id: "inf", curve_type: "inflation", mode: "fixed", fixed_rate: 0.025, control_points: [] },
    ],
  });
  usePlanStore.setState({ plan: inflated, loadPlan: reload });
  mocks.create.mockReset().mockResolvedValue({});
  render(<AssumptionsPanel plan={inflated} />);
  fireEvent.click(screen.getByText("Wage growth · Follows inflation"));
  // It opens on following inflation; a rate of its own is a choice, prefilled with inflation.
  expect(screen.getByRole("button", { name: "Follows inflation" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.queryByLabelText("Wage growth percent")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Own rate" }));
  expect(screen.getByLabelText("Wage growth percent")).toHaveValue(2.5);
  fireEvent.change(screen.getByLabelText("Wage growth percent"), { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Save assumptions" }));
  await waitFor(() => expect(reload).toHaveBeenCalledWith("p"));
  expect(mocks.create).toHaveBeenCalledWith(
    "p",
    expect.objectContaining({ curve_type: "wage_growth", mode: "fixed", fixed_rate: 0.04 }),
  );
});

it("shows a saved wage growth rate", () => {
  const saved = makePlan({
    ...plan,
    assumption_curves: [
      { id: "w", curve_type: "wage_growth", mode: "fixed", fixed_rate: 0.035, control_points: [] },
    ],
  });
  render(<AssumptionsPanel plan={saved} />);
  expect(screen.getByText("Wage growth · 3.5%")).toBeInTheDocument();
});

it("saves cash yield in decimal units and displays the reloaded rule", async () => {
  const reload = vi.fn().mockResolvedValue(undefined);
  usePlanStore.setState({ plan, loadPlan: reload });
  mocks.create.mockReset().mockResolvedValue({});
  const { rerender } = render(<AssumptionsPanel plan={plan} />);
  fireEvent.click(screen.getByText("Cash yield · 0.0% (default)"));
  fireEvent.change(screen.getByLabelText("Cash yield percent"), { target: { value: "3.5" } });
  fireEvent.click(screen.getByRole("button", { name: "Save assumptions" }));
  await waitFor(() => expect(reload).toHaveBeenCalledWith("p"));
  expect(mocks.create).toHaveBeenCalledWith(
    "p",
    expect.objectContaining({
      curve_type: "cash_yield",
      mode: "fixed",
      fixed_rate: 0.035,
    }),
  );
  const saved = makePlan({
    ...plan,
    assumption_curves: [
      {
        id: "cash",
        curve_type: "cash_yield",
        mode: "fixed",
        fixed_rate: 0.035,
        control_points: [],
      },
    ],
  });
  rerender(<AssumptionsPanel plan={saved} />);
  expect(screen.getByText("Cash yield · 3.5%")).toBeInTheDocument();
  expect(screen.getByLabelText("Cash yield percent")).toHaveValue(3.5);
});

it("returns a saved wage growth to following inflation by removing its rate", async () => {
  const reload = vi.fn().mockResolvedValue(undefined);
  const remove = mocks.remove.mockReset().mockResolvedValue(undefined);
  const saved = makePlan({
    ...plan,
    assumption_curves: [
      { id: "w", curve_type: "wage_growth", mode: "fixed", fixed_rate: 0.035, control_points: [] },
    ],
  });
  usePlanStore.setState({ plan: saved, loadPlan: reload });
  render(<AssumptionsPanel plan={saved} />);
  const save = screen.getByRole("button", { name: "Save assumptions" });
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByText("Wage growth · 3.5%"));
  fireEvent.click(screen.getByRole("button", { name: "Follows inflation" }));
  fireEvent.click(save);
  await waitFor(() => expect(reload).toHaveBeenCalledWith("p"));
  expect(remove).toHaveBeenCalledWith("p", "w");
});

it("saves nothing while a collapsed row is invalid, and opens that row to show why", async () => {
  mocks.create.mockReset().mockResolvedValue({});
  render(<AssumptionsPanel plan={plan} />);
  const stocks = screen.getByText("Stock price growth · 7.0% (default)").closest("details")!;
  fireEvent.click(screen.getByText("Stock price growth · 7.0% (default)"));
  fireEvent.change(screen.getByLabelText("Stock price growth percent"), {
    target: { value: "500" },
  });
  stocks.open = false;
  fireEvent.click(screen.getByText("Inflation · 3.0% (default)"));
  fireEvent.change(screen.getByLabelText("Inflation percent"), { target: { value: "60" } });
  fireEvent.click(screen.getByRole("button", { name: "Save assumptions" }));
  expect(stocks.open).toBe(true);
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a rate from -99% to 100%.");
  expect(screen.getByLabelText("Stock price growth percent")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  expect(screen.getByLabelText("Stock price growth percent")).toHaveFocus();
  expect(mocks.create).not.toHaveBeenCalled();
});
