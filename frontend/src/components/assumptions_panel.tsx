import { useCallback, useId, useRef, useState } from "react";
import AssumptionCurveEditor from "./assumption_curve_editor";
import AssetLocationForm from "./asset_location_form";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { ScenarioBadge } from "@/components/scenario/scenario_badge";
import type { AssumptionCurve, CurveType, PlanData } from "@/types/plan";

// Defaults match AssumptionData and the simulator's allocation fallback.
// Unset wage growth follows each year's inflation in the engine.
const assumptions: {
  type: CurveType;
  label: string;
  rate: number;
  min: number;
  max: number;
  help?: string;
  followsInflation?: boolean;
}[] = [
  { type: "inflation", label: "Inflation", rate: 0.03, min: -0.99, max: 1 },
  {
    type: "wage_growth",
    label: "Wage growth",
    rate: 0.03,
    min: -0.99,
    max: 1,
    help: "Applies to earned income without its own growth rate.",
    followsInflation: true,
  },
  {
    type: "market_return",
    label: "Stock price growth",
    rate: 0.07,
    min: -0.99,
    max: 1,
    help: "Excludes dividends.",
  },
  { type: "dividend_yield", label: "Stock dividend yield", rate: 0, min: 0, max: 1 },
  { type: "cash_yield", label: "Cash yield", rate: 0, min: 0, max: 1 },
  { type: "bond_return", label: "Bond return", rate: 0.04, min: -0.99, max: 1 },
  { type: "bond_allocation", label: "Bond allocation", rate: 0, min: 0, max: 1 },
];

/**
 * A row's unsaved edit, which the sheet's one Save button writes. `check` runs on every
 * edited row first and opens a row whose draft is invalid; `save` resolves to success.
 */
export interface PendingSave {
  check: () => boolean;
  save: () => Promise<boolean>;
}
type PendingKey = CurveType | "asset_location";

