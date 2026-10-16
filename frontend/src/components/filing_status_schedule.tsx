import { useState } from "react";
import type { FilingStatusChange, FilingStatus, Milestone } from "../types/plan";

export default function FilingStatusSchedule({
  initial,
  milestones,
  onSave,
}: {
  initial: FilingStatusChange[];
  milestones: Milestone[];
  onSave: (rows: FilingStatusChange[]) => Promise<unknown>;
}) {
  const [rows, setRows] = useState(initial);
  const [savedRows, setSavedRows] = useState(initial);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(rows) !== JSON.stringify(savedRows);
  const update = (index: number, patch: Partial<FilingStatusChange>) =>
    setRows(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  async function save() {
    if (
      rows.some(
        (row) =>
          !row.milestone_id &&
          (!Number.isInteger(row.year) || (row.year ?? 0) < 1900 || (row.year ?? 0) > 2300),
      )
    ) {
      setError("Enter a year from 1900 to 2300 or choose a milestone.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await onSave(rows);
      setSavedRows(rows);
    } catch {
      setError("Could not save filing status changes. Your edits are retained.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <fieldset data-unsaved-changes={dirty || undefined} data-save-pending={saving || undefined}>
      <legend>Filing status changes</legend>
      <p>
        Year-end marital status applies to the whole tax year. Death-related changes take
        precedence.
      </p>
      {rows.map((row, index) => (
        <div key={index}>
          <label>
            Change year
            <input
              type="number"
              min={1900}
              max={2300}
              value={row.year ?? ""}
              disabled={!!row.milestone_id}
              onChange={(e) => update(index, { year: Number(e.target.value) })}
            />
          </label>
          <label>
            Change milestone
            <select
              value={row.milestone_id ?? ""}
              onChange={(e) =>
                update(index, {
                  milestone_id: e.target.value || null,
                  year: e.target.value ? null : new Date().getFullYear(),
                })
              }
            >
              <option value="">Use year</option>
              {milestones.map((ms) => (
                <option key={ms.id} value={ms.id}>
                  {ms.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            New filing status
            <select
              value={row.filing_status}
              onChange={(e) => update(index, { filing_status: e.target.value as FilingStatus })}
            >
              <option value="single">Single</option>
              <option value="married_filing_jointly">Married filing jointly</option>
              <option value="married_filing_separately">Married filing separately</option>
              <option value="head_of_household">Head of household</option>
            </select>
          </label>
          <button type="button" onClick={() => setRows(rows.filter((_, i) => i !== index))}>
            Remove change
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() =>
          setRows([
            ...rows,
            { year: new Date().getFullYear(), filing_status: "married_filing_jointly" },
          ])
        }
      >
        Add filing status change
      </button>
      <button type="button" disabled={saving || !dirty} onClick={save}>
        {saving ? "Saving…" : "Save filing status changes"}
      </button>
      {error && <p role="alert">{error}</p>}
    </fieldset>
  );
}
