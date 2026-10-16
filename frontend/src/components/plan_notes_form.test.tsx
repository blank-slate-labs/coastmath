import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { it, expect, vi } from "vitest";
import PlanNotesForm, { NOTES_MAX_LENGTH } from "./plan_notes_form";
import { makePlan } from "@/test_support/plan_builder";

const plan = makePlan({ id: "p1", notes: "Original" });

it("saves edited notes as plain text and clears empty notes to null", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<PlanNotesForm plan={plan} onSave={save} />);
  expect(screen.getByRole("button", { name: "Save notes" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/Plan notes/), {
    target: { value: "<script>alert(1)</script> review 2027" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save notes" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Notes saved."));
  expect(save).toHaveBeenCalledWith("p1", "<script>alert(1)</script> review 2027");
  expect(document.querySelector("script")).toBeNull();
  fireEvent.change(screen.getByLabelText(/Plan notes/), { target: { value: "   " } });
  fireEvent.click(screen.getByRole("button", { name: "Save notes" }));
  await waitFor(() => expect(save).toHaveBeenLastCalledWith("p1", null));
});

it("blocks over-long notes and reports failed saves without losing text", async () => {
  const save = vi.fn().mockRejectedValue(new Error("offline"));
  render(<PlanNotesForm plan={plan} onSave={save} />);
  fireEvent.change(screen.getByLabelText(/Plan notes/), {
    target: { value: "x".repeat(NOTES_MAX_LENGTH + 1) },
  });
  expect(screen.getByRole("button", { name: "Save notes" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/Plan notes/), { target: { value: "Short" } });
  fireEvent.click(screen.getByRole("button", { name: "Save notes" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not save"));
  expect(screen.getByLabelText(/Plan notes/)).toHaveValue("Short");
});
