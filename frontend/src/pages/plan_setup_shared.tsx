import { createContext, useCallback, useContext, useEffect, useId, useState } from "react";

import { usePlanStore } from "@/stores/plan_store";
import { US_STATE_OPTIONS } from "@/domain/us_states";
import type { FilingStatus } from "@/types/plan";

/**
 * How a builder section paints itself.
 * - "stack": the classic collapsible accordion (kept for the PlanSetup
 *   composition root and any legacy consumer).
 * - "sheet": rendered inside the Edit sheet, where the slide-over already
 *   owns the title, so the section shows just its editor plus
 *   any inline "Add" action — always expanded, no localStorage persistence.
 */
export type BuilderMode = "stack" | "sheet";
export const BuilderModeContext = createContext<BuilderMode>("stack");

export const filingStatuses: { value: FilingStatus; label: string }[] = [
  { value: "single", label: "Single" },
  { value: "married_filing_jointly", label: "Married Filing Jointly" },
  { value: "married_filing_separately", label: "Married Filing Separately" },
  { value: "head_of_household", label: "Head of Household" },
];

export const usStates = US_STATE_OPTIONS;

// Longevity tops out at 120, so nobody born earlier can still be planned for.
export const EARLIEST_BIRTH_YEAR = new Date().getFullYear() - 120;

export const sectionStyle: React.CSSProperties = {
  padding: "0 0 20px",
  marginBottom: "4px",
  borderBottom: "1px solid var(--surface-border)",
};

const sectionHeaderStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: "12px",
  flexWrap: "wrap",
  marginBottom: "16px",
};

const sectionHeaderCopyStyle: React.CSSProperties = {
  display: "grid",
  gap: "4px",
  flex: "1 1 160px",
  minWidth: 0,
};

const sectionTitleRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "10px",
  flexWrap: "wrap",
};

const sectionTitleStyle: React.CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
  fontSize: "16px",
  fontWeight: 500,
  letterSpacing: "0",
};

const sectionCountStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "2px 8px",
  borderRadius: 999,
  border: "none",
  background: "var(--gray-100)",
  color: "var(--gray-500)",
  fontSize: "11px",
  fontWeight: 500,
  letterSpacing: "0",
  textTransform: "none",
};

export const formGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr",
  gap: "14px",
};

export const addBtnStyle: React.CSSProperties = {
  minHeight: 34,
  padding: "0 10px",
  borderRadius: 10,
  fontSize: "13px",
  fontWeight: 500,
  width: "100%",
  maxWidth: "100%",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

export const actionBtnStyle: React.CSSProperties = {
  maxWidth: "100%",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

export const deleteBtnStyle: React.CSSProperties = {
  maxWidth: "100%",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

const emptyStateStyle: React.CSSProperties = {
  position: "relative",
  padding: "16px",
  borderRadius: 12,
  border: "none",
  background: "transparent",
  color: "var(--text-tertiary)",
  fontSize: "13px",
  lineHeight: 1.7,
};

export function EmptyState({ message }: { message: string }) {
  return <div style={emptyStateStyle}>{message}</div>;
}

export function CollapsibleSection({
  id,
  title,
  count,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  action,
  sheetNote,
  children,
}: {
  id?: string;
  title: string;
  count?: number;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  action?: React.ReactNode;
  /** What the sheet's own title cannot say, shown beside the action there. */
  sheetNote?: string;
  children: React.ReactNode;
}) {
  const mode = useContext(BuilderModeContext);
  const planId = usePlanStore((s) => s.plan?.id);
  const storageKey = `coastmath:builder:${planId}:${title}`;
  const readOpen = useCallback(() => {
    try {
      const value = localStorage.getItem(storageKey);
      return value === null ? defaultOpen : value === "true";
    } catch {
      return defaultOpen;
    }
  }, [storageKey, defaultOpen]);
  const [internalOpen, setInternalOpen] = useState(readOpen);
  useEffect(() => {
    if (mode === "sheet") return;
    const saved = readOpen();
    setInternalOpen(saved);
    onOpenChange?.(saved);
  }, [readOpen, mode, onOpenChange]);
  const open = controlledOpen ?? internalOpen;
  const contentId = useId();

  // Inside the Edit sheet the slide-over header already carries the section
  // title, so drop the accordion chrome and always show the
  // editor. The optional "Add" action rides along the top of
  // the body. The wrapper keeps its id (e.g. #income-allocation) so deep
  // links and scroll targets keep working.
  if (mode === "sheet") {
    return (
      <div id={id} className="edit-sheet-section" tabIndex={id ? -1 : undefined}>
        {/* The list and the sidebar already show how many there are; the sheet adds no count. */}
        {(action || sheetNote) && (
          <div className="edit-sheet-section-head">
            {sheetNote ? <p className="edit-sheet-section-note">{sheetNote}</p> : <span />}
            {action && <div className="edit-sheet-section-action">{action}</div>}
          </div>
        )}
        {children}
      </div>
    );
  }

  return (
    <div id={id} style={sectionStyle} tabIndex={id ? -1 : undefined}>
      <div
        style={{
          ...sectionHeaderStyle,
          marginBottom: open ? "16px" : 0,
        }}
      >
        <div style={sectionHeaderCopyStyle}>
          <h2 style={sectionTitleStyle}>
            <button
              type="button"
              className="btn-ghost builder-section-toggle"
              style={sectionTitleRowStyle}
              data-sample-view
              aria-expanded={open}
              aria-controls={contentId}
              onClick={() => {
                setInternalOpen(!open);
                try {
                  localStorage.setItem(storageKey, String(!open));
                } catch {
                  /* browser storage unavailable */
                }
                onOpenChange?.(!open);
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  display: "inline-block",
                  transition: "transform 0.2s ease",
                  transform: open ? "rotate(90deg)" : "rotate(0deg)",
                  fontSize: 10,
                  color: "var(--text-tertiary)",
                }}
              >
                &#9654;
              </span>
              {title}
              {count != null && <span style={sectionCountStyle}>{count}</span>}
            </button>
          </h2>
        </div>
        {action && open && (
          <div
            style={{ flex: "1 1 100%", minWidth: 0, maxWidth: "100%" }}
            onClick={(e) => e.stopPropagation()}
          >
            {action}
          </div>
        )}
      </div>
      <div id={contentId} hidden={!open}>
        {children}
      </div>
    </div>
  );
}
