import { useState } from "react";

import type { PlanData } from "@/types/plan";

export const NOTES_MAX_LENGTH = 20_000;

interface PlanNotesFormProps {
  plan: PlanData;
  onSave: (planId: string, notes: string | null) => void | Promise<void>;
}

/**
 * Free-text record of the reasoning behind a plan's assumptions. Stored and
 * rendered as plain text only.
 */
export default function PlanNotesForm({ plan, onSave }: PlanNotesFormProps) {
  const [notes, setNotes] = useState(plan.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = notes !== (plan.notes ?? "");
  const tooLong = notes.length > NOTES_MAX_LENGTH;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    if (tooLong) {
      setError(`Notes must be ${NOTES_MAX_LENGTH.toLocaleString()} characters or fewer.`);
      return;
    }
    setSaving(true);
    Promise.resolve(onSave(plan.id, notes.trim() === "" ? null : notes))
      .then(() => setSaved(true))
      .catch(() => setError("Could not save notes. Your text is retained; try again."))
      .finally(() => setSaving(false));
  }

  return (
    <form
      onSubmit={handleSubmit}
      data-unsaved-changes={dirty || undefined}
      data-save-pending={saving || undefined}
      style={{ display: "grid", gap: 8 }}
    >
      <fieldset
        disabled={saving}
        style={{ border: 0, padding: 0, minWidth: 0, display: "grid", gap: 8 }}
      >
        <label>
          Plan notes
          <textarea
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              setSaved(false);
            }}
            rows={8}
            placeholder="Why these assumptions? What to revisit and when?"
            style={{
              display: "block",
              width: "100%",
              resize: "vertical",
              fontFamily: "inherit",
              fontSize: 13,
              textTransform: "none",
            }}
          />
          <span
            style={{
              display: "block",
              fontSize: 12,
              color: tooLong ? "var(--color-danger)" : "var(--text-secondary)",
              textTransform: "none",
              letterSpacing: "normal",
              fontWeight: 400,
              marginTop: 4,
            }}
          >
            {notes.length.toLocaleString()} / {NOTES_MAX_LENGTH.toLocaleString()} characters · plain
            text, saved with the plan
          </span>
        </label>
        {error && (
          <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
            {error}
          </div>
        )}
        <button type="submit" disabled={!dirty || tooLong}>
          {saving ? "Saving…" : "Save notes"}
        </button>
      </fieldset>
      {saved && (
        <p role="status" style={{ margin: 0, fontSize: 13 }}>
          Notes saved.
        </p>
      )}
    </form>
  );
}
