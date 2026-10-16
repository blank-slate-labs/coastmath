import React, { useEffect, useId, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { InlineValidity } from "@/components/inline_validity";
import { confirmDiscard } from "@/components/confirm_dialog";
import { useDialogFocus } from "@/components/use_dialog_focus";

interface FormModalProps {
  open: boolean;
  /** `confirmed` is set when the person already chose to discard their edits here. */
  onClose: (options?: { confirmed?: boolean }) => void;
  title: string;
  children: React.ReactNode;
}

const backdropStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(15, 23, 42, 0.38)",
  zIndex: 1000,
  backdropFilter: "blur(10px)",
};

const panelStyle: React.CSSProperties = {
  position: "fixed",
  top: "50%",
  left: "50%",
  transform: "translate(-50%, -50%)",
  zIndex: 1001,
  width: "min(640px, calc(100vw - 32px))",
  maxWidth: "calc(100vw - 32px)",
  background: "var(--surface-elevated)",
  border: "1px solid var(--surface-border)",
  borderRadius: 16,
  boxShadow: "0 24px 60px rgba(15, 23, 42, 0.22)",
  padding: 20,
  maxHeight: "calc(100vh - 32px)",
  overflowY: "auto",
  overflowX: "hidden",
  animation: "modalEntrance 200ms ease forwards",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 16,
  paddingBottom: 14,
  borderBottom: "1px solid var(--surface-border)",
};

const titleStyle: React.CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 600,
  fontSize: 20,
  margin: 0,
  letterSpacing: "0",
};

const closeButtonStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--text-tertiary)",
  fontSize: 18,
  cursor: "pointer",
  padding: 0,
  lineHeight: 1,
  width: 34,
  height: 34,
  borderRadius: "50%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  transition: "background 200ms ease, color 200ms ease",
  flexShrink: 0,
};

export function FormModal({ open, onClose, title, children }: FormModalProps) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // Edited since it opened. The close button, Escape and a click outside ask before dropping the
  // edits; a form's own Cancel button discards them, as it says.
  const [edited, setEdited] = useState(false);
  const editedRef = useRef(false);
  editedRef.current = edited;
  const requestClose = useRef(() => {});
  requestClose.current = () => {
    // A save in flight closes the dialog itself on success and keeps it on failure; nothing to discard yet.
    if (panel.current?.querySelector('[data-save-pending="true"]')) return;
    if (!editedRef.current) {
      onClose();
      return;
    }
    void confirmDiscard().then((confirmed) => {
      if (confirmed) onClose({ confirmed: true });
    });
  };
  useEffect(() => {
    if (!open) setEdited(false);
  }, [open]);
  useDialogFocus(open, panel, { onEscape: () => requestClose.current() });

  if (!open) return null;

  return ReactDOM.createPortal(
    <>
      <div style={backdropStyle} onClick={() => requestClose.current()} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        style={panelStyle}
        onClick={(e) => e.stopPropagation()}
        data-sample-editor
        data-unsaved-changes={edited || undefined}
        onInput={() => setEdited(true)}
        onChange={() => setEdited(true)}
      >
        <div style={headerStyle}>
          <h2 id={titleId} style={titleStyle}>
            {title}
          </h2>
          <button
            className="modal-close-btn"
            style={closeButtonStyle}
            onClick={() => requestClose.current()}
            aria-label="Close"
            data-sample-view
          >
            &#x2715;
          </button>
        </div>
        <InlineValidity>{children}</InlineValidity>
      </div>
    </>,
    document.body,
  );
}
