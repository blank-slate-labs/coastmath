import { useEffect, useState } from "react";

import type { IntlBenefit, IntlPerson, Milestone, TaxRegimeBenefitRule } from "@/types/plan";
import { paramDraft, paramFields, paramValues } from "./param_schema";

type StartKind = "age" | "milestone";

interface BenefitRow {
  rule: string;
  owner: IntlPerson;
  startKind: StartKind;
  startAge: string;
  startMilestoneId: string;
  params: Record<string, string | boolean>;
}

function toRow(benefit: IntlBenefit, rules: readonly TaxRegimeBenefitRule[]): BenefitRow {
  const fields = paramFields(rules.find((r) => r.id === benefit.rule)?.params_schema);
  const params: Record<string, string | boolean> = {};
  for (const field of fields) params[field.key] = paramDraft(field, benefit.params?.[field.key]);
  return {
    rule: benefit.rule,
    owner: benefit.owner,
    startKind: benefit.start_milestone_id ? "milestone" : "age",
    startAge: benefit.start_age != null ? String(benefit.start_age) : "",
    startMilestoneId: benefit.start_milestone_id ?? "",
    params,
  };
}

function newRow(rule: TaxRegimeBenefitRule): BenefitRow {
  const params: Record<string, string | boolean> = {};
  for (const field of paramFields(rule.params_schema))
    params[field.key] = paramDraft(field, undefined);
  return {
    rule: rule.id,
    owner: "self",
    startKind: "age",
    startAge: "",
    startMilestoneId: "",
    params,
  };
}

type RowErrors = { start?: string; params?: Record<string, string> };

/** The saved list for the draft rows, or each row's errors. */
export function benefitsFromRows(
  rows: BenefitRow[],
  rules: readonly TaxRegimeBenefitRule[],
): { benefits: IntlBenefit[] } | { errors: RowErrors[] } {
  const benefits: IntlBenefit[] = [];
  const errors: RowErrors[] = rows.map(() => ({}));
  let failed = false;
  rows.forEach((row, index) => {
    const rule = rules.find((r) => r.id === row.rule);
    // A rule the registry no longer lists keeps its saved params untouched.
    const values = rule
      ? paramValues(paramFields(rule.params_schema), row.params)
      : { params: row.params as Record<string, unknown> };
    let startAge: number | null = null;
    if (row.startKind === "age") {
      const age = Number(row.startAge);
      if (row.startAge.trim() === "" || !Number.isInteger(age) || age < 0 || age > 120) {
        errors[index].start = "Enter a whole start age from 0 to 120.";
        failed = true;
      } else startAge = age;
    } else if (!row.startMilestoneId) {
      errors[index].start = "Choose the milestone the benefit starts at.";
      failed = true;
    }
    if ("errors" in values) {
      errors[index].params = values.errors;
      failed = true;
      return;
    }
    benefits.push({
      rule: row.rule,
      owner: row.owner,
      start_age: row.startKind === "age" ? startAge : null,
      start_milestone_id: row.startKind === "milestone" ? row.startMilestoneId || null : null,
      params: values.params,
    });
  });
  return failed ? { errors } : { benefits };
}

const cardStyle: React.CSSProperties = {
  display: "grid",
  gap: 10,
  padding: "12px 14px",
  marginBottom: 8,
  borderRadius: 12,
  background: "var(--gray-100)",
};
const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
  alignItems: "end",
};
const errorStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  color: "var(--color-danger)",
};

/**
 * Government benefits paid by a country's registered rules, saved in
 * `intl_settings.benefits`. Each rule's inputs come from its
 * params schema in the registry; the server validates them again.
 */
