import { useEffect, useState } from "react";

import type { IntlPerson, IntlStartingRoom, TaxRegimeAccountKind } from "@/types/plan";
import MoneyInput from "@/components/money_input";

export interface RoomSettings {
  starting_room: IntlStartingRoom[];
  prior_year_earned_income: Partial<Record<IntlPerson, number>> | null;
}

interface Draft {
  room: Record<string, string>;
  income: Record<string, string>;
}

const PEOPLE: { id: IntlPerson; label: string }[] = [
  { id: "self", label: "Primary person" },
  { id: "spouse", label: "Partner" },
];

const roomKey = (kind: string, owner: IntlPerson) => `${kind}|${owner}`;

function toDraft(
  room: readonly IntlStartingRoom[],
  income: RoomSettings["prior_year_earned_income"],
): Draft {
  const draft: Draft = { room: {}, income: {} };
  for (const entry of room) draft.room[roomKey(entry.kind, entry.owner)] = String(entry.amount);
  for (const person of PEOPLE) {
    const amount = income?.[person.id];
    if (amount != null) draft.income[person.id] = String(amount);
  }
  return draft;
}

function amountError(text: string | undefined): string | null {
  if (!text || text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) && value >= 0 ? null : "Enter an amount of 0 or more.";
}

/** The settings to save for the draft, or each field's error (blank fields are not saved). */
export function roomSettingsFromDraft(
  draft: Draft,
): { settings: RoomSettings } | { errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const startingRoom: IntlStartingRoom[] = [];
  for (const [key, text] of Object.entries(draft.room)) {
    const error = amountError(text);
    if (error) errors[`room:${key}`] = error;
    else if (text.trim() !== "") {
      const [kind, owner] = key.split("|") as [string, IntlPerson];
      startingRoom.push({ kind, owner, amount: Number(text) });
    }
  }
  const income: Partial<Record<IntlPerson, number>> = {};
  for (const [owner, text] of Object.entries(draft.income)) {
    const error = amountError(text);
    if (error) errors[`income:${owner}`] = error;
    else if (text.trim() !== "") income[owner as IntlPerson] = Number(text);
  }
  if (Object.keys(errors).length > 0) return { errors };
  return {
    settings: {
      starting_room: startingRoom,
      prior_year_earned_income: Object.keys(income).length > 0 ? income : null,
    },
  };
}

const errorStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  color: "var(--color-danger)",
};
const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
  alignItems: "end",
};

/**
 * Contribution room for account kinds whose unused room carries forward,
 * saved in `intl_settings.starting_room` and
 * `intl_settings.prior_year_earned_income`. The server validates them again.
 */
export default function IntlRoomEditor({
  kinds,
  startingRoom,
  priorIncome,
  hasPartner,
  onSave,
}: {
  kinds: readonly TaxRegimeAccountKind[];
  startingRoom: readonly IntlStartingRoom[];
  priorIncome: RoomSettings["prior_year_earned_income"];
  hasPartner: boolean;
  onSave: (settings: RoomSettings) => Promise<void>;
}) {
  const serialized = JSON.stringify([startingRoom, priorIncome ?? null]);
  const [draft, setDraft] = useState<Draft>(() => toDraft(startingRoom, priorIncome));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!dirty) {
      const [room, income] = JSON.parse(serialized) as [
        IntlStartingRoom[],
        RoomSettings["prior_year_earned_income"],
      ];
      setDraft(toDraft(room, income));
    }
  }, [serialized, dirty]);

  const people = PEOPLE.filter(
    (p) =>
      p.id === "self" ||
      hasPartner ||
      startingRoom.some((r) => r.owner === "spouse") ||
      priorIncome?.spouse != null,
  );
  const usesPriorIncome = kinds.some((kind) => kind.uses_prior_year_income);
  // Saved room for a kind the plan's countries no longer offer stays in the draft untouched.
  const listed = new Set(kinds.map((kind) => kind.id));
  const unlisted = startingRoom.filter((entry) => !listed.has(entry.kind));

  function edit(section: keyof Draft, key: string, value: string) {
    setDraft((current) => ({ ...current, [section]: { ...current[section], [key]: value } }));
    setDirty(true);
    setSaved(false);
    setSaveError(null);
  }

  async function save() {
    if (saving) return;
    const result = roomSettingsFromDraft(draft);
    if ("errors" in result) {
      setErrors(result.errors);
      setSaveError("Fix the highlighted amounts, then save.");
      return;
    }
    setErrors({});
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(result.settings);
      setDirty(false);
      setSaved(true);
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error.message
          : "Could not save contribution room. Your changes are kept; retry your save.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <fieldset
      disabled={saving}
      data-testid="intl-room-editor"
      style={{
        display: "grid",
        gap: 6,
        border: 0,
        padding: 0,
        margin: 0,
        minWidth: 0,
        gridColumn: "1 / -1",
      }}
    >
      <div style={{ display: "grid", gap: 2 }}>
        <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Contribution room</span>
        <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
          Unused room carried into the plan&apos;s first year, before that year&apos;s new room.
          Leave blank for none. Unused room carries forward each year.
        </span>
      </div>
      <div style={gridStyle}>
        {kinds.flatMap((kind) =>
          people.map((person) => {
            const key = roomKey(kind.id, person.id);
            const error = errors[`room:${key}`];
            return (
              <label key={key}>
                {kind.label} room{people.length > 1 ? `, ${person.label.toLowerCase()}` : ""}
                <MoneyInput
                  min={0}
                  step="any"
                  value={draft.room[key] ?? ""}
                  aria-invalid={error ? true : undefined}
                  onValueChange={(value) => edit("room", key, value)}
                />
                {error && (
                  <span role="alert" style={errorStyle}>
                    {error}
                  </span>
                )}
              </label>
            );
          }),
        )}
        {usesPriorIncome &&
          people.map((person) => {
            const error = errors[`income:${person.id}`];
            return (
              <label key={`income-${person.id}`}>
                Prior-year earned income{people.length > 1 ? `, ${person.label.toLowerCase()}` : ""}{" "}
                (optional)
                <MoneyInput
                  min={0}
                  step="any"
                  value={draft.income[person.id] ?? ""}
                  aria-invalid={error ? true : undefined}
                  onValueChange={(value) => edit("income", person.id, value)}
                />
                {error && (
                  <span role="alert" style={errorStyle}>
                    {error}
                  </span>
                )}
              </label>
            );
          })}
      </div>
      {usesPriorIncome && (
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-tertiary)" }}>
          New room for{" "}
          {kinds
            .filter((k) => k.uses_prior_year_income)
            .map((k) => k.label)
            .join(" and ")}{" "}
          is a share of the prior year&apos;s earned income. Without the prior-year income, the
          first year uses its own earnings.
        </p>
      )}
      {unlisted.length > 0 && (
        <p style={{ margin: 0, fontSize: 12 }}>
          Room saved for an account kind this plan no longer uses is kept.
        </p>
      )}
      {saveError && <p role="alert">{saveError}</p>}
      {dirty && <p role="status">Unsaved contribution room changes.</p>}
      {saved && <p role="status">Contribution room saved.</p>}
      <button type="button" className="btn-primary" disabled={!dirty || saving} onClick={save}>
        {saving ? "Saving…" : "Save contribution room"}
      </button>
    </fieldset>
  );
}
