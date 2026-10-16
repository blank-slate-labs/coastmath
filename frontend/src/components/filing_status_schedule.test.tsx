import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FilingStatusSchedule from "./filing_status_schedule";

describe("filing status schedule", () => {
  it("saves a marriage year and retains the draft after a failed save", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(undefined);
    render(<FilingStatusSchedule initial={[]} milestones={[]} onSave={save} />);
    fireEvent.click(screen.getByText("Add filing status change"));
    fireEvent.change(screen.getByLabelText("Change year"), { target: { value: "2030" } });
    fireEvent.click(screen.getByText("Save filing status changes"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your edits are retained");
    expect(screen.getByLabelText("Change year")).toHaveValue(2030);
    fireEvent.click(screen.getByText("Save filing status changes"));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save).toHaveBeenLastCalledWith([
      { year: 2030, filing_status: "married_filing_jointly" },
    ]);
  });
});