export default function IntlBenefitsEditor({
  benefits,
  rules,
  milestones,
  hasPartner,
  onSave,
}: {
  benefits: IntlBenefit[];
  rules: readonly TaxRegimeBenefitRule[];
  milestones: Pick<Milestone, "id" | "name">[];
  hasPartner: boolean;
  onSave: (benefits: IntlBenefit[]) => Promise<void>;
}) {
  const serialized = JSON.stringify(benefits);
  const [rows, setRows] = useState<BenefitRow[]>(() => benefits.map((b) => toRow(b, rules)));
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [errors, setErrors] = useState<RowErrors[]>([]);
  const [addRule, setAddRule] = useState(rules[0]?.id ?? "");
  const ruleIds = rules.map((r) => r.id).join("|");

  useEffect(() => {
    if (!dirty) setRows((JSON.parse(serialized) as IntlBenefit[]).map((b) => toRow(b, rules)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rules are compared by id (ruleIds); their schemas come from the same registry load
  }, [serialized, dirty, ruleIds]);
  useEffect(() => {
    if (!rules.some((r) => r.id === addRule)) setAddRule(rules[0]?.id ?? "");
  }, [rules, addRule]);

  function commit(next: BenefitRow[]) {
    setRows(next);
    setDirty(true);
    setSaved(false);
    setSaveError(null);
  }
  const update = (index: number, patch: Partial<BenefitRow>) =>
    commit(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));

  async function save() {
    if (saving) return;
    const result = benefitsFromRows(rows, rules);
    if ("errors" in result) {
      setErrors(result.errors);
      setSaveError("Fix the highlighted benefit inputs, then save.");
      return;
    }
    setErrors([]);
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(result.benefits);
      setDirty(false);
      setSaved(true);
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error.message
          : "Could not save benefits. Your changes are kept; retry your save.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <fieldset
      disabled={saving}
      data-testid="intl-benefits-editor"
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
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "end",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "grid", gap: 2 }}>
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Government benefits</span>
          <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            Paid each year from the start age or milestone, taxed by the country you live in. Other
            state pensions are income streams.
          </span>
        </div>
        {rules.length > 0 && (
          <div style={{ display: "flex", gap: 8, alignItems: "end" }}>
            <label>
              Benefit
              <select value={addRule} onChange={(e) => setAddRule(e.target.value)}>
                {rules.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="plan-add-btn"
              onClick={() => {
                const rule = rules.find((r) => r.id === addRule);
                if (rule) commit([...rows, newRow(rule)]);
              }}
            >
              + Add benefit
            </button>
          </div>
        )}
      </div>

      {rows.length === 0 && (
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-tertiary)" }}>No benefits.</p>
      )}

      {rows.map((row, index) => {
        const rule = rules.find((r) => r.id === row.rule);
        const fields = paramFields(rule?.params_schema);
        const rowErrors = errors[index] ?? {};
        return (
          <div
            key={index}
            style={cardStyle}
            aria-label={`Benefit ${index + 1}: ${rule?.label ?? row.rule}`}
            role="group"
          >
            <div style={gridStyle}>
              <strong style={{ alignSelf: "center" }}>{rule?.label ?? row.rule}</strong>
              <label>
                Paid to
                <select
                  value={row.owner}
                  onChange={(e) => update(index, { owner: e.target.value as IntlPerson })}
                >
                  <option value="self">Primary person</option>
                  {(hasPartner || row.owner === "spouse") && (
                    <option value="spouse">Partner</option>
                  )}
                </select>
              </label>
              <label>
                Starts
                <select
                  value={row.startKind}
                  onChange={(e) => update(index, { startKind: e.target.value as StartKind })}
                >
                  <option value="age">At age</option>
                  <option value="milestone" disabled={milestones.length === 0}>
                    At milestone
                  </option>
                </select>
              </label>
              {row.startKind === "age" ? (
                <label>
                  Start age
                  <input
                    type="number"
                    min={0}
                    max={120}
                    step={1}
                    value={row.startAge}
                    aria-invalid={rowErrors.start ? true : undefined}
                    onChange={(e) => update(index, { startAge: e.target.value })}
                  />
                </label>
              ) : (
                <label>
                  Start milestone
                  <select
                    value={row.startMilestoneId}
                    aria-invalid={rowErrors.start ? true : undefined}
                    onChange={(e) => update(index, { startMilestoneId: e.target.value })}
                  >
                    <option value="">Choose a milestone</option>
                    {milestones.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                type="button"
                className="plan-delete-btn"
                onClick={() => commit(rows.filter((_, i) => i !== index))}
                aria-label={`Remove ${rule?.label ?? row.rule}`}
              >
                Remove
              </button>
            </div>
            {rowErrors.start && (
              <span role="alert" style={errorStyle}>
                {rowErrors.start}
              </span>
            )}
            {!rule && (
              <p style={{ margin: 0, fontSize: 12 }}>
                This benefit&apos;s country is no longer offered; its saved inputs are kept.
              </p>
            )}
            {fields.length > 0 && (
              <div style={gridStyle}>
                {fields.map((field) => {
                  const error = rowErrors.params?.[field.key];
                  const value = row.params[field.key];
                  const setValue = (next: string | boolean) =>
                    update(index, { params: { ...row.params, [field.key]: next } });
                  if (field.kind === "boolean") {
                    return (
                      <label
                        key={field.key}
                        style={{ display: "flex", gap: 8, alignItems: "center" }}
                        title={field.description ?? undefined}
                      >
                        <input
                          type="checkbox"
                          checked={value === true}
                          onChange={(e) => setValue(e.target.checked)}
                        />
                        {field.label}
                      </label>
                    );
                  }
                  return (
                    <label key={field.key} title={field.description ?? undefined}>
                      {field.label}
                      {field.required ? "" : " (optional)"}
                      {field.kind === "enum" ? (
                        <select
                          value={typeof value === "string" ? value : ""}
                          aria-invalid={error ? true : undefined}
                          onChange={(e) => setValue(e.target.value)}
                        >
                          <option value="">{field.required ? "Choose…" : "Default"}</option>
                          {field.options.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={field.kind === "string" ? "text" : "number"}
                          step={field.kind === "integer" ? 1 : "any"}
                          min={field.minimum ?? undefined}
                          max={field.maximum ?? undefined}
                          value={typeof value === "string" ? value : ""}
                          aria-invalid={error ? true : undefined}
                          onChange={(e) => setValue(e.target.value)}
                        />
                      )}
                      {field.description && (
                        <span style={{ display: "block", fontSize: 12 }}>{field.description}</span>
                      )}
                      {error && (
                        <span role="alert" style={errorStyle}>
                          {error}
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
      {saveError && <p role="alert">{saveError}</p>}
      {dirty && <p role="status">Unsaved benefit changes.</p>}
      {saved && <p role="status">Benefits saved.</p>}
      <button type="button" className="btn-primary" disabled={!dirty || saving} onClick={save}>
        {saving ? "Saving…" : "Save benefits"}
      </button>
    </fieldset>
  );
}
