import type { BondGlidePoint } from "@/types/plan";

export type GlideBasis = "year" | "age";
export interface GlideRow {
  x: string;
  percent: string;
}

/** The server accepts at most 20 points. */
const MAX_POINTS = 20;

export function glideRowsFrom(points: BondGlidePoint[] | null | undefined): {
  basis: GlideBasis;
  rows: GlideRow[];
} {
  const list = points ?? [];
  const basis: GlideBasis = list.some((p) => p.age != null) ? "age" : "year";
  return {
    basis,
    rows: list.map((p) => ({
      x: String((basis === "age" ? p.age : p.year) ?? ""),
      percent: String(Number((p.bond_allocation * 100).toFixed(6))),
    })),
  };
}

export function glideError(basis: GlideBasis, rows: GlideRow[]): string | null {
  for (const row of rows) {
    const x = Number(row.x),
      percent = Number(row.percent);
    if (row.x.trim() === "" || row.percent.trim() === "")
      return "Fill in or remove each glide path row.";
    if (
      basis === "year" ? !(Number.isInteger(x) && x >= 1900 && x <= 2200) : !(x >= 0 && x <= 130)
    ) {
      return basis === "year"
        ? "Glide path years run from 1900 to 2200."
        : "Glide path ages run from 0 to 130.";
    }
    if (!(percent >= 0 && percent <= 100)) return "Glide path bond shares run from 0% to 100%.";
  }
  return null;
}

/** Wire points in the server's key order, so an unchanged path compares equal. */
export function glidePoints(basis: GlideBasis, rows: GlideRow[]): BondGlidePoint[] {
  return rows.map((row) => ({
    year: basis === "year" ? Number(row.x) : null,
    age: basis === "age" ? Number(row.x) : null,
    bond_allocation: Number(row.percent) / 100,
  }));
}

interface BondGlideFieldsProps {
  basis: GlideBasis;
  rows: GlideRow[];
  error: string | null;
  onChange: (basis: GlideBasis, rows: GlideRow[]) => void;
}

/** A few year- or age-keyed bond share points for one account. */
export default function BondGlideFields({ basis, rows, error, onChange }: BondGlideFieldsProps) {
  const update = (index: number, patch: Partial<GlideRow>) =>
    onChange(
      basis,
      rows.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  return (
    <fieldset
      style={{ gridColumn: "1 / -1", border: 0, padding: 0, margin: 0, display: "grid", gap: 8 }}
      aria-describedby={error ? "bond_glide_error" : undefined}
    >
      <legend style={{ fontSize: 13 }}>
        Bond glide path — replaces the bond allocation above when set
      </legend>
      <label style={{ maxWidth: 220 }}>
        Points by
        <select
          value={basis}
          onChange={(e) => onChange(e.target.value as GlideBasis, rows)}
          aria-label="Glide path points by"
        >
          <option value="year">Calendar year</option>
          <option value="age">Owner's age</option>
        </select>
      </label>
      {rows.map((row, i) => (
        <div key={i} style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
          <label>
            {basis === "year" ? "Year" : "Age"}
            <input
              type="number"
              step={basis === "year" ? 1 : 0.5}
              value={row.x}
              onChange={(e) => update(i, { x: e.target.value })}
              aria-label={`Glide path ${basis} ${i + 1}`}
            />
          </label>
          <label>
            Bonds (%)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={row.percent}
              onChange={(e) => update(i, { percent: e.target.value })}
              aria-label={`Glide path bonds ${i + 1} (%)`}
            />
          </label>
          <button
            type="button"
            onClick={() =>
              onChange(
                basis,
                rows.filter((_, j) => j !== i),
              )
            }
            aria-label={`Remove glide path point ${i + 1}`}
          >
            Remove
          </button>
        </div>
      ))}
      <div>
        <button
          type="button"
          disabled={rows.length >= MAX_POINTS}
          onClick={() => onChange(basis, [...rows, { x: "", percent: "" }])}
        >
          Add glide path point
        </button>
      </div>
      <p style={{ margin: 0, fontSize: 12, color: "var(--gray-600)" }}>
        Straight lines between points; constant before the first and after the last.
      </p>
      {error && (
        <p id="bond_glide_error" role="alert" style={{ margin: 0, fontSize: 12 }}>
          {error}
        </p>
      )}
    </fieldset>
  );
}
