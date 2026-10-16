import type { ReactNode } from "react";

/** Keeps Cancel and submit in view at the bottom of a long row form. */
const footerStyle: React.CSSProperties = {
  gridColumn: "1 / -1",
  display: "flex",
  gap: 8,
  justifyContent: "flex-end",
  flexWrap: "wrap",
  position: "sticky",
  bottom: -14,
  paddingTop: 10,
  paddingBottom: 2,
  background: "var(--gray-50)",
};

interface FormFooterProps {
  onCancel: () => void;
  /** Text of the submit button. */
  submitLabel: ReactNode;
  /** Further actions shown between Cancel and submit. */
  children?: ReactNode;
}

/** Sticky Cancel and submit row shared by the plan row forms. */
export function FormFooter({ onCancel, submitLabel, children }: FormFooterProps) {
  return (
    <div style={footerStyle}>
      <button type="button" onClick={onCancel} data-sample-view>
        Cancel
      </button>
      {children}
      <button type="submit">{submitLabel}</button>
    </div>
  );
}
