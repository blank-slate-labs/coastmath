import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import WithdrawalStrategyForm from "./withdrawal_strategy_form";

const milestones = [{ id: "retire", name: "Retirement" }];

it("saves a ratchet strategy with a milestone start, bounds in both units and income handling", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <WithdrawalStrategyForm planId="p" initial={null} milestones={milestones} onSave={save} />,
  );
  fireEvent.click(screen.getByLabelText("Set spending with a withdrawal strategy"));
  fireEvent.change(screen.getByLabelText("Method"), { target: { value: "kitces_ratchet" } });
  fireEvent.change(screen.getByLabelText("Initial rate (%)"), { target: { value: "3.5" } });
  fireEvent.change(screen.getByLabelText("Ratchet threshold (% of starting portfolio)"), {
    target: { value: "140" },
  });
  fireEvent.change(screen.getByLabelText("Years between raises"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("Start"), { target: { value: "milestone" } });
  fireEvent.click(screen.getByLabelText("Minimum"));
  fireEvent.change(screen.getByLabelText("Minimum amount"), { target: { value: "30000" } });
  fireEvent.click(screen.getByLabelText("Maximum"));
  fireEvent.change(screen.getByLabelText("Maximum unit"), {
    target: { value: "portfolio_percent" },
  });
  fireEvent.change(screen.getByLabelText("Maximum amount"), { target: { value: "6" } });
  fireEvent.change(screen.getByLabelText("Other income"), {
    target: { value: "withdrawal_plus_income" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save withdrawal strategy" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenCalledWith(
    "p",
    expect.objectContaining({
      enabled: true,
      method: "kitces_ratchet",
      initial_rate: 0.035,
      ratchet_threshold: 1.4,
      ratchet_cooldown_years: 2,
      start_milestone_id: "retire",
      start_age: null,
      minimum: { unit: "today_dollars", amount: 30000 },
      maximum: { unit: "portfolio_percent", amount: 0.06 },
      income_handling: "withdrawal_plus_income",
    }),
  );
});

it("shows only the chosen method's parameters and requires a fixed amount", async () => {
  const save = vi.fn();
  render(
    <WithdrawalStrategyForm planId="p" initial={{ enabled: true, method: "vpw" }} onSave={save} />,
  );
  expect(screen.getByLabelText("Stock real return (%)")).toHaveValue(5);
  expect(screen.getByLabelText("Bond real return (%)")).toHaveValue(1.9);
  expect(screen.queryByLabelText("Initial rate (%)")).toBeNull();
  fireEvent.change(screen.getByLabelText("Method"), { target: { value: "fixed_amount" } });
  fireEvent.click(screen.getByRole("button", { name: "Save withdrawal strategy" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Yearly amount");
  expect(save).not.toHaveBeenCalled();
});

it("keeps edits and reports a failed save; disabling keeps the saved choices", async () => {
  const save = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
  const initial = {
    enabled: true,
    method: "clyatt_95" as const,
    initial_rate: 0.04,
    clyatt_floor: 0.9,
    start_age: 62,
  };
  render(<WithdrawalStrategyForm planId="p" initial={initial} onSave={save} />);
  expect(screen.getByLabelText("Share of last year's withdrawal (%)")).toHaveValue(90);
  expect(screen.getByLabelText("Start age")).toHaveValue(62);
  fireEvent.click(screen.getByRole("button", { name: "Save withdrawal strategy" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not save"));
  fireEvent.click(screen.getByLabelText("Set spending with a withdrawal strategy"));
  fireEvent.click(screen.getByRole("button", { name: "Save withdrawal strategy" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenLastCalledWith(
    "p",
    expect.objectContaining({
      enabled: false,
      method: "clyatt_95",
      clyatt_floor: 0.9,
      start_age: 62,
    }),
  );
});
