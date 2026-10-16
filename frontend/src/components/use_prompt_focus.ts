import { useEffect, type RefObject } from "react";
import { FOCUSABLE_SELECTOR } from "./use_dialog_focus";

/**
 * Focus handling for a prompt that sits above the edit sheet and its dialogs:
 * everything else is inert, Tab cycles inside the panel, Escape closes only the
 * prompt, and focus returns to the trigger afterwards.
 */
export function usePromptFocus(
  open: boolean,
  hide: () => void,
  root: RefObject<HTMLElement>,
  panel: RefObject<HTMLElement>,
) {
  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement as HTMLElement | null;
    // Everything else, including other dialogs' portals, is inert while this is open.
    const background = Array.from(document.body.children).filter(
      (node): node is HTMLElement => node instanceof HTMLElement && node !== root.current,
    );
    const wasInert = background.map((node) => node.inert);
    background.forEach((node) => {
      node.inert = true;
    });
    panel.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus();

    // Capture phase, ahead of the edit sheet's and dialogs' own key handling,
    // so Escape closes only this prompt.
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        hide();
      } else if (event.key === "Tab") {
        const controls = Array.from(
          panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? [],
        );
        if (!controls.length) return;
        const index = controls.indexOf(document.activeElement as HTMLElement);
        const next = event.shiftKey
          ? index <= 0
            ? controls.length - 1
            : index - 1
          : (index + 1) % controls.length;
        event.preventDefault();
        event.stopPropagation();
        controls[next].focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      background.forEach((node, i) => {
        node.inert = wasInert[i];
      });
      if (trigger?.isConnected) trigger.focus();
    };
  }, [open, hide, root, panel]);
}
