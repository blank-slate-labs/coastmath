import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, it, expect } from "vitest";
import FlexSpendingConfig from "./flex_spending_config";
it("preserves a positive trailing-return threshold and reports failed saves", async () => {
  const save = vi.fn().mockRejectedValue(new Error("offline"));
  render(
    <FlexSpendingConfig
      planId="p"
      initial={{
        flex_threshold: 0.05,
        flex_reduction: 0.2,
        spending_floor: 0.8,
        lookback_years: 3,
      }}
      onSave={save}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not save"));
  expect(save).toHaveBeenCalledWith("p", {
    flex_threshold: 0.05,
    flex_reduction: 0.2,
    spending_floor: 0.8,
    lookback_years: 3,
  });
  expect(screen.getByLabelText(/trailing return/)).toHaveValue(5);
});
it("disables rules with an explicit null and awaits persistence", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <FlexSpendingConfig
      planId="p"
      initial={{
        flex_threshold: -0.1,
        flex_reduction: 0.2,
        spending_floor: 0.8,
        lookback_years: 1,
      }}
      onSave={save}
    />,
  );
  fireEvent.click(screen.getByLabelText("Enable flex spending rules"));
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenCalledWith("p", null);
});

it("saves opt-in all-time-high thresholds, interpolation, floor, and window", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <FlexSpendingConfig
      planId="p"
      initial={null}
      milestones={[{ id: "retirement", name: "Retirement" }]}
      onSave={save}
    />,
  );

  fireEvent.click(screen.getByLabelText("Enable flex spending rules"));
  fireEvent.change(screen.getByLabelText("Performance measure"), {
    target: { value: "all_time_high" },
  });
  fireEvent.change(screen.getByLabelText("Spending floor (%)"), { target: { value: "70" } });
  fireEvent.click(screen.getByRole("button", { name: "Add threshold" }));
  fireEvent.change(screen.getByLabelText("Interpolation"), { target: { value: "linear" } });
  fireEvent.change(screen.getByLabelText("Start milestone (optional)"), {
    target: { value: "retirement" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));

  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenCalledWith(
    "p",
    expect.objectContaining({
      performance_mode: "all_time_high",
      interpolation: "linear",
      spending_floor: 0.7,
      start_milestone_id: "retirement",
      thresholds: [
        { threshold: -0.1, reduction: 0.2 },
        { threshold: -0.2, reduction: 0.3 },
      ],
    }),
  );
});

it("saves upside points, a flex scope and spend-the-leftover on top of the downside rules", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<FlexSpendingConfig planId="p" initial={null} onSave={save} />);

  fireEvent.click(screen.getByLabelText("Enable flex spending rules"));
  fireEvent.change(screen.getByLabelText("Performance measure"), {
    target: { value: "all_time_high" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add upside point" }));
  fireEvent.change(screen.getByLabelText("Upside threshold 1"), { target: { value: "5" } });
  fireEvent.change(screen.getByLabelText("Increase 1"), { target: { value: "10" } });
  fireEvent.click(screen.getByRole("button", { name: "Add upside point" }));
  fireEvent.change(screen.getByLabelText("Upside threshold 2"), { target: { value: "20" } });
  fireEvent.change(screen.getByLabelText("Increase 2"), { target: { value: "30" } });
  fireEvent.change(screen.getByLabelText("Unallocated cash at year end"), {
    target: { value: "spend_leftover" },
  });
  fireEvent.click(screen.getByLabelText("Withdrawal-strategy spending"));
  fireEvent.click(screen.getByLabelText("Leftover spending"));
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));

  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenCalledWith(
    "p",
    expect.objectContaining({
      performance_mode: "all_time_high",
      thresholds: [{ threshold: -0.1, reduction: 0.2 }],
      upside_thresholds: [
        { threshold: 0.05, increase: 0.1 },
        { threshold: 0.2, increase: 0.3 },
      ],
      flex_scope: ["expenses", "strategy_spending", "leftover_spending"],
      surplus_mode: "spend_leftover",
    }),
  );
});

it("leaves the legacy document shape alone when no addition is chosen", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <FlexSpendingConfig
      planId="p"
      initial={{
        flex_threshold: -0.1,
        flex_reduction: 0.2,
        spending_floor: 0.8,
        lookback_years: 1,
      }}
      onSave={save}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenCalledWith("p", {
    flex_threshold: -0.1,
    flex_reduction: 0.2,
    spending_floor: 0.8,
    lookback_years: 1,
  });
});

it("saves spend-the-leftover without enabling any flex rule", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<FlexSpendingConfig planId="p" initial={null} onSave={save} />);
  fireEvent.change(screen.getByLabelText("Unallocated cash at year end"), {
    target: { value: "spend_leftover" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenCalledWith("p", {
    flex_threshold: null,
    flex_reduction: 0.2,
    lookback_years: 1,
    surplus_mode: "spend_leftover",
  });
});

it("drops leftover scope when the surplus is saved and rejects an empty scope or bad upside", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <FlexSpendingConfig
      planId="p"
      initial={{
        flex_threshold: -0.1,
        flex_reduction: 0.2,
        lookback_years: 1,
        spending_floor: 0.8,
        performance_mode: "all_time_high",
        thresholds: [{ threshold: -0.1, reduction: 0.2 }],
        upside_thresholds: [{ threshold: 0.1, increase: 0.1 }],
        flex_scope: ["leftover_spending"],
        surplus_mode: "spend_leftover",
      }}
      onSave={save}
    />,
  );
  expect(screen.getByLabelText("Upside threshold 1")).toHaveValue(10);
  fireEvent.change(screen.getByLabelText("Unallocated cash at year end"), {
    target: { value: "save" },
  });
  expect(screen.getByLabelText("Leftover spending")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("at least one spending type");
  expect(save).not.toHaveBeenCalled();

  fireEvent.click(screen.getByLabelText("Ordinary expenses"));
  fireEvent.change(screen.getByLabelText("Upside threshold 1"), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("upside threshold");
  expect(save).not.toHaveBeenCalled();
});

it("shows an upside-only document without inventing a downside rule", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <FlexSpendingConfig
      planId="p"
      initial={{
        flex_threshold: null,
        flex_reduction: 0.2,
        lookback_years: 1,
        performance_mode: "all_time_high",
        upside_thresholds: [{ threshold: 0.1, increase: 0.1 }],
      }}
      onSave={save}
    />,
  );
  expect(screen.queryByLabelText("Threshold 1")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save Spending Rules" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenCalledWith(
    "p",
    expect.objectContaining({
      flex_threshold: null,
      thresholds: [],
      upside_thresholds: [{ threshold: 0.1, increase: 0.1 }],
    }),
  );
});
