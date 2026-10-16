import type { GrowthSegment, GrowthSegmentKind } from "@/types/plan";
import { dollarsOr, moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";

/** One editable schedule row; fields stay text until the form is saved. */
export interface SegmentRow {
  start: string;
  end: string;
  kind: GrowthSegmentKind;
  value: string;
  dollars: "today" | "nominal";
}

const KIND_LABELS: Record<GrowthSegmentKind, string> = {
  percent: "Percent per year",
  inflation_offset: "Inflation plus or minus",
  dollar_change: "Dollar change per year",
  set_amount: "Set amount",
};

const VALUE_LABELS: Record<GrowthSegmentKind, string> = {
  percent: "Change (% per year)",
  inflation_offset: "Points above inflation (+/-)",
  dollar_change: "Change ($ per year)",
  set_amount: "Annual amount ($)",
};

const isDollarKind = (kind: GrowthSegmentKind) => kind === "dollar_change" || kind === "set_amount";

export function segmentRowsFrom(schedule: GrowthSegment[] | null | undefined): SegmentRow[] {
  return (schedule ?? []).map((segment) => ({
    start: String(segment.start_year),
    end: segment.end_year == null ? "" : String(segment.end_year),
    kind: segment.kind,
    value: String(segment.value),
    dollars: segment.dollars ?? "today",
  }));
}

/** Validated schedule for saving: null when there are no rows. */
export function scheduleFromRows(rows: SegmentRow[]): {
  schedule: GrowthSegment[] | null;
  error: string | null;
} {
  if (rows.length === 0) return { schedule: null, error: null };
  const schedule: GrowthSegment[] = [];
  for (const [index, row] of rows.entries()) {
    const label = `Growth segment ${index + 1}`;
    const start = Number(row.start);
    const end = row.end.trim() === "" ? null : Number(row.end);
    const value = Number(row.value);
    if (row.start.trim() === "" || !Number.isInteger(start) || start < 1900 || start > 2200) {
      return { schedule: null, error: `${label}: enter a start year.` };
    }
    if (end !== null && (!Number.isInteger(end) || end < start || end > 2200)) {
      return {
        schedule: null,
        error: `${label}: the end year must be on or after the start year.`,
      };
    }
    if (row.value.trim() === "" || !Number.isFinite(value)) {
      return { schedule: null, error: `${label}: enter a finite value.` };
    }
    if (!isDollarKind(row.kind) && (value < -100 || value > 100)) {
      return { schedule: null, error: `${label}: percentages must be between -100 and 100.` };
    }
    if (row.kind === "set_amount" && value < 0) {
      return { schedule: null, error: `${label}: a set amount cannot be negative.` };
    }
    const previous = schedule[schedule.length - 1];
    if (previous && (previous.end_year === null || previous.end_year >= start)) {
      return {
        schedule: null,
        error:
          "Growth segments must be in year order and must not overlap; give earlier segments an end year.",
      };
    }
    schedule.push({
      start_year: start,
      end_year: end,
      kind: row.kind,
      value,
      dollars: isDollarKind(row.kind) ? row.dollars : null,
    });
  }
  return { schedule, error: null };
}

interface GrowthScheduleEditorProps {
  rows: SegmentRow[];
  onChange: (rows: SegmentRow[]) => void;
  /** First calendar year a new row suggests. */
  defaultStartYear: number;
}

/** Year-segment growth rows inside the income form's growth settings. */
export function GrowthScheduleEditor({
  rows,
  onChange,
  defaultStartYear,
}: GrowthScheduleEditorProps) {
  function update(index: number, patch: Partial<SegmentRow>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }
  function add() {
    const last = rows[rows.length - 1];
    const lastEnd = last && last.end.trim() !== "" ? Number(last.end) : null;
    const lastStart = last ? Number(last.start) : NaN;
    const start =
      lastEnd != null && Number.isFinite(lastEnd)
        ? lastEnd + 1
        : Number.isFinite(lastStart)
          ? lastStart + 1
          : defaultStartYear;
    onChange([
      ...rows,
      { start: String(start), end: "", kind: "percent", value: "", dollars: "today" },
    ]);
  }
  return (
    <fieldset className="growth-schedule" style={{ gridColumn: "1 / -1" }}>
      <legend>Growth schedule (optional)</legend>
      <p style={{ margin: "0 0 8px", fontSize: 12, color: "var(--text-secondary)" }}>
        Each segment changes the amount in the years it covers, starting each January. Years without
        a segment use the growth rate above. The growth cap still applies.
      </p>
      {rows.map((row, index) => (
        <div
          key={index}
          role="group"
          aria-label={`Growth segment ${index + 1}`}
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(120px, 100%), 1fr))",
            gap: 8,
            alignItems: "end",
            marginBottom: 8,
          }}
        >
          <label>
            Start year
            <input
              type="number"
              step={1}
              value={row.start}
              onChange={(e) => update(index, { start: e.target.value })}
            />
          </label>
          <label>
            End year
            <input
              type="number"
              step={1}
              value={row.end}
              placeholder="Ongoing"
              onChange={(e) => update(index, { end: e.target.value })}
            />
          </label>
          <label>
            Change type
            <select
              value={row.kind}
              onChange={(e) => update(index, { kind: e.target.value as GrowthSegmentKind })}
            >
              {(Object.keys(KIND_LABELS) as GrowthSegmentKind[]).map((kind) => (
                <option key={kind} value={kind}>
                  {kind === "dollar_change"
                    ? dollarsOr(KIND_LABELS[kind], "Amount change per year")
                    : KIND_LABELS[kind]}
                </option>
              ))}
            </select>
          </label>
          <label>
            {moneyLabel(VALUE_LABELS[row.kind])}
            {isDollarKind(row.kind) ? (
              <MoneyInput
                step="any"
                value={row.value}
                onValueChange={(value) => update(index, { value })}
              />
            ) : (
              <input
                type="number"
                step="any"
                value={row.value}
                onChange={(e) => update(index, { value: e.target.value })}
              />
            )}
          </label>
          {isDollarKind(row.kind) && (
            <label>
              {dollarsOr("Dollars", "Amount basis")}
              <select
                value={row.dollars}
                onChange={(e) => update(index, { dollars: e.target.value as "today" | "nominal" })}
              >
                <option value="today">{moneyLabel("Today's dollars")}</option>
                <option value="nominal">{moneyLabel("Nominal dollars")}</option>
              </select>
            </label>
          )}
          <button
            type="button"
            aria-label={`Remove growth segment ${index + 1}`}
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            Remove
          </button>
        </div>
      ))}
      <button type="button" onClick={add}>
        Add growth segment
      </button>
    </fieldset>
  );
}
