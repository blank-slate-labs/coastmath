import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IncomeAmountFields } from "./income_amount_fields";

function renderFields(overrides: Partial<React.ComponentProps<typeof IncomeAmountFields>> = {}) {
  const props: React.ComponentProps<typeof IncomeAmountFields> = {
    hourlyPay: false,
    onHourlyChange: vi.fn(),
    hourlyRate: "",
    onHourlyRateChange: vi.fn(),
    hoursPerWeek: "40",
    onHoursPerWeekChange: vi.fn(),
    annualAmount: 52000,
    frequency: "annual",
    onFrequencyChange: vi.fn(),
    displayedAmount: "52000",
    onAmountInput: vi.fn(),
    onAmountChange: vi.fn(),
    once: false,
    ...overrides,
  };
  render(<IncomeAmountFields {...props} />);
  return props;
}

describe("IncomeAmountFields", () => {
  it("reports a typed amount and a new unit", () => {
    const props = renderFields();
    fireEvent.change(screen.getByLabelText(/Annual amount/), { target: { value: "60000" } });
    expect(props.onAmountInput).toHaveBeenCalledWith("60000");
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
    expect(props.onHourlyChange).toHaveBeenCalledWith(false);
    expect(props.onFrequencyChange).toHaveBeenCalledWith("monthly");
    expect(props.onAmountChange).not.toHaveBeenCalled();
  });

  it("seeds an hourly rate from the annual amount when switching to hourly", () => {
    const props = renderFields();
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "hourly" } });
    expect(props.onHourlyRateChange).toHaveBeenCalledWith("25");
    expect(props.onHourlyChange).toHaveBeenCalledWith(true);
    expect(props.onFrequencyChange).not.toHaveBeenCalled();
  });

  it("turns hourly pay back into an annual amount when another unit is chosen", () => {
    const props = renderFields({ hourlyPay: true, hourlyRate: "25" });
    expect(screen.getByTestId("hourly-annual")).toHaveTextContent("$52,000.00 a year");
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "annual" } });
    expect(props.onAmountChange).toHaveBeenCalledWith({ value: "52000", frequency: "annual" });
    expect(props.onHourlyChange).toHaveBeenCalledWith(false);
  });

  it("locks a one-time payment to the annual unit", () => {
    renderFields({ once: true, hourlyPay: false });
    const unit = screen.getByLabelText("Amount frequency") as HTMLSelectElement;
    expect(unit).toBeDisabled();
    expect(unit.value).toBe("annual");
  });
});
