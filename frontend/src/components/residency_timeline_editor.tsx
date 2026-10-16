import { useEffect, useState } from "react";

import {
  LocalTaxFields,
  localTaxDraft,
  localTaxSelection,
  withoutCatalogLocality,
  type LocalTaxDraft,
} from "@/components/local_tax_fields";
import { US_COUNTRY, countryName, defaultRegion } from "@/domain/intl_plan";
import { EmptyState, actionBtnStyle, deleteBtnStyle, usStates } from "@/pages/plan_setup_shared";
import type {
  LocalTaxJurisdiction,
  Milestone,
  ResidencyPeriod,
  ResidencyPeriodCreate,
  TaxRegimeCountry,
} from "@/types/plan";

type ResidencyTriggerKind = "none" | "milestone" | "year";

type ResidencyRow = {
  /** "" is the plan's own country. */
  country: string;
  region: string;
  state_code: string;
  start_milestone_id: string | null;
  end_milestone_id: string | null;
  start_year: number | null;
  end_year: number | null;
  local_tax: LocalTaxDraft;
};

function toRow(p: ResidencyPeriod): ResidencyRow {
  return {
    country: p.country ?? "",
    region: p.region ?? "",
    state_code: p.state_code ?? "",
    start_milestone_id: p.start_milestone_id,
    end_milestone_id: p.end_milestone_id,
    start_year: p.start_year,
    end_year: p.end_year,
    local_tax: localTaxDraft(p.local_tax),
  };
}

function startKind(r: ResidencyRow): ResidencyTriggerKind {
  if (r.start_milestone_id) return "milestone";
  if (r.start_year != null) return "year";
  return "none";
}

function endKind(r: ResidencyRow): ResidencyTriggerKind {
  if (r.end_milestone_id) return "milestone";
  if (r.end_year != null) return "year";
  return "none";
}

const residencyCardStyle: React.CSSProperties = {
  display: "grid",
  gap: 10,
  padding: "12px 14px",
  marginBottom: 8,
  borderRadius: 12,
  background: "var(--gray-100)",
};

const residencyRowGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 10,
  alignItems: "end",
};

const residencyTriggerGroupStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr",
  gap: 6,
};

