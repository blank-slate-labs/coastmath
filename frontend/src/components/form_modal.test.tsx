import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { FormModal } from "./form_modal";

it("contains keyboard focus and restores the trigger when dismissed", () => {
  const trigger = document.createElement("button");
  document.body.appendChild(trigger);
  trigger.focus();
  const close = vi.fn();
  const { rerender } = render(
    <FormModal open onClose={close} title="Edit income">
      <input aria-label="Name" />
      <button>Save income</button>
    </FormModal>,
  );
  const dialog = screen.getByRole("dialog", { name: "Edit income" });
  expect(dialog).toHaveFocus();
  fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("button", { name: "Save income" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Tab" });
  expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(close).toHaveBeenCalledOnce();
  rerender(
    <FormModal open={false} onClose={close} title="Edit income">
      Closed
    </FormModal>,
  );
  expect(trigger).toHaveFocus();
  trigger.remove();
});
