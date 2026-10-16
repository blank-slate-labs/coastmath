import { useRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useDialogFocus } from "./use_dialog_focus";

function Dialog({
  open,
  onEscape,
  isActive,
}: {
  open: boolean;
  onEscape: () => void;
  isActive?: () => boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useDialogFocus(open, panel, { onEscape, isActive });
  if (!open) return null;
  return (
    <div ref={panel} role="dialog" aria-label="Panel" tabIndex={-1}>
      <button>First</button>
      <button hidden>Hidden</button>
      <details>
        <summary>More</summary>
        <button>Inside closed details</button>
      </details>
      <input type="hidden" />
      <button disabled>Disabled</button>
      <button>Last</button>
    </div>
  );
}

let root: HTMLDivElement;
let trigger: HTMLButtonElement;

beforeEach(() => {
  root = document.createElement("div");
  root.id = "root";
  trigger = document.createElement("button");
  root.appendChild(trigger);
  document.body.appendChild(root);
  trigger.focus();
});

afterEach(() => {
  root.remove();
});

it("focuses the panel and wraps Tab forwards and backwards past hidden controls", () => {
  render(<Dialog open onEscape={vi.fn()} />);
  const panel = screen.getByRole("dialog", { name: "Panel" });
  expect(panel).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
  // A closed `details` keeps its summary in the cycle but not its contents.
  screen.getByText("More").focus();
  fireEvent.keyDown(document, { key: "Tab" });
  expect(screen.getByText("More")).toHaveFocus();
});

it("calls onEscape with the latest callback", () => {
  const first = vi.fn();
  const latest = vi.fn();
  const view = render(<Dialog open onEscape={first} />);
  view.rerender(<Dialog open onEscape={latest} />);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(first).not.toHaveBeenCalled();
  expect(latest).toHaveBeenCalledOnce();
});

it("ignores Escape and Tab while inactive", () => {
  const escape = vi.fn();
  render(<Dialog open onEscape={escape} isActive={() => false} />);
  const last = screen.getByRole("button", { name: "Last" });
  last.focus();
  const tab = fireEvent.keyDown(document, { key: "Tab" });
  fireEvent.keyDown(document, { key: "Escape" });
  expect(tab).toBe(true);
  expect(last).toHaveFocus();
  expect(escape).not.toHaveBeenCalled();
});

it("restores inert, overflow and the trigger's focus when closed", () => {
  document.body.style.overflow = "auto";
  const view = render(<Dialog open onEscape={vi.fn()} />);
  expect(root.inert).toBe(true);
  expect(document.body.style.overflow).toBe("hidden");
  view.rerender(<Dialog open={false} onEscape={vi.fn()} />);
  expect(root.inert).toBe(false);
  expect(document.body.style.overflow).toBe("auto");
  expect(trigger).toHaveFocus();
  const escape = vi.fn();
  view.rerender(<Dialog open={false} onEscape={escape} />);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(escape).not.toHaveBeenCalled();
  document.body.style.overflow = "";
});
