import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import MoneyInput, { cleanAmount, groupDigits } from "./money_input";

function Field({
  initial = "",
  step,
  min,
  max,
  numeric = false,
  onRaw = () => {},
}: {
  initial?: string;
  step?: string;
  min?: string;
  max?: string;
  numeric?: boolean;
  onRaw?: (raw: string) => void;
}) {
  const [value, setValue] = useState<string | number>(numeric ? Number(initial) : initial);
  return (
    <form aria-label="form">
      <label>
        Amount
        <MoneyInput
          value={value}
          step={step}
          min={min}
          max={max}
          onValueChange={(raw) => {
            onRaw(raw);
            setValue(numeric ? Number(raw) : raw);
          }}
        />
      </label>
    </form>
  );
}

/** Types as a browser does: new text with the caret placed, then the input event. */
function type(input: HTMLInputElement, text: string, caret: number) {
  // The prototype setter bypasses React's value tracker, so React sees the change.
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
  input.setSelectionRange(caret, caret);
  fireEvent.change(input);
}

const field = () => screen.getByLabelText("Amount") as HTMLInputElement;

describe("groupDigits and cleanAmount", () => {
  it.each([
    ["0", "0"],
    ["999", "999"],
    ["1000", "1,000"],
    ["231000", "231,000"],
    ["-1234567.891", "-1,234,567.891"],
    ["12.", "12."],
    [".5", ".5"],
    ["", ""],
    ["1e+21", "1e+21"],
  ])("groups %s as %s", (raw, shown) => expect(groupDigits(raw)).toBe(shown));

  it("keeps digits, one point and a leading minus sign, capped to the step's decimals", () => {
    expect(cleanAmount("$1,234.5.6")).toBe("1234.56");
    expect(cleanAmount("-1,000")).toBe("-1000");
    expect(cleanAmount("10-0")).toBe("100");
    expect(cleanAmount("12.345", 2)).toBe("12.34");
    expect(cleanAmount("1234.56", 0)).toBe("1234");
  });
});

describe("MoneyInput", () => {
  it("is a text field without a spinner that shows commas and reports plain numeric text", () => {
    const onRaw = vi.fn();
    render(<Field onRaw={onRaw} />);
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(field()).toHaveAttribute("type", "text");
    fireEvent.change(field(), { target: { value: "100000" } });
    expect(field()).toHaveValue("100,000");
    expect(onRaw).toHaveBeenLastCalledWith("100000");
    fireEvent.change(field(), { target: { value: "1,000,000.25" } });
    expect(field()).toHaveValue("1,000,000.25");
    expect(onRaw).toHaveBeenLastCalledWith("1000000.25");
  });

  it("shows a saved amount with commas", () => {
    render(<Field initial="231000" numeric />);
    expect(field()).toHaveValue("231,000");
  });

  it("keeps a typed trailing point while the parent stores a number", () => {
    render(<Field initial="12" numeric />);
    fireEvent.change(field(), { target: { value: "1200." } });
    expect(field()).toHaveValue("1,200.");
    fireEvent.change(field(), { target: { value: "1,200.5" } });
    expect(field()).toHaveValue("1,200.5");
  });

  it("reports a lone minus sign as blank but keeps it on screen", () => {
    const onRaw = vi.fn();
    render(<Field onRaw={onRaw} />);
    fireEvent.change(field(), { target: { value: "-" } });
    expect(field()).toHaveValue("-");
    expect(onRaw).toHaveBeenLastCalledWith("");
    fireEvent.change(field(), { target: { value: "-2500" } });
    expect(onRaw).toHaveBeenLastCalledWith("-2500");
    expect(field()).toHaveValue("-2,500");
  });

  it("limits decimals to the step", () => {
    render(<Field step="1" />);
    fireEvent.change(field(), { target: { value: "1500.75" } });
    expect(field()).toHaveValue("1,500");
  });

  it("checks min and max through form validation", () => {
    render(<Field min="0" max="1000" />);
    fireEvent.change(field(), { target: { value: "-5" } });
    expect(field().validationMessage).toBe("Enter 0 or more.");
    fireEvent.change(field(), { target: { value: "5000" } });
    expect(field().validationMessage).toBe("Enter 1,000 or less.");
    fireEvent.change(field(), { target: { value: "500" } });
    expect(field().checkValidity()).toBe(true);
  });

  it("follows a value changed outside the field", () => {
    const { rerender } = render(
      <MoneyInput aria-label="Amount" value="5000" onValueChange={() => {}} />,
    );
    expect(field()).toHaveValue("5,000");
    rerender(<MoneyInput aria-label="Amount" value={null} onValueChange={() => {}} />);
    expect(field()).toHaveValue("");
  });

  it("keeps the caret beside the digit just typed when commas move", () => {
    render(<Field initial="100" />);
    const input = field();
    input.focus();
    // Typing 5 after the leading 1 of "100": "1|00" becomes "1,5|00".
    type(input, "1500", 2);
    expect(input).toHaveValue("1,500");
    expect(input.selectionStart).toBe(3);
    // Deleting the 5 again: "1,|00" becomes "1|00".
    type(input, "1,00", 2);
    expect(input).toHaveValue("100");
    expect(input.selectionStart).toBe(1);
  });
});
