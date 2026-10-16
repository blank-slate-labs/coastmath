import { useEffect, useState } from "react";

import type { IntlRegimeDocument } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";
import {
  draftFromDocument,
  documentFromDraft,
  type CapitalGainsMode,
  type CustomRegimeDraft,
  type DraftErrors,
  type IncomeMode,
  type TradeSide,
} from "./custom_regime_document";

const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
  alignItems: "end",
};
const groupStyle: React.CSSProperties = {
  border: "1px solid var(--gray-200)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  display: "grid",
  gap: 10,
};
const errorStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  color: "var(--color-danger)",
};

function FieldError({ message }: { message?: string }) {
  return message ? (
    <span role="alert" style={errorStyle}>
      {message}
    </span>
  ) : null;
}

/**
 * Tax rules for a country without a built-in pack ("Other"): national
 * brackets and allowance, capital gains, dividends and interest, and optional
 * wealth and transaction taxes. Saved as `intl_settings.custom_regime`; the
 * server's validation messages are shown as they come back.
 */
export default function CustomRegimeEditor({
  document,
  baseYear,
  currency,
  onSave,
}: {
  document: IntlRegimeDocument | null | undefined;
  baseYear: number;
  currency: string;
  onSave: (document: IntlRegimeDocument) => Promise<void>;
}) {
  const serialized = JSON.stringify(document ?? null);
  const [draft, setDraft] = useState<CustomRegimeDraft>(() => draftFromDocument(document));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) setDraft(draftFromDocument(JSON.parse(serialized)));
  }, [serialized, dirty]);

  function change(patch: Partial<CustomRegimeDraft>) {
    setDraft((d) => ({ ...d, ...patch }));
    setDirty(true);
    setSaved(false);
    setSaveError(null);
  }

  async function save() {
    if (saving) return;
    const result = documentFromDraft(draft, { baseYear, currency });
    if ("errors" in result) {
      setErrors(result.errors);
      setSaveError("Fix the highlighted tax rules, then save.");
      return;
    }
    setErrors({});
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(result.document);
      setDirty(false);
      setSaved(true);
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error.message
          : "Could not save the tax rules. Your changes are kept; retry your save.",
      );
    } finally {
      setSaving(false);
    }
  }

  const brackets = draft.brackets;
  const setBracket = (index: number, patch: Partial<{ from: string; rate: string }>) =>
    change({ brackets: brackets.map((b, i) => (i === index ? { ...b, ...patch } : b)) });

  return (
    <fieldset
      disabled={saving}
      data-testid="custom-regime-editor"
      style={{
        display: "grid",
        gap: 10,
        border: 0,
        padding: 0,
        margin: 0,
        minWidth: 0,
        gridColumn: "1 / -1",
      }}
    >
      <div style={{ display: "grid", gap: 2 }}>
        <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Custom tax rules</span>
        <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
          For a country without built-in rules. Amounts are in {currency} for {baseYear}
          {draft.indexed ? " and grow with the plan's inflation" : ""}.
        </span>
      </div>

      <div style={gridStyle}>
        <label>
          Taxed as
          <select
            value={draft.filingUnit}
            onChange={(e) =>
              change({ filingUnit: e.target.value as CustomRegimeDraft["filingUnit"] })
            }
          >
            <option value="individual">Each person separately</option>
            <option value="joint">The couple together</option>
          </select>
        </label>
        <label>
          {moneyLabel("Tax-free allowance ($)")}
          <MoneyInput
            min={0}
            step="any"
            value={draft.allowance}
            aria-invalid={errors.allowance ? true : undefined}
            onValueChange={(value) => change({ allowance: value })}
          />
          <FieldError message={errors.allowance} />
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={draft.indexed}
            onChange={(e) => change({ indexed: e.target.checked })}
          />
          Index thresholds with inflation
        </label>
      </div>

      <fieldset style={groupStyle}>
        <legend>National income tax brackets</legend>
        {brackets.map((bracket, index) => (
          <div key={index} style={gridStyle} role="group" aria-label={`Bracket ${index + 1}`}>
            <label>
              {moneyLabel("Income from ($)")}
              <MoneyInput
                min={0}
                step="any"
                value={bracket.from}
                readOnly={index === 0}
                aria-invalid={errors[`bracket_${index}_from`] ? true : undefined}
                onValueChange={(value) => setBracket(index, { from: value })}
              />
              <FieldError message={errors[`bracket_${index}_from`]} />
            </label>
            <label>
              Rate (%)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={bracket.rate}
                aria-invalid={errors[`bracket_${index}_rate`] ? true : undefined}
                onChange={(e) => setBracket(index, { rate: e.target.value })}
              />
              <FieldError message={errors[`bracket_${index}_rate`]} />
            </label>
            {index > 0 && (
              <button
                type="button"
                className="plan-delete-btn"
                aria-label={`Remove bracket ${index + 1}`}
                onClick={() => change({ brackets: brackets.filter((_, i) => i !== index) })}
              >
                Remove
              </button>
            )}
          </div>
        ))}
        <FieldError message={errors.brackets} />
        <button
          type="button"
          className="plan-add-btn"
          style={{ justifySelf: "start" }}
          onClick={() => change({ brackets: [...brackets, { from: "", rate: "" }] })}
        >
          + Add bracket
        </button>
      </fieldset>

      <fieldset style={groupStyle}>
        <legend>Investment income</legend>
        <div style={gridStyle}>
          <label>
            Capital gains
            <select
              value={draft.capitalGains.mode}
              onChange={(e) =>
                change({
                  capitalGains: { ...draft.capitalGains, mode: e.target.value as CapitalGainsMode },
                })
              }
            >
              <option value="ordinary_inclusion">Part of income, at the bracket rates</option>
              <option value="flat">Flat rate</option>
              <option value="exempt">Not taxed</option>
            </select>
          </label>
          {draft.capitalGains.mode === "ordinary_inclusion" && (
            <label>
              Share of gains taxed (%)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={draft.capitalGains.inclusion}
                aria-invalid={errors.cg_inclusion ? true : undefined}
                onChange={(e) =>
                  change({ capitalGains: { ...draft.capitalGains, inclusion: e.target.value } })
                }
              />
              <FieldError message={errors.cg_inclusion} />
            </label>
          )}
          {draft.capitalGains.mode === "flat" && (
            <label>
              Capital gains rate (%)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={draft.capitalGains.rate}
                aria-invalid={errors.cg_rate ? true : undefined}
                onChange={(e) =>
                  change({ capitalGains: { ...draft.capitalGains, rate: e.target.value } })
                }
              />
              <FieldError message={errors.cg_rate} />
            </label>
          )}
          <label>
            Dividends
            <select
              value={draft.dividends.mode}
              onChange={(e) =>
                change({ dividends: { ...draft.dividends, mode: e.target.value as IncomeMode } })
              }
            >
              <option value="ordinary">Ordinary income</option>
              <option value="capital_gains_rates">Like capital gains</option>
              <option value="flat">Flat rate</option>
              <option value="exempt">Not taxed</option>
            </select>
          </label>
          {draft.dividends.mode === "flat" && (
            <label>
              Dividend rate (%)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={draft.dividends.rate}
                aria-invalid={errors.dividend_rate ? true : undefined}
                onChange={(e) =>
                  change({ dividends: { ...draft.dividends, rate: e.target.value } })
                }
              />
              <FieldError message={errors.dividend_rate} />
            </label>
          )}
          <label>
            Interest
            <select
              value={draft.interest.mode}
              onChange={(e) =>
                change({
                  interest: {
                    ...draft.interest,
                    mode: e.target.value as CustomRegimeDraft["interest"]["mode"],
                  },
                })
              }
            >
              <option value="ordinary">Ordinary income</option>
              <option value="flat">Flat rate</option>
              <option value="exempt">Not taxed</option>
            </select>
          </label>
          {draft.interest.mode === "flat" && (
            <label>
              Interest rate (%)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={draft.interest.rate}
                aria-invalid={errors.interest_rate ? true : undefined}
                onChange={(e) => change({ interest: { ...draft.interest, rate: e.target.value } })}
              />
              <FieldError message={errors.interest_rate} />
            </label>
          )}
        </div>
      </fieldset>

      <fieldset style={groupStyle}>
        <legend>Wealth tax</legend>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={draft.wealth.enabled}
            onChange={(e) => change({ wealth: { ...draft.wealth, enabled: e.target.checked } })}
          />
          Tax net worth each year
        </label>
        {draft.wealth.enabled && (
          <div style={gridStyle}>
            <label>
              Based on
              <select
                value={draft.wealth.base}
                onChange={(e) =>
                  change({
                    wealth: {
                      ...draft.wealth,
                      base: e.target.value as CustomRegimeDraft["wealth"]["base"],
                    },
                  })
                }
              >
                <option value="net_worth">Net worth</option>
                <option value="liquid_net_worth">Net worth without property</option>
              </select>
            </label>
            <label>
              Applied to
              <select
                value={draft.wealth.per}
                onChange={(e) =>
                  change({
                    wealth: {
                      ...draft.wealth,
                      per: e.target.value as CustomRegimeDraft["wealth"]["per"],
                    },
                  })
                }
              >
                <option value="person">Each person</option>
                <option value="household">The household</option>
              </select>
            </label>
            <label>
              {moneyLabel("Tax-free amount ($)")}
              <MoneyInput
                min={0}
                step="any"
                value={draft.wealth.allowance}
                aria-invalid={errors.wealth_allowance ? true : undefined}
                onValueChange={(value) => change({ wealth: { ...draft.wealth, allowance: value } })}
              />
              <FieldError message={errors.wealth_allowance} />
            </label>
            <label>
              Wealth tax rate (%)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={draft.wealth.rate}
                aria-invalid={errors.wealth_rate ? true : undefined}
                onChange={(e) => change({ wealth: { ...draft.wealth, rate: e.target.value } })}
              />
              <FieldError message={errors.wealth_rate} />
            </label>
          </div>
        )}
      </fieldset>

      <fieldset style={groupStyle}>
        <legend>Transaction tax</legend>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={draft.transaction.enabled}
            onChange={(e) =>
              change({ transaction: { ...draft.transaction, enabled: e.target.checked } })
            }
          />
          Tax trades in taxable accounts
        </label>
        {draft.transaction.enabled && (
          <div style={gridStyle}>
            <label>
              Transaction tax rate (%)
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={draft.transaction.rate}
                aria-invalid={errors.transaction_rate ? true : undefined}
                onChange={(e) =>
                  change({ transaction: { ...draft.transaction, rate: e.target.value } })
                }
              />
              <FieldError message={errors.transaction_rate} />
            </label>
            <label>
              Charged on
              <select
                value={draft.transaction.side}
                onChange={(e) =>
                  change({
                    transaction: { ...draft.transaction, side: e.target.value as TradeSide },
                  })
                }
              >
                <option value="buy">Purchases</option>
                <option value="sell">Sales</option>
                <option value="both">Purchases and sales</option>
              </select>
            </label>
          </div>
        )}
      </fieldset>

      {saveError && <p role="alert">{saveError}</p>}
      {dirty && <p role="status">Unsaved tax rule changes.</p>}
      {saved && <p role="status">Tax rules saved.</p>}
      <button
        type="button"
        className="btn-primary"
        disabled={!dirty || saving}
        onClick={save}
        style={{ justifySelf: "start" }}
      >
        {saving ? "Saving…" : "Save tax rules"}
      </button>
    </fieldset>
  );
}
