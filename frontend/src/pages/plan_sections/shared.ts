import { intlCompactCurrency } from "@/utils/format";

/** Compact money in the plan's display currency ("$1.2M" in USD). */
export const compactCurrency = { format: intlCompactCurrency };

// Row chrome (dividers, hover) lives on .plan-list-item in theme.css.
export const listItemStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: "12px",
};

export const itemStackStyle: React.CSSProperties = {
  display: "grid",
  gap: "4px",
  minWidth: 0,
};

export const itemNameStyle: React.CSSProperties = {
  color: "var(--text-primary)",
  fontSize: "14px",
  fontWeight: 500,
};

export const itemDetailStyle: React.CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: "13px",
  lineHeight: 1.5,
};

export const actionGroupStyle: React.CSSProperties = {
  display: "flex",
  gap: "6px",
  flexWrap: "wrap",
  justifyContent: "flex-end",
};
