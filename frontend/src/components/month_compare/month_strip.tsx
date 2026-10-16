import { useId, useState } from "react";
import { scaleLinear } from "d3-scale";
import type { LedgerMonth, MonthSource } from "@/api/ledger";
import { money, monthLabel, muted, row } from "@/components/ledger/ledger_format";
import { reasonText } from "./month_format";

const BAR_WIDTH = 28;
const BAR_HEIGHT = 72;
const ESSENTIAL = "var(--chart-1, #3b6ea8)";
const DISCRETIONARY = "var(--chart-2, #e0a040)";
const TAKE_HOME = "var(--text-primary, #222)";
// The strip sits on a card, so the segmented control's white "active" chip is invisible here.
const SELECTED = "var(--brand-primary)";
const SELECTED_FILL = "var(--brand-primary-light)";

/**
 * Months as toggle buttons, each a stacked essential/discretionary bar with a
 * take-home marker. Incomplete months stay focusable but cannot be chosen;
 * hovering or focusing one shows why.
 */
export default function MonthStrip({
  months,
  sources,
  currency,
  selected,
  full,
  onToggle,
}: {
  months: LedgerMonth[];
  sources: MonthSource[];
  currency: string;
  selected: string[];
  full: boolean;
  onToggle: (month: string) => void;
}) {
  const hintId = useId();
  const [focused, setFocused] = useState<string | null>(null);
  const top = Math.max(
    1,
    ...months.map((m) => Math.max(0, m.essential) + Math.max(0, m.discretionary)),
    ...months.map((m) => m.income),
  );
  const y = scaleLinear().domain([0, top]).range([BAR_HEIGHT, 0]);
  const hinted = months.find((m) => m.month === focused) ?? null;
  const hint =
    hinted &&
    (hinted.complete
      ? `${monthLabel(hinted.month)}: essential ${money(hinted.essential, currency)}, discretionary ${money(hinted.discretionary, currency)}, take-home ${money(hinted.income, currency)}.`
      : `${monthLabel(hinted.month)}: ${reasonText(hinted, sources)}`);

  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div
        role="group"
        aria-label="Months"
        style={{ ...row, gap: 4, overflowX: "auto", flexWrap: "nowrap", paddingBottom: 4 }}
      >
        {months.map((m) => {
          const essential = Math.max(0, m.essential);
          const discretionary = Math.max(0, m.discretionary);
          const isSelected = selected.includes(m.month);
          const unavailable = !m.complete || (full && !isSelected);
          return (
            <button
              key={m.month}
              type="button"
              data-month={m.month}
              aria-pressed={isSelected}
              aria-disabled={unavailable ? "true" : undefined}
              aria-describedby={focused === m.month ? hintId : undefined}
              className="seg-option"
              style={{
                display: "grid",
                justifyItems: "center",
                gap: 2,
                padding: "4px 2px",
                minWidth: BAR_WIDTH + 16,
                border: `2px solid ${isSelected ? SELECTED : "transparent"}`,
                borderRadius: 8,
                background: isSelected ? SELECTED_FILL : "transparent",
                boxShadow: "none",
                color: isSelected ? SELECTED : undefined,
                fontWeight: isSelected ? 600 : undefined,
                opacity: m.complete ? 1 : 0.45,
                cursor: unavailable ? "not-allowed" : "pointer",
              }}
              onMouseEnter={() => setFocused(m.month)}
              onMouseLeave={() => setFocused(null)}
              onFocus={() => setFocused(m.month)}
              onBlur={() => setFocused(null)}
              onClick={() => {
                if (!unavailable) onToggle(m.month);
              }}
            >
              <svg width={BAR_WIDTH} height={BAR_HEIGHT} aria-hidden="true">
                <rect
                  x={4}
                  y={y(essential)}
                  width={BAR_WIDTH - 8}
                  height={BAR_HEIGHT - y(essential)}
                  fill={ESSENTIAL}
                />
                <rect
                  x={4}
                  y={y(essential + discretionary)}
                  width={BAR_WIDTH - 8}
                  height={y(essential) - y(essential + discretionary)}
                  fill={DISCRETIONARY}
                />
                {!m.complete && (
                  <rect
                    x={4.5}
                    y={0.5}
                    width={BAR_WIDTH - 9}
                    height={BAR_HEIGHT - 1}
                    fill="none"
                    stroke="currentColor"
                    strokeDasharray="3 3"
                  />
                )}
                {m.income > 0 && (
                  <line
                    data-take-home
                    x1={0}
                    x2={BAR_WIDTH}
                    y1={y(m.income)}
                    y2={y(m.income)}
                    stroke={TAKE_HOME}
                    strokeWidth={2}
                  />
                )}
              </svg>
              <span style={{ fontSize: 11 }}>{monthLabel(m.month)}</span>
            </button>
          );
        })}
      </div>
      <p id={hintId} role="status" style={{ ...muted, minHeight: "1.5em", margin: 0 }}>
        {hint ?? ""}
      </p>
      <div style={{ ...row, ...muted }} aria-hidden="true">
        <span>
          <svg width="10" height="10">
            <rect width="10" height="10" fill={ESSENTIAL} />
          </svg>{" "}
          Essential
        </span>
        <span>
          <svg width="10" height="10">
            <rect width="10" height="10" fill={DISCRETIONARY} />
          </svg>{" "}
          Discretionary
        </span>
        <span>
          <svg width="14" height="10">
            <line x1="0" x2="14" y1="5" y2="5" stroke={TAKE_HOME} strokeWidth="2" />
          </svg>{" "}
          Take-home
        </span>
      </div>
    </div>
  );
}
