import { useEffect, useState } from "react";

import type { StorageAdapter } from "@/storage/adapter";
import type { LocalTaxJurisdiction, LocalTaxSelection } from "@/types/plan";

export const CUSTOM_LOCAL_TAX = "custom";

type RateKey = "earned_income_rate" | "taxable_income_rate" | "state_tax_surcharge_rate";

// Server bounds, as percentages (LocalTaxSelection in the backend schemas).
const RATE_FIELDS: { key: RateKey; label: string; max: number }[] = [
  { key: "earned_income_rate", label: "Earned income rate (%)", max: 10 },
  { key: "taxable_income_rate", label: "State taxable income rate (%)", max: 10 },
  { key: "state_tax_surcharge_rate", label: "State tax surcharge (%)", max: 100 },
];

/** Editable form of a selection: "" jurisdiction is none; rates are percent text. */
export type LocalTaxDraft = { jurisdiction: string } & Record<RateKey, string>;

export function localTaxDraft(selection?: LocalTaxSelection | null): LocalTaxDraft {
  const percent = (rate?: number | null) =>
    rate == null ? "" : String(Number((rate * 100).toFixed(8)));
  return {
    jurisdiction: selection?.jurisdiction ?? "",
    earned_income_rate: percent(selection?.earned_income_rate),
    taxable_income_rate: percent(selection?.taxable_income_rate),
    state_tax_surcharge_rate: percent(selection?.state_tax_surcharge_rate),
  };
}

/** The wire selection for a draft, or the first entry error. Zero rates are omitted. */
export function localTaxSelection(
  draft: LocalTaxDraft,
): { selection: LocalTaxSelection | null } | { error: string } {
  if (!draft.jurisdiction) return { selection: null };
  if (draft.jurisdiction !== CUSTOM_LOCAL_TAX)
    return { selection: { jurisdiction: draft.jurisdiction } };
  const selection: LocalTaxSelection = { jurisdiction: CUSTOM_LOCAL_TAX };
  for (const field of RATE_FIELDS) {
    const text = draft[field.key].trim();
    if (!text) continue;
    const percent = Number(text);
    if (!Number.isFinite(percent) || percent < 0 || percent > field.max) {
      return { error: `${field.label.replace(" (%)", "")}: enter 0 to ${field.max}%.` };
    }
    if (percent > 0) selection[field.key] = Number((percent / 100).toFixed(10));
  }
  if (!RATE_FIELDS.some((field) => selection[field.key]))
    return { error: "Enter at least one local tax rate." };
  return { selection };
}

/**
 * A catalog locality belongs to one state, so a state change clears it, as
 * the server does; custom rates carry no state and stay.
 */
export function withoutCatalogLocality(draft: LocalTaxDraft): LocalTaxDraft {
  return draft.jurisdiction && draft.jurisdiction !== CUSTOM_LOCAL_TAX
    ? { ...draft, jurisdiction: "" }
    : draft;
}

const catalogs = new WeakMap<StorageAdapter, Promise<LocalTaxJurisdiction[]>>();

/** Every catalog locality, loaded once per adapter; null while loading or unavailable. */
export function useLocalTaxJurisdictions(adapter: StorageAdapter): LocalTaxJurisdiction[] | null {
  const [jurisdictions, setJurisdictions] = useState<LocalTaxJurisdiction[] | null>(null);
  useEffect(() => {
    let active = true;
    let request = catalogs.get(adapter);
    if (!request) {
      request = adapter.listLocalTaxJurisdictions().then((catalog) => catalog.jurisdictions);
      catalogs.set(adapter, request);
      // A failed load is retried by the next editor that opens.
      request.catch(() => {
        if (catalogs.get(adapter) === request) catalogs.delete(adapter);
      });
    }
    request.then(
      (list) => {
        if (active) setJurisdictions(list);
      },
      () => {},
    );
    return () => {
      active = false;
    };
  }, [adapter]);
  return jurisdictions;
}

/**
 * Locality picker for one residence. Renders label cells for the caller's
 * form grid: the picker, then the custom rates when "Custom rates" is chosen.
 */
export function LocalTaxFields({
  stateCode,
  value,
  jurisdictions,
  onChange,
  onRateBlur,
}: {
  stateCode: string;
  value: LocalTaxDraft;
  jurisdictions: LocalTaxJurisdiction[] | null;
  onChange: (next: LocalTaxDraft) => void;
  onRateBlur?: () => void;
}) {
  const options = (jurisdictions ?? []).filter((j) => j.state_code === stateCode);
  const saved =
    value.jurisdiction &&
    value.jurisdiction !== CUSTOM_LOCAL_TAX &&
    !options.some((j) => j.id === value.jurisdiction)
      ? value.jurisdiction
      : null;
  return (
    <>
      <label>
        Local income tax
        <select
          value={value.jurisdiction}
          onChange={(e) => onChange({ ...value, jurisdiction: e.target.value })}
        >
          <option value="">None</option>
          {options.map((j) => (
            <option key={j.id} value={j.id}>
              {j.name}
            </option>
          ))}
          {saved && <option value={saved}>{saved}</option>}
          <option value={CUSTOM_LOCAL_TAX}>Custom rates</option>
        </select>
      </label>
      {value.jurisdiction === CUSTOM_LOCAL_TAX &&
        RATE_FIELDS.map((field) => (
          <label key={field.key}>
            {field.label}
            <input
              type="number"
              inputMode="decimal"
              min={0}
              max={field.max}
              step="any"
              value={value[field.key]}
              onChange={(e) => onChange({ ...value, [field.key]: e.target.value })}
              onBlur={onRateBlur}
            />
          </label>
        ))}
    </>
  );
}
