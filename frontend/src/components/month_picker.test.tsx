import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MonthPicker } from "./month_picker";

describe("MonthPicker", () => {
  it("renders 12 month options plus a null/default option", () => {
    render(<MonthPicker value={null} onChange={() => {}} label="Start Month" />);

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(13);
    expect(options[0]).toHaveTextContent("— None —");
    expect(options[1]).toHaveTextContent("January");
    expect(options[12]).toHaveTextContent("December");
  });

  it("calls onChange with the correct month number", () => {
    const handleChange = vi.fn();
    render(<MonthPicker value={null} onChange={handleChange} label="Start Month" />);

    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "3" } });

    expect(handleChange).toHaveBeenCalledWith(3);
  });

  it("displays the current value correctly", () => {
    render(<MonthPicker value={7} onChange={() => {}} label="Start Month" />);

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("7");
  });

  it("shows placeholder when value is null", () => {
    render(
      <MonthPicker
        value={null}
        onChange={() => {}}
        label="End Month"
        placeholder="January (default)"
      />,
    );

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(screen.getByText("January (default)")).toBeInTheDocument();
  });

  it("calls onChange with null when selecting the blank option", () => {
    const handleChange = vi.fn();
    render(<MonthPicker value={5} onChange={handleChange} label="Start Month" />);

    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "" } });

    expect(handleChange).toHaveBeenCalledWith(null);
  });
});
