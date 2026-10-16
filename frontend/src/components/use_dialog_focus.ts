import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

/** Controls that take keyboard focus inside a dialog. */
export const FOCUSABLE_SELECTOR =
  'button:not(:disabled), input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]';

interface DialogFocusOptions {
  /** Runs on Escape while the dialog is active. */
  onEscape: () => void;
  /** Returns false while another dialog is on top, so Escape and Tab act on that one instead. */
  isActive?: () => boolean;
}

/** The panel's tabbable controls in order, skipping hidden ones and the insides of closed `details`. */
function tabbableControls(panel: HTMLElement | null): HTMLElement[] {
  return Array.from(panel?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? []).filter(
    (el) =>
      !el.closest("[hidden]") &&
      el.getAttribute("aria-hidden") !== "true" &&
      (!el.closest("details:not([open])") ||
        (el.tagName === "SUMMARY" && el.parentElement === el.closest("details:not([open])"))),
  );
}

/**
 * Focus handling for a modal dialog while `open`: the app behind (`#root`) is inert and the body
 * does not scroll, the panel takes focus, Tab wraps between its first and last controls, Escape
 * calls `onEscape`, and focus returns to the trigger afterwards. Runs once per opening; the
 * latest `onEscape` and `isActive` are used without re-running it.
 */
export function useDialogFocus(
  open: boolean,
  panel: RefObject<HTMLElement>,
  { onEscape, isActive }: DialogFocusOptions,
) {
  const handlers = useRef({ onEscape, isActive });
  useLayoutEffect(() => {
    handlers.current = { onEscape, isActive };
  });

  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement as HTMLElement | null;
    const root = document.getElementById("root");
    const wasInert = root?.inert ?? false;
    if (root) root.inert = true;
    panel.current?.focus();

    const handleKey = (e: KeyboardEvent) => {
      const active = handlers.current.isActive;
      if (active && !active()) return;
      if (e.key === "Escape") {
        e.preventDefault();
        handlers.current.onEscape();
        return;
      }
      if (e.key === "Tab") {
        const controls = tabbableControls(panel.current);
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (!first) {
          e.preventDefault();
          panel.current?.focus();
        } else if (
          e.shiftKey &&
          (document.activeElement === first || document.activeElement === panel.current)
        ) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = originalOverflow;
      document.removeEventListener("keydown", handleKey);
      if (root) root.inert = wasInert;
      if (trigger?.isConnected) trigger.focus();
    };
  }, [open, panel]);
}
