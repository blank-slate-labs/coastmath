import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FormFooter } from "./form_footer";

describe("FormFooter", () => {
  it("renders a Cancel button that stays usable in sample view and calls onCancel", () => {
    const onCancel = vi.fn();
    render(<FormFooter onCancel={onCancel} submitLabel="Add income" />);
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveAttribute("type", "button");
    expect(cancel).toHaveAttribute("data-sample-view");
    fireEvent.click(cancel);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("submits the enclosing form from the labelled submit button", () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    const onCancel = vi.fn();
    render(
      <form onSubmit={onSubmit}>
        <FormFooter onCancel={onCancel} submitLabel="Update Milestone" />
      </form>,
    );
    const submit = screen.getByRole("button", { name: "Update Milestone" });
    expect(submit).toHaveAttribute("type", "submit");
    fireEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("places extra actions between Cancel and submit", () => {
    render(
      <FormFooter onCancel={() => {}} submitLabel="Update Expense">
        <button type="submit">Review latest saved values</button>
      </FormFooter>,
    );
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Cancel",
      "Review latest saved values",
      "Update Expense",
    ]);
  });
});