function AssumptionRow({
  plan,
  definition,
  existing,
  onPending,
}: {
  plan: PlanData;
  definition: (typeof assumptions)[number];
  existing?: AssumptionCurve;
  onPending: (key: PendingKey, pending: PendingSave | null) => void;
}) {
  const { adapter } = useStorage();
  const [mode, setMode] = useState(existing?.mode ?? "fixed");
  // An unset wage growth follows inflation; choosing a rate is explicit, never the editor's default.
  const [follows, setFollows] = useState(!!definition.followsInflation && !existing);
  const [rate, setRate] = useState<number | null>(existing?.fixed_rate ?? definition.rate);
  const firstAge =
    (plan.plan_type === "FIXED_DATE" && plan.start_date
      ? Number(plan.start_date.slice(0, 4))
      : new Date().getFullYear()) - plan.birth_year;
  const lastAge = Math.max(firstAge + 1, plan.life_expectancy);
  const [points, setPoints] = useState(
    existing?.control_points.length
      ? existing.control_points
      : [
          { x: firstAge, y: rate ?? definition.rate },
          { x: lastAge, y: rate ?? definition.rate },
        ],
  );
  const [error, setError] = useState("");
  // The input the error is about: the fixed rate, or a curve point's age or percent.
  const [invalid, setInvalid] = useState<string | null>(null);
  const errorId = useId();

  // The latest draft, read by the save the sheet runs later.
  const draft = { mode, follows, rate, points };
  const latest = useRef(draft);
  latest.current = draft;

  const row = useRef<HTMLDetailsElement>(null);
  /** The first invalid input and why, or null. Points are numbered as listed. */
  const problem = useCallback((): { field: string; message: string } | null => {
    const { mode, follows, rate, points } = latest.current;
    if (follows) return null;
    const validRate = (v: number | null): v is number =>
      v !== null && Number.isFinite(v) && v >= definition.min && v <= definition.max;
    const range = `${definition.min * 100}% to ${definition.max * 100}%`;
    if (mode === "fixed")
      return validRate(rate) ? null : { field: "rate", message: `Enter a rate from ${range}.` };
    for (const [i, p] of points.entries()) {
      if (!Number.isInteger(p.x) || p.x < 0 || p.x > 130)
        return { field: `age-${i}`, message: `Age ${i + 1}: enter a whole number from 0 to 130.` };
      if (points.slice(0, i).some((q) => q.x === p.x))
        return { field: `age-${i}`, message: `Age ${i + 1}: age ${p.x} is already listed.` };
      if (!validRate(p.y))
        return { field: `percent-${i}`, message: `Percent ${i + 1}: enter ${range}.` };
    }
    return points.length < 2
      ? { field: "points", message: "A curve needs at least two ages." }
      : null;
  }, [definition]);

  /** Opens this row on an invalid draft and focuses the bad input, so a collapsed row never hides why nothing saved. */
  const check = useCallback(() => {
    const found = problem();
    setError(found?.message ?? "");
    setInvalid(found?.field ?? null);
    if (found && row.current) {
      row.current.open = true;
      (
        row.current.querySelector<HTMLElement>(`[data-field="${found.field}"]`) ??
        row.current.querySelector<HTMLElement>("input, select, button.seg-option")
      )?.focus();
    }
    return !found;
  }, [problem]);

  const save = useCallback(async () => {
    const { mode, follows, rate, points } = latest.current;
    try {
      if (follows) {
        if (existing) await adapter.deleteAssumption(plan.id, existing.id);
        return true;
      }
      if (!check()) return false;
      const sorted = [...points].sort((a, b) => a.x - b.x);
      const data = { curve_type: definition.type, mode, fixed_rate: rate, control_points: sorted };
      if (existing) await adapter.updateAssumption(plan.id, existing.id, data);
      else await adapter.createAssumption(plan.id, data);
      return true;
    } catch {
      setError("Could not save this assumption. Your edits are still here; try again.");
      setInvalid(null);
      return false;
    }
  }, [adapter, plan.id, existing, definition, check]);

  function edited(change: () => void) {
    change();
    setError("");
    setInvalid(null);
    onPending(definition.type, { check, save });
  }

  const summary =
    existing?.mode === "curve"
      ? "Age-based curve"
      : !existing && definition.followsInflation
        ? "Follows inflation"
        : `${((existing?.fixed_rate ?? definition.rate) * 100).toFixed(1)}%`;
  return (
    <details ref={row} style={{ borderTop: "1px solid var(--surface-border)", padding: "12px 0" }}>
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>
        {definition.label} · {summary}
        {!existing && !definition.followsInflation && " (default)"}
        <ScenarioBadge rowId={existing?.id} />
      </summary>
      {definition.help && (
        <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>{definition.help}</p>
      )}
      {definition.followsInflation && (
        <div
          className="seg-control"
          role="group"
          aria-label={`${definition.label} source`}
          style={{ marginBottom: 12 }}
        >
          <button
            type="button"
            className={`seg-option${follows ? " active" : ""}`}
            aria-pressed={follows}
            onClick={() => edited(() => setFollows(true))}
          >
            Follows inflation
          </button>
          <button
            type="button"
            className={`seg-option${follows ? "" : " active"}`}
            aria-pressed={!follows}
            onClick={() => edited(() => setFollows(false))}
          >
            Own rate
          </button>
        </div>
      )}
      {!follows && (
        <>
          <AssumptionCurveEditor
            curveType={definition.type}
            label={definition.label}
            mode={mode}
            fixedRate={rate}
            controlPoints={points}
            invalid={invalid === "rate" ? errorId : undefined}
            minAge={Math.min(firstAge, ...points.map((p) => p.x))}
            maxAge={Math.max(lastAge, ...points.map((p) => p.x))}
            minValue={
              definition.type === "bond_allocation" ? 0 : Math.min(0, ...points.map((p) => p.y))
            }
            maxValue={
              definition.type === "bond_allocation" ? 1 : Math.max(0.15, ...points.map((p) => p.y))
            }
            onChange={(update) =>
              edited(() => {
                if (update.mode) setMode(update.mode);
                if ("fixedRate" in update) setRate(update.fixedRate ?? null);
                if (update.controlPoints) setPoints(update.controlPoints);
              })
            }
          />
          {mode === "curve" && (
            <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
              <p style={{ fontSize: 12 }}>Linear interpolation; constant beyond endpoints.</p>
              {points.map((point, i) => (
                <div key={i} style={{ display: "flex", gap: 8, alignItems: "end" }}>
                  <label>
                    Age
                    <input
                      aria-label={`${definition.label} age ${i + 1}`}
                      data-field={`age-${i}`}
                      aria-invalid={invalid === `age-${i}` || undefined}
                      aria-describedby={invalid === `age-${i}` ? errorId : undefined}
                      type="number"
                      value={point.x}
                      onChange={(e) =>
                        edited(() =>
                          setPoints(
                            points.map((p, j) =>
                              j === i ? { ...p, x: Number(e.target.value) } : p,
                            ),
                          ),
                        )
                      }
                    />
                  </label>
                  <label>
                    Percent
                    <input
                      aria-label={`${definition.label} percent ${i + 1}`}
                      data-field={`percent-${i}`}
                      aria-invalid={invalid === `percent-${i}` || undefined}
                      aria-describedby={invalid === `percent-${i}` ? errorId : undefined}
                      type="number"
                      step="0.1"
                      value={Number((point.y * 100).toFixed(4))}
                      onChange={(e) =>
                        edited(() =>
                          setPoints(
                            points.map((p, j) =>
                              j === i ? { ...p, y: Number(e.target.value) / 100 } : p,
                            ),
                          ),
                        )
                      }
                    />
                  </label>
                  <button
                    type="button"
                    disabled={points.length <= 2}
                    aria-label={`Remove ${definition.label} point ${i + 1}`}
                    onClick={() => edited(() => setPoints(points.filter((_, j) => i !== j)))}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() =>
                  edited(() =>
                    setPoints([
                      ...points,
                      {
                        x: Math.min(130, Math.max(...points.map((p) => p.x)) + 1),
                        y: rate ?? definition.rate,
                      },
                    ]),
                  )
                }
              >
                Add age point
              </button>
            </div>
          )}
        </>
      )}
      {error && (
        <p id={errorId} role="alert" className="field-error">
          {error}
        </p>
      )}
    </details>
  );
}

/** Every rate in one sheet with one Save: edits wait until it is pressed, then the plan recalculates once. */
export default function AssumptionsPanel({ plan }: { plan: PlanData }) {
  const inflation = plan.assumption_curves.find((c) => c.curve_type === "inflation");
  const inflationRate =
    (inflation?.mode === "fixed" ? inflation.fixed_rate : null) ??
    plan.assumption_defaults?.inflation ??
    0.03;
  const pending = useRef(new Map<PendingKey, PendingSave>());
  const [dirty, setDirty] = useState(0);
  const [saving, setSaving] = useState(false);
  const onPending = useCallback((key: PendingKey, save: PendingSave | null) => {
    if (save) pending.current.set(key, save);
    else pending.current.delete(key);
    setDirty(pending.current.size);
  }, []);

  async function saveAll() {
    // One invalid row stops the whole save; every invalid row shows why, the first one open.
    const checks = [...pending.current.values()].map((item) => item.check());
    if (checks.includes(false)) return;
    setSaving(true);
    try {
      for (const [key, item] of [...pending.current]) {
        if (await item.save()) pending.current.delete(key);
      }
      setDirty(pending.current.size);
      if (usePlanStore.getState().plan?.id === plan.id)
        await usePlanStore.getState().loadPlan(plan.id);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>Annual nominal rates.</p>
      <fieldset
        disabled={saving}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
        data-unsaved-changes={dirty > 0 || undefined}
      >
        {assumptions.map((fallback) => {
          const definition = {
            ...fallback,
            rate:
              plan.assumption_defaults?.[fallback.type] ??
              (fallback.followsInflation ? inflationRate : fallback.rate),
          };
          const existing = plan.assumption_curves.find((c) => c.curve_type === definition.type);
          return (
            <AssumptionRow
              key={`${plan.id}-${definition.type}-${definition.rate}-${JSON.stringify(existing)}`}
              plan={plan}
              definition={definition}
              existing={existing}
              onPending={onPending}
            />
          );
        })}
        <AssetLocationPanel plan={plan} onPending={onPending} />
        <button
          type="button"
          style={{ marginTop: 12 }}
          disabled={dirty === 0}
          aria-busy={saving}
          onClick={() => void saveAll()}
        >
          {saving ? "Saving…" : "Save assumptions"}
        </button>
      </fieldset>
    </div>
  );
}

function AssetLocationPanel({
  plan,
  onPending,
}: {
  plan: PlanData;
  onPending: (key: PendingKey, pending: PendingSave | null) => void;
}) {
  const { adapter } = useStorage();
  return (
    <AssetLocationForm
      key={`${plan.id}-${JSON.stringify(plan.tax_settings?.asset_location ?? null)}`}
      plan={plan}
      onSave={async (tax_settings) => {
        await adapter.updatePlan(plan.id, { tax_settings });
      }}
      onPending={(pending) => onPending("asset_location", pending)}
    />
  );
}
