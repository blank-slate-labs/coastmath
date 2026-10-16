import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import EditSheet from "./edit_sheet";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import { PLAN_SECTIONS } from "@/pages/plan_setup";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
import { makeIncome } from "@/test_support/record_builders";
const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
beforeEach(() => {
  usePlanStore.setState({
    plan: makePlan({ id: "a", birth_year: 1990, life_expectancy: 90, notes: null }),
  });
});
it("traps keyboard focus, respects nested forms, and restores the trigger and body on close", async () => {
  const root = document.createElement("div");
  root.id = "root";
  const trigger = document.createElement("button");
  trigger.textContent = "Open editor";
  root.appendChild(trigger);
  document.body.appendChild(root);
  trigger.focus();
  const close = vi.fn();
  const view = render(<EditSheet index={3} onIndexChange={vi.fn()} onClose={close} />);
  const sheet = screen.getByRole("dialog", { name: "Income streams" });
  expect(sheet).toHaveFocus();
  expect(root.inert).toBe(true);
  expect(document.body.style.overflow).toBe("hidden");
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("combobox", { name: "Go to section" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(screen.getByRole("button", { name: "Close editor" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("combobox", { name: "Go to section" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: /Add income/ }));
  expect(screen.getByRole("dialog", { name: "Add Income" })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "Add Income" })).not.toBeInTheDocument();
  expect(close).not.toHaveBeenCalled();
  const latestClose = vi.fn();
  view.rerender(<EditSheet index={3} onIndexChange={vi.fn()} onClose={latestClose} />);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(latestClose).toHaveBeenCalledOnce();
  view.unmount();
  expect(document.body.style.overflow).toBe("");
  expect(root.inert).toBe(false);
  expect(trigger).toHaveFocus();
  root.remove();
});
it("jumps directly between independent sections without a wizard step count", () => {
  const navigate = vi.fn();
  const close = vi.fn();
  const view = render(<EditSheet index={0} onIndexChange={navigate} onClose={close} />);
  const picker = screen.getByRole("combobox", { name: "Go to section" });
  expect(picker).toHaveValue("0");
  expect(screen.getByText("Essential")).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Assumptions" }).parentElement).toHaveAttribute(
    "label",
    "Optional",
  );
  expect(screen.getByRole("option", { name: "Accounts" }).parentElement).toHaveAttribute(
    "label",
    "Essentials",
  );
  fireEvent.change(picker, { target: { value: "13" } });
  expect(navigate).toHaveBeenLastCalledWith(13);
  view.rerender(
    <EditSheet index={PLAN_SECTIONS.length - 1} onIndexChange={navigate} onClose={close} />,
  );
  expect(picker).toHaveValue(String(PLAN_SECTIONS.length - 1));
  expect(screen.getByText("Optional")).toBeInTheDocument();
  expect(screen.queryByText(/of 14/)).not.toBeInTheDocument();
  fireEvent.click(document.querySelector(".edit-sheet-backdrop")!);
  expect(close).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
  expect(close).toHaveBeenCalledTimes(2);
});
it("does not lock the page when a requested editor cannot render", () => {
  const view = render(<EditSheet index={-1} onIndexChange={vi.fn()} onClose={vi.fn()} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
  view.rerender(<EditSheet index={3} onIndexChange={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  act(() => usePlanStore.setState({ plan: null }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
});
it("moves focus to the next row when a deleted row takes the focused button with it", async () => {
  const income = (id: string, name: string) =>
    makeIncome({
      id,
      plan_id: "a",
      name,
      annual_amount: 1000,
      owner: "self",
      growth_rate: 0,
      start_milestone_id: null,
      end_milestone_id: null,
      start_month: null,
      end_month: null,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
      claiming_age: null,
      is_active: true,
    });
  const plan = usePlanStore.getState().plan!;
  usePlanStore.setState({
    plan: makePlan({ ...plan, income_streams: [income("i1", "Salary"), income("i2", "Bonus")] }),
  });
  render(<EditSheet index={3} onIndexChange={vi.fn()} onClose={vi.fn()} />);
  const rows = document.querySelectorAll(".plan-list-item");
  expect(rows).toHaveLength(2);
  rows[0].querySelector<HTMLButtonElement>(".plan-delete-btn")!.focus();
  act(() =>
    usePlanStore.setState((s) => ({
      plan: { ...s.plan!, income_streams: [income("i2", "Bonus")] },
    })),
  );
  await vi.waitFor(() =>
    expect(document.activeElement).toBe(document.querySelector(".plan-list-item .plan-action-btn")),
  );
});

async function renderPlanDetails(close: () => void) {
  setStorageAdapter(adapter);
  await act(async () => {
    render(<EditSheet index={0} onIndexChange={vi.fn()} onClose={close} />);
  });
  return screen.getByLabelText("Plan name");
}
it("asks before Plan details closes over a failed save, and declining keeps the draft", async () => {
  adapter.updatePlan.mockRejectedValueOnce(new Error("Save plan could not be confirmed."));
  const close = vi.fn();
  const name = await renderPlanDetails(close);
  fireEvent.change(name, { target: { value: "Renamed" } });
  fireEvent.blur(name);
  const notice = await screen.findByRole("alert");
  expect(notice).toHaveTextContent("Save plan could not be confirmed.Your draft is kept.");
  // An autosave failure does not pull focus away from the field the person moved to.
  expect(notice).not.toHaveFocus();
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);

  fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  fireEvent.keyDown(document, { key: "Escape" });
  fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(close).not.toHaveBeenCalled();
  expect(name).toHaveValue("Renamed");

  fireEvent.keyDown(document, { key: "Escape" });
  fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
});
it("closes Plan details without asking once the failed field saves", async () => {
  adapter.updatePlan
    .mockRejectedValueOnce(new Error("offline"))
    .mockImplementation(async (_id, data) => ({ ...usePlanStore.getState().plan!, ...data }));
  const close = vi.fn();
  const name = await renderPlanDetails(close);
  fireEvent.change(name, { target: { value: "Renamed" } });
  fireEvent.blur(name);
  await screen.findByText("Your draft is kept.");
  fireEvent.blur(name);
  await waitFor(() => expect(screen.queryByText("Your draft is kept.")).not.toBeInTheDocument());
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
  expect(close).toHaveBeenCalledOnce();
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});
