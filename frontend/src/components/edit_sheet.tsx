import { useEffect, useId, useRef } from "react";
import { failedSaveText, useSaveStore } from "@/stores/save_store";
import ReactDOM from "react-dom";
import { confirmDiscard } from "./confirm_dialog";
import { useDialogFocus } from "./use_dialog_focus";

import { usePlanStore } from "@/stores/plan_store";
import { BuilderModeContext, PLAN_SECTIONS } from "@/pages/plan_setup";

interface EditSheetProps {
  /** Index into PLAN_SECTIONS of the section currently shown. */
  index: number;
  historyRequest?: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}

/**
 * Right-anchored slide-over for editing one plan section at a time. The
 * dashboard keeps updating live behind it as edits save. Nested FormModals
 * (add/edit dialogs) portal above this sheet via their higher z-index.
 */
export default function EditSheet({
  index,
  onIndexChange,
  onClose,
  historyRequest = 0,
}: EditSheetProps) {
  const { pending, failed, failures, lastSavedAt } = useSaveStore();
  const planId = usePlanStore((s) => s.plan?.id);
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();

  const section = PLAN_SECTIONS[index];
  const visible = Boolean(section && planId);

  // Mount-time concerns: body scroll lock, make the app behind inert, trap
  // focus, restore focus to the trigger on close. Runs once for the sheet's
  // lifetime — navigating between sections does not re-run it.
  useDialogFocus(visible, panelRef, {
    onEscape: () => leave(onClose),
    // A nested FormModal (add/edit dialog) portals above this sheet and runs
    // its own focus trap + Escape handler. While one is open, stand down so
    // Escape/Tab act on the dialog, not the sheet behind it.
    isActive: () => {
      const dialogs = document.querySelectorAll('[role="dialog"][aria-modal="true"]');
      return !dialogs.length || dialogs[dialogs.length - 1] === panelRef.current;
    },
  });

  useEffect(() => {
    if (!visible) return;
    // Deleting a row removes the focused button and drops focus to <body> behind the modal sheet.
    // Remember where focus was, and move it to the next row (else the previous one, else the
    // control now at the same position) when that happens.
    const panel = panelRef.current;
    let lastFocus: { index: number; next: Element | null; previous: Element | null } | null = null;
    const focusable = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href]",
        ) ?? [],
      );
    const handleFocusIn = (e: FocusEvent) => {
      const row = (e.target as HTMLElement).closest(".plan-list-item");
      lastFocus = {
        index: focusable().indexOf(e.target as HTMLElement),
        next: row?.nextElementSibling?.matches(".plan-list-item") ? row.nextElementSibling : null,
        previous: row?.previousElementSibling?.matches(".plan-list-item")
          ? row.previousElementSibling
          : null,
      };
    };
    const restoreFocus = new MutationObserver(() => {
      if (document.activeElement && document.activeElement !== document.body) return;
      const dialogs = document.querySelectorAll(
        '[role="dialog"][aria-modal="true"], [role="alertdialog"]',
      );
      if (!panel || dialogs[dialogs.length - 1] !== panel || !lastFocus) return;
      const controls = focusable();
      const target =
        [lastFocus.next, lastFocus.previous]
          .find((row) => row?.isConnected)
          ?.querySelector<HTMLElement>("button:not(:disabled)") ??
        (lastFocus.index >= 0
          ? controls[Math.min(lastFocus.index, controls.length - 1)]
          : undefined);
      (target ?? panel).focus();
    });
    panel?.addEventListener("focusin", handleFocusIn);
    if (panel) restoreFocus.observe(panel, { childList: true, subtree: true });
    return () => {
      panel?.removeEventListener("focusin", handleFocusIn);
      restoreFocus.disconnect();
    };
  }, [visible]);

  // Leaving a section discards its drafts, so a rejected save's message goes with them.
  useEffect(() => {
    if (!visible) return;
    useSaveStore.getState().setAnnouncer("sheet");
    return () => useSaveStore.getState().setAnnouncer("header");
  }, [visible]);
  useEffect(() => () => useSaveStore.getState().discardAllRejected(), [section?.key]);

  /** Runs `then` unless a save is in flight, asking first when a form holds unsaved changes. */
  function leave(then: () => void) {
    if (panelRef.current?.querySelector('[data-save-pending="true"]')) return;
    if (!panelRef.current?.querySelector('[data-unsaved-changes="true"]')) {
      then();
      return;
    }
    void confirmDiscard().then((confirmed) => {
      if (confirmed) then();
    });
  }

  useEffect(() => {
    if (!historyRequest || section?.key !== "plan_details") return;
    const history = panelRef.current?.querySelector<HTMLDetailsElement>("#year-to-date-history");
    if (history) {
      // The history may sit inside a collapsed group (Advanced tax settings); open every level.
      for (
        let node: HTMLElement | null = history;
        node;
        node = node.parentElement?.closest("details") ?? null
      ) {
        if (node instanceof HTMLDetailsElement) node.open = true;
      }
      history.scrollIntoView({ block: "start" });
      history.querySelector<HTMLInputElement>("input")?.focus({ preventScroll: true });
    }
  }, [historyRequest, section?.key]);

  if (!section || !planId) return null;

  const SectionComponent = section.Component;

  return ReactDOM.createPortal(
    <div className="edit-sheet-root">
      <div className="edit-sheet-backdrop" onClick={() => leave(onClose)} />
      <div
        ref={panelRef}
        className="edit-sheet-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-sample-editor
      >
        <header className="edit-sheet-header">
          <div className="edit-sheet-heading">
            <span className="edit-sheet-kicker">
              {section.essential ? "Essential" : "Optional"}
            </span>
            <h2 id={titleId} className="edit-sheet-title">
              {section.title}
            </h2>
          </div>
          <button
            type="button"
            className="edit-sheet-close"
            onClick={() => leave(onClose)}
            aria-label="Close editor"
            data-sample-view
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </header>

        <div className="edit-sheet-body left-pane-form">
          <BuilderModeContext.Provider value="sheet">
            <SectionComponent key={`${planId}:${section.key}`} />
          </BuilderModeContext.Provider>
        </div>

        <footer className="edit-sheet-footer">
          <label className="editor-section-picker" data-sample-view>
            Go to section
            <select
              value={index}
              onChange={(e) => {
                const next = Number(e.target.value);
                leave(() => onIndexChange(next));
              }}
            >
              <optgroup label="Essentials">
                {PLAN_SECTIONS.map((item, i) =>
                  item.essential ? (
                    <option key={item.key} value={i}>
                      {item.title}
                    </option>
                  ) : null,
                )}
              </optgroup>
              <optgroup label="Optional">
                {PLAN_SECTIONS.map((item, i) =>
                  !item.essential ? (
                    <option key={item.key} value={i}>
                      {item.title}
                    </option>
                  ) : null,
                )}
              </optgroup>
            </select>
          </label>
          {/* Only the short state is live; the editor's own alert announces a failure's detail once. */}
          <span className="editor-save-status">
            <span role="status">
              {pending
                ? "Saving…"
                : failed.length
                  ? "Not saved."
                  : lastSavedAt
                    ? `Saved at ${new Date(lastSavedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
                    : ""}
            </span>
            {!pending && failed.length > 0 && (
              <span aria-hidden="true"> {failedSaveText({ failed, failures })}</span>
            )}
          </span>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
