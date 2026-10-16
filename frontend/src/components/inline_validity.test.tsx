import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { InlineValidity, validityMessage } from "./inline_validity";

it("states the browser's rejection inline, marks the field red, and clears once fixed", () => {
  render(
    <InlineValidity>
      <form>
        <label>
          Amount
          <input required />
        </label>
        <label>
          Note
          <input aria-invalid="true" />
        </label>
        <button type="submit">Save</button>
      </form>
    </InlineValidity>,
  );
  const amount = screen.getByLabelText("Amount");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("alert")).toHaveTextContent(/^Amount: Enter a value\.$/);
  expect(amount).toHaveAttribute("aria-invalid", "true");
  fireEvent.input(amount, { target: { value: "5" } });
  expect(amount).not.toHaveAttribute("aria-invalid");
  expect(screen.queryByRole("alert")).toBeNull();
  // A form's own error marking is left alone.
  expect(screen.getByLabelText("Note")).toHaveAttribute("aria-invalid", "true");
});

it("names the field by its label, not the help line nested after the control", () => {
  render(
    <InlineValidity>
      <form>
        <label>
          Interest rate (% per year)
          <input type="number" max={100} defaultValue="150" />
          <span>Annual percentage, used by the projection.</span>
        </label>
        <button type="submit">Save</button>
      </form>
    </InlineValidity>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    /^Interest rate \(% per year\): Enter 100 or less\.$/,
  );
});

it("names a control that leads its label by the label's text", () => {
  render(
    <InlineValidity>
      <form>
        <label>
          <input type="checkbox" required /> Plan includes a partner
        </label>
        <button type="submit">Save</button>
      </form>
    </InlineValidity>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    /^Plan includes a partner: Check this box\.$/,
  );
});

it("states each rejection in the product's words, not the browser's", () => {
  render(
    <form>
      <select aria-label="State" required defaultValue="">
        <option value="" disabled>
          Choose a state
        </option>
        <option value="CA">California</option>
      </select>
      <input aria-label="Birth year" type="number" required />
      <input aria-label="Low" type="number" min={1900} defaultValue="1800" />
      <input aria-label="Whole" type="number" min={1900} defaultValue="1990.5" />
      <input aria-label="Cents" type="number" min={0} step={0.01} defaultValue="2.555" />
      <input aria-label="Fives" type="number" min={0} step={5} defaultValue="7" />
      <input aria-label="Offset" type="number" min={1} step={5} defaultValue="7" />
      <input aria-label="Date" type="date" max="2026-10-15" defaultValue="2027-01-01" />
      <input aria-label="Email" type="email" defaultValue="not-an-email" />
      <input
        aria-label="Code"
        pattern="[A-Z]{2}"
        title="Use two capital letters."
        defaultValue="a"
      />
      <input
        aria-label="Custom"
        defaultValue="x"
        ref={(el) => el?.setCustomValidity("Enter 0 or more.")}
      />
    </form>,
  );
  const message = (name: string) =>
    validityMessage(screen.getByLabelText(name) as HTMLInputElement);
  expect(message("State")).toBe("Choose one.");
  expect(message("Birth year")).toBe("Enter a number.");
  expect(message("Low")).toBe("Enter 1900 or more.");
  expect(message("Whole")).toBe("Enter a whole number.");
  expect(message("Cents")).toBe("Use at most 2 decimal places.");
  expect(message("Fives")).toBe("Enter a multiple of 5.");
  expect(message("Offset")).toBe("Use steps of 5 from 1.");
  expect(message("Date")).toBe("Enter 2026-10-15 or earlier.");
  expect(message("Email")).toBe("Enter an email address.");
  expect(message("Code")).toBe("Use two capital letters.");
  expect(message("Custom")).toBe("Enter 0 or more.");
});
