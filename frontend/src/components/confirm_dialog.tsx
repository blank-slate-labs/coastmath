import { useEffect, useId, useRef } from "react";
import { createRoot } from "react-dom/client";

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel: string;
  cancelLabel?: string;
}

const backdropStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 1100,
  display: "grid",
  placeItems: "center",
  padding: 16,
  background: "rgba(15, 23, 42, 0.38)",
};

const panelStyle: React.CSSProperties = {
  width: "min(400px, 100%)",
  background: "var(--surface-elevated)",
  border: "1px solid var(--surface-border)",
  borderRadius: 16,
  boxShadow: "0 24px 60px rgba(15, 23, 42, 0.22)",
  padding: 20,
  display: "grid",
  gap: 12,
};

function ConfirmDialog({
  title,
  message,
  confirmLabel,
  cancelLabel = "Keep editing",
  onSettle,
}: ConfirmOptions & { onSettle: (confirmed: boolean) => void }) {
  const panel = useRef<HTMLDivElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const messageId = useId();
  useEffect(() => {
    cancel.current?.focus();
  }, []);

  // Keys stop here, so the editor or dialog behind does not act on them too.
  function onKeyDown(event: React.KeyboardEvent) {
    event.stopPropagation();
    if (event.key === "Escape") {
      event.preventDefault();
      onSettle(false);
    }
    if (event.key === "Tab") {
      const buttons = Array.from(panel.current?.querySelectorAll("button") ?? []);
      const next =
        buttons[
          (buttons.indexOf(document.activeElement as HTMLButtonElement) +
            (event.shiftKey ? -1 : 1) +
            buttons.length) %
            buttons.length
        ];
      event.preventDefault();
      next?.focus();
    }
  }

  return (
    <div style={backdropStyle} onClick={() => onSettle(false)}>
      <div
        ref={panel}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={message ? messageId : undefined}
        style={panelStyle}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <h2 id={titleId} style={{ margin: 0, fontSize: 17 }}>
          {title}
        </h2>
        {message && (
          <p id={messageId} style={{ margin: 0 }}>
            {message}
          </p>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button ref={cancel} type="button" onClick={() => onSettle(false)}>
            {cancelLabel}
          </button>
          <button type="button" className="btn-primary" onClick={() => onSettle(true)}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * The app's own confirmation, used instead of window.confirm, which blocks the tab.
 * Resolves true on confirm; false on cancel, Escape or a click outside.
 */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  const trigger = document.activeElement as HTMLElement | null;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  return new Promise((resolve) => {
    const settle = (confirmed: boolean) => {
      host.hidden = true;
      // Unmount after the click or key handler that settled it has returned.
      queueMicrotask(() => {
        root.unmount();
        host.remove();
      });
      if (!confirmed && trigger?.isConnected) trigger.focus();
      resolve(confirmed);
    };
    root.render(<ConfirmDialog {...options} onSettle={settle} />);
  });
}

/** Asks before unsaved edits are discarded. */
export function confirmDiscard(message?: string): Promise<boolean> {
  return confirmDialog({
    title: "Discard unsaved changes?",
    message,
    confirmLabel: "Discard changes",
  });
}

/** Asks before an item is deleted; nothing in the editors undoes a delete. */
export function confirmDelete(name: string, message?: string): Promise<boolean> {
  return confirmDialog({
    title: `Delete “${name}”?`,
    message,
    confirmLabel: "Delete",
    cancelLabel: "Keep it",
  });
}