export function ResidencyTimelineEditor({
  milestones,
  periods,
  onChange,
  jurisdictions = null,
  planCountry = US_COUNTRY,
  countries = null,
}: {
  milestones: Milestone[];
  periods: ResidencyPeriod[];
  onChange: (rows: ResidencyPeriodCreate[]) => Promise<void>;
  /** Local tax catalog; null while loading or unavailable. */
  jurisdictions?: LocalTaxJurisdiction[] | null;
  /** The plan's own tax country, used by rows that name none. */
  planCountry?: string;
  /** Tax regime registry; null while loading or unavailable. */
  countries?: TaxRegimeCountry[] | null;
}) {
  const [rows, setRows] = useState<ResidencyRow[]>(periods.map(toRow));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const serializedPeriods = JSON.stringify(periods.map(toRow));
  useEffect(() => {
    if (!dirty) setRows(JSON.parse(serializedPeriods));
  }, [serializedPeriods, dirty]);

  function commit(next: ResidencyRow[]) {
    setRows(next);
    setDirty(true);
    setSaved(false);
    setSaveError(null);
  }

  async function save() {
    if (saving) return;
    const rowCountry = (row: ResidencyRow) => row.country || planCountry;
    if (rows.some((row) => rowCountry(row) === US_COUNTRY && !row.state_code)) {
      setSaveError("Choose a state for each residency change, or remove the incomplete row.");
      return;
    }
    // The list replaces saved periods, so every row resends its locality.
    const periods: ResidencyPeriodCreate[] = [];
    for (const [rank, row] of rows.entries()) {
      if (rowCountry(row) !== US_COUNTRY) {
        // Another country's years use its own rules; a US state and locality do not apply.
        periods.push({
          state_code: null,
          country: row.country || null,
          region: row.region || null,
          start_milestone_id: row.start_milestone_id,
          end_milestone_id: row.end_milestone_id,
          start_year: row.start_year,
          end_year: row.end_year,
          rank,
          local_tax: null,
        });
        continue;
      }
      const local = localTaxSelection(row.local_tax);
      if ("error" in local) {
        setSaveError(
          rows.length > 1 ? `Residency change ${rank + 1}: ${local.error}` : local.error,
        );
        return;
      }
      periods.push({
        state_code: row.state_code,
        // Sent only when set, so US-only timelines keep their payload.
        ...(row.country ? { country: row.country, region: null } : {}),
        start_milestone_id: row.start_milestone_id,
        end_milestone_id: row.end_milestone_id,
        start_year: row.start_year,
        end_year: row.end_year,
        rank,
        local_tax: local.selection,
      });
    }
    setSaving(true);
    setSaveError(null);
    try {
      await onChange(periods);
      setDirty(false);
      setSaved(true);
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error.message
          : "Could not save residency changes. Retry your save.",
      );
    } finally {
      setSaving(false);
    }
  }

  function addRow() {
    commit([
      ...rows,
      {
        country: "",
        region: "",
        state_code: "",
        start_milestone_id: null,
        end_milestone_id: null,
        start_year: null,
        end_year: null,
        local_tax: localTaxDraft(null),
      },
    ]);
  }

  function updateRow(index: number, patch: Partial<ResidencyRow>) {
    commit(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function removeRow(index: number) {
    commit(rows.filter((_, i) => i !== index));
  }

  function setStartKind(index: number, kind: ResidencyTriggerKind) {
    if (kind === "none") {
      updateRow(index, { start_milestone_id: null, start_year: null });
    } else if (kind === "milestone") {
      updateRow(index, {
        start_milestone_id: milestones[0]?.id ?? null,
        start_year: null,
      });
    } else {
      updateRow(index, {
        start_milestone_id: null,
        start_year: new Date().getFullYear(),
      });
    }
  }

  function setEndKind(index: number, kind: ResidencyTriggerKind) {
    if (kind === "none") {
      updateRow(index, { end_milestone_id: null, end_year: null });
    } else if (kind === "milestone") {
      updateRow(index, {
        end_milestone_id: milestones[0]?.id ?? null,
        end_year: null,
      });
    } else {
      updateRow(index, {
        end_milestone_id: null,
        end_year: new Date().getFullYear() + 1,
      });
    }
  }

  return (
    <fieldset
      disabled={saving}
      data-unsaved-changes={dirty || undefined}
      data-save-pending={saving || undefined}
      data-testid="residency-timeline-editor"
      style={{ display: "grid", gap: 6, border: 0, padding: 0, margin: 0, minWidth: 0 }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "grid", gap: 2 }}>
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Residency timeline</span>
          <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            {planCountry === US_COUNTRY
              ? "State above is the starting residency."
              : `${countryName(planCountry, countries)} above is the starting residency.`}{" "}
            Add changes to model moves tied to milestones or specific years.
          </span>
        </div>
        <button
          type="button"
          className="plan-add-btn"
          style={actionBtnStyle}
          onClick={addRow}
          data-testid="residency-add"
        >
          + Add residency change
        </button>
      </div>

      {rows.length === 0 && <EmptyState message="No residency changes." />}

      {rows.map((row, index) => {
        const sKind = startKind(row);
        const eKind = endKind(row);
        const country = row.country || planCountry;
        const regions = countries?.find((c) => c.code === country)?.regions ?? [];
        const countryChoices = [
          US_COUNTRY,
          ...(countries ?? []).map((c) => c.code).filter((code) => code !== US_COUNTRY),
        ];
        if (row.country && !countryChoices.includes(row.country)) countryChoices.push(row.country);
        return (
          <div key={index} style={residencyCardStyle}>
            <div style={residencyRowGridStyle}>
              <label>
                Country
                <select
                  value={row.country}
                  onChange={(e) => {
                    const next = e.target.value;
                    updateRow(index, {
                      country: next,
                      region:
                        defaultRegion(countries?.find((c) => c.code === (next || planCountry))) ??
                        "",
                    });
                  }}
                >
                  <option value="">Same as plan ({countryName(planCountry, countries)})</option>
                  {countryChoices.map((code) => (
                    <option key={code} value={code}>
                      {countryName(code, countries)}
                    </option>
                  ))}
                </select>
              </label>
              {country !== US_COUNTRY && regions.length > 0 && row.country && (
                <label>
                  Region
                  <select
                    value={row.region}
                    onChange={(e) => updateRow(index, { region: e.target.value })}
                  >
                    {!row.region && <option value="">Choose a region</option>}
                    {regions.map((r) => (
                      <option key={r.code} value={r.code}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {country === US_COUNTRY && (
                <label>
                  State
                  <select
                    value={row.state_code}
                    onChange={(e) =>
                      updateRow(index, {
                        state_code: e.target.value,
                        local_tax: withoutCatalogLocality(row.local_tax),
                      })
                    }
                  >
                    <option value="">— Select —</option>
                    {usStates
                      .filter((s) => s.value !== "")
                      .map((state) => (
                        <option key={state.value} value={state.value}>
                          {state.label}
                        </option>
                      ))}
                  </select>
                </label>
              )}

              <div style={residencyTriggerGroupStyle}>
                <label>
                  Start
                  <select
                    value={sKind}
                    onChange={(e) => setStartKind(index, e.target.value as ResidencyTriggerKind)}
                  >
                    <option value="none">From plan start</option>
                    <option value="milestone" disabled={milestones.length === 0}>
                      At milestone
                    </option>
                    <option value="year">In year</option>
                  </select>
                </label>
                {sKind === "milestone" && (
                  <select
                    value={row.start_milestone_id ?? ""}
                    onChange={(e) =>
                      updateRow(index, {
                        start_milestone_id: e.target.value || null,
                      })
                    }
                  >
                    {milestones.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                )}
                {sKind === "year" && (
                  <input
                    type="number"
                    min={1900}
                    max={2200}
                    value={row.start_year ?? ""}
                    onChange={(e) =>
                      updateRow(index, {
                        start_year: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                  />
                )}
              </div>

              <div style={residencyTriggerGroupStyle}>
                <label>
                  End
                  <select
                    value={eKind}
                    onChange={(e) => setEndKind(index, e.target.value as ResidencyTriggerKind)}
                  >
                    <option value="none">Indefinite</option>
                    <option value="milestone" disabled={milestones.length === 0}>
                      At milestone
                    </option>
                    <option value="year">In year</option>
                  </select>
                </label>
                {eKind === "milestone" && (
                  <select
                    value={row.end_milestone_id ?? ""}
                    onChange={(e) =>
                      updateRow(index, {
                        end_milestone_id: e.target.value || null,
                      })
                    }
                  >
                    {milestones.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                )}
                {eKind === "year" && (
                  <input
                    type="number"
                    min={1900}
                    max={2200}
                    value={row.end_year ?? ""}
                    onChange={(e) =>
                      updateRow(index, {
                        end_year: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                  />
                )}
              </div>

              <button
                type="button"
                className="plan-delete-btn"
                style={deleteBtnStyle}
                onClick={() => removeRow(index)}
                aria-label="Remove residency change"
              >
                Remove
              </button>
            </div>
            {country === US_COUNTRY && (row.state_code || row.local_tax.jurisdiction) && (
              <div style={residencyRowGridStyle}>
                <LocalTaxFields
                  stateCode={row.state_code}
                  value={row.local_tax}
                  jurisdictions={jurisdictions}
                  onChange={(local_tax) => updateRow(index, { local_tax })}
                />
              </div>
            )}
          </div>
        );
      })}
      {saveError && <p role="alert">{saveError}</p>}
      {dirty && <p role="status">Unsaved residency changes. Save this timeline before closing.</p>}
      {saved && <p role="status">Residency changes saved.</p>}
      <button type="button" className="btn-primary" disabled={!dirty || saving} onClick={save}>
        {saving ? "Saving…" : "Save residency changes"}
      </button>
    </fieldset>
  );
}
