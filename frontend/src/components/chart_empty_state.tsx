import type { ReactNode } from "react";

interface ChartEmptyStateProps {
  /** What to do before the chart can show anything. */
  message: ReactNode;
  /** Path elements for a 24×24 outline icon drawn above the message. */
  icon?: ReactNode;
}

/** Centred, muted placeholder for an analysis page that has nothing to chart yet. */
export function ChartEmptyState({ message, icon }: ChartEmptyStateProps) {
  return (
    <div
      style={{
        padding: 60,
        color: "var(--text-tertiary)",
        textAlign: "center",
        fontSize: 14,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
      }}
    >
      {icon && (
        <svg
          width="40"
          height="40"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--gray-300)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {icon}
        </svg>
      )}
      {message}
    </div>
  );
}
