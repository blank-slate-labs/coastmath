import { useState } from "react";
import { useFormDraftStatus } from "@/utils/form_draft_status";
import { useSaveGroupPart } from "./save_group";
import type {
  SpendingFlexScope,
  SpendingInterpolation,
  SpendingPerformanceMode,
  SpendingRules,
  SpendingSurplusMode,
} from "@/types/plan";

interface MilestoneOption {
  id: string;
  name: string;
}

interface FlexSpendingConfigProps {
  planId: string;
  initial: SpendingRules | null;
  milestones?: MilestoneOption[];
  /** Omitted inside a SaveGroup, which saves the form with the others. */
  onSave?: (planId: string, rules: SpendingRules | null) => void | Promise<void>;
}

interface ThresholdRow {
  threshold: string;
  reduction: string;
}

interface UpsideRow {
  threshold: string;
  increase: string;
}

const SCOPE_OPTIONS: { value: SpendingFlexScope; label: string }[] = [
  { value: "expenses", label: "Ordinary expenses" },
  { value: "strategy_spending", label: "Withdrawal-strategy spending" },
  { value: "leftover_spending", label: "Leftover spending" },
];

function hasUpside(initial: SpendingRules | null): boolean {
  return (initial?.upside_thresholds?.length ?? 0) > 0;
}

function initialUpsideRows(initial: SpendingRules | null): UpsideRow[] {
  return (initial?.upside_thresholds ?? []).map((point) => ({
    threshold: String(Math.round(point.threshold * 1e6) / 1e4),
    increase: String(Math.round(point.increase * 1e6) / 1e4),
  }));
}

function initialRows(initial: SpendingRules | null): ThresholdRow[] {
  // An upside-only document has no downside rule to show.
  if (hasUpside(initial) && !initial?.thresholds?.length && initial?.flex_threshold == null)
    return [];
  if (initial?.thresholds?.length) {
    return initial.thresholds.map((rule) => ({
      threshold: String(rule.threshold * 100),
      reduction: String(rule.reduction * 100),
    }));
  }
  return [
    {
      threshold: initial?.flex_threshold != null ? String(initial.flex_threshold * 100) : "-10",
      reduction: initial ? String(initial.flex_reduction * 100) : "20",
    },
  ];
}

export default function FlexSpendingConfig({
  planId,
  initial,
  milestones = [],
  onSave,
}: FlexSpendingConfigProps) {
  const [enabled, setEnabled] = useState(
    initial?.flex_threshold != null || (initial?.thresholds?.length ?? 0) > 0 || hasUpside(initial),
  );
  const [surplusMode, setSurplusMode] = useState<SpendingSurplusMode>(
    initial?.surplus_mode ?? "save",
  );
  const [scope, setScope] = useState<SpendingFlexScope[]>(initial?.flex_scope ?? ["expenses"]);
  const [upsideRows, setUpsideRows] = useState<UpsideRow[]>(() => initialUpsideRows(initial));
  const [performanceMode, setPerformanceMode] = useState<SpendingPerformanceMode>(
    initial?.performance_mode ?? "trailing_return",
  );
  const [interpolation, setInterpolation] = useState<SpendingInterpolation>(
    initial?.interpolation ?? "step",
  );
  const [rows, setRows] = useState<ThresholdRow[]>(() => initialRows(initial));
  const [spendingFloor, setSpendingFloor] = useState(
    initial?.spending_floor != null ? String(initial.spending_floor * 100) : "80",
  );
  const [lookbackYears, setLookbackYears] = useState(initial?.lookback_years ?? 1);
  const [startMilestoneId, setStartMilestoneId] = useState(initial?.start_milestone_id ?? "");
  const [endMilestoneId, setEndMilestoneId] = useState(initial?.end_milestone_id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function persist(rules: SpendingRules | null) {
    setSaving(true);
    setSaved(false);
    try {
      await onSave?.(planId, rules);
      markSaved();
      setSaved(true);
    } catch {
      setError("Could not save spending rules. Your edits are retained; try again.");
    } finally {
      setSaving(false);
    }
  }

  /** The rules to save; throws an Error naming the first invalid input. */
  function buildRules(): SpendingRules | null {
    // Surplus handling does not depend on the flex rules, so it saves on its own.
    const surplus: Pick<SpendingRules, "surplus_mode"> =
      surplusMode === "spend_leftover" ? { surplus_mode: "spend_leftover" } : {};

    if (!enabled) {
      return surplusMode === "spend_leftover"
        ? { flex_threshold: null, flex_reduction: 0.2, lookback_years: 1, ...surplus }
        : null;
    }

    const activeScope = SCOPE_OPTIONS.map((option) => option.value).filter(
      (value) =>
        scope.includes(value) &&
        (value !== "leftover_spending" || surplusMode === "spend_leftover"),
    );
    if (activeScope.length === 0) {
      throw new Error("Choose at least one spending type for the flex rules to apply to.");
    }
    const useUpside = performanceMode === "all_time_high" && upsideRows.length > 0;
    const parsedUpside = upsideRows.map((row) => ({
      thresholdPct: Number(row.threshold),
      increasePct: Number(row.increase),
      blank: row.threshold.trim() === "" || row.increase.trim() === "",
    }));
    if (useUpside) {
      if (
        parsedUpside.some(
          (row) =>
            row.blank ||
            !Number.isFinite(row.thresholdPct) ||
            row.thresholdPct <= 0 ||
            row.thresholdPct > 1000,
        )
      ) {
        throw new Error("Each upside threshold must be above 0 and at most 1000 percent.");
      }
      if (
        parsedUpside.some(
          (row) =>
            !Number.isFinite(row.increasePct) || row.increasePct < 0 || row.increasePct > 200,
        )
      ) {
        throw new Error("Each spending increase must be between 0 and 200 percent.");
      }
      if (new Set(parsedUpside.map((row) => row.thresholdPct)).size !== parsedUpside.length) {
        throw new Error("Upside thresholds must be different from each other.");
      }
    }
    if (rows.length === 0 && !useUpside) {
      throw new Error("Add at least one threshold.");
    }

    const floorPct = Number(spendingFloor);
    if (
      !Number.isFinite(floorPct) ||
      floorPct < 0 ||
      floorPct > 100 ||
      spendingFloor.trim() === ""
    ) {
      throw new Error("Spending floor must be between 0 and 100 percent.");
    }
    if (lookbackYears < 1 || lookbackYears > 5) {
      throw new Error("Lookback period must be between 1 and 5 years.");
    }

    const parsedRows = rows.map((row) => ({
      thresholdPct: Number(row.threshold),
      reductionPct: Number(row.reduction),
    }));
    if (
      parsedRows.some(
        (row) =>
          !Number.isFinite(row.thresholdPct) || row.thresholdPct < -100 || row.thresholdPct > 100,
      )
    ) {
      throw new Error("Each threshold must be between -100 and 100 percent.");
    }
    if (
      parsedRows.some(
        (row) =>
          !Number.isFinite(row.reductionPct) || row.reductionPct < 0 || row.reductionPct > 100,
      )
    ) {
      throw new Error("Each reduction must be between 0 and 100 percent.");
    }

    const thresholds = parsedRows.map((row) => ({
      threshold: row.thresholdPct / 100,
      reduction: row.reductionPct / 100,
    }));
    const first = thresholds[0];
    const additions: Partial<SpendingRules> = {
      ...surplus,
      ...(useUpside
        ? {
            upside_thresholds: parsedUpside
              .map((row) => ({
                threshold: Math.round(row.thresholdPct * 1e4) / 1e6,
                increase: Math.round(row.increasePct * 1e4) / 1e6,
              }))
              .sort((a, b) => a.threshold - b.threshold),
          }
        : {}),
      ...(activeScope.length === 1 && activeScope[0] === "expenses"
        ? {}
        : { flex_scope: activeScope }),
    };
    const hasAdvancedFields = Boolean(
      useUpside ||
      initial?.thresholds?.length ||
      performanceMode === "all_time_high" ||
      interpolation === "linear" ||
      thresholds.length > 1 ||
      startMilestoneId ||
      endMilestoneId,
    );

    // Keep the original JSONB shape for an unchanged one-rule trailing setup.
    // This preserves the legacy strict-below boundary and defaults.
    const rules: SpendingRules = hasAdvancedFields
      ? {
          flex_threshold: first?.threshold ?? null,
          flex_reduction: first?.reduction ?? 0.2,
          lookback_years: lookbackYears,
          spending_floor: floorPct / 100,
          performance_mode: performanceMode,
          interpolation,
          thresholds,
          start_milestone_id: startMilestoneId || null,
          end_milestone_id: endMilestoneId || null,
          ...additions,
        }
      : {
          flex_threshold: first.threshold,
          flex_reduction: first.reduction,
          lookback_years: lookbackYears,
          spending_floor: floorPct / 100,
          ...additions,
        };
    return rules;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    let rules: SpendingRules | null;
    try {
      rules = buildRules();
    } catch (err) {
      setError((err as Error).message);
      return;
    }
    void persist(rules);
  }

  const { dirty, markSaved } = useFormDraftStatus(
    JSON.stringify([
      enabled,
      surplusMode,
      scope,
      upsideRows,
      performanceMode,
      interpolation,
      rows,
      spendingFloor,
      lookbackYears,
      startMilestoneId,
      endMilestoneId,
    ]),
  );
  const embedded = useSaveGroupPart("spending_rules", {
    build: () => ({ spending_rules: buildRules() }),
    dirty,
    markSaved,
  });
  const Wrapper = embedded ? "div" : "form";

  return (
    <Wrapper
      onSubmit={embedded ? undefined : handleSubmit}
      data-unsaved-changes={(!embedded && dirty) || undefined}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        border: "1px solid var(--surface-border)",
        borderRadius: 4,
      }}
    >
      <fieldset disabled={saving} style={{ border: 0, padding: 0, display: "grid", gap: 10 }}>
        <h3 style={{ margin: 0 }}>Flex Spending Rules</h3>
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
          Uses prior-year investment performance, excluding contributions and withdrawals.
        </p>

        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Enable flex spending rules
        </label>

        {enabled && (
          <>
            <label>
              Performance measure
              <select
                value={performanceMode}
                onChange={(e) => setPerformanceMode(e.target.value as SpendingPerformanceMode)}
                style={{ display: "block", width: "100%" }}
              >
                <option value="trailing_return">Trailing return</option>
                <option value="all_time_high">Drawdown from all-time high</option>
              </select>
            </label>

            <p style={{ margin: 0, fontSize: 13 }}>
              {performanceMode === "all_time_high"
                ? "Drawdown thresholds"
                : "Trailing return thresholds"}
            </p>
            {rows.map((row, index) => (
              <div
                key={index}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr auto",
                  gap: 8,
                  alignItems: "end",
                }}
              >
                <label>
                  {index === 0 && performanceMode === "trailing_return"
                    ? "Reduce spending when trailing return is below (%)"
                    : `Threshold ${index + 1} (%)`}
                  <input
                    aria-label={
                      index === 0 && performanceMode === "trailing_return"
                        ? "Trailing return threshold"
                        : `Threshold ${index + 1}`
                    }
                    type="number"
                    min="-100"
                    max="100"
                    step="1"
                    required
                    value={row.threshold}
                    onChange={(e) =>
                      setRows((current) =>
                        current.map((item, i) =>
                          i === index ? { ...item, threshold: e.target.value } : item,
                        ),
                      )
                    }
                    style={{ display: "block", width: "100%" }}
                  />
                </label>
                <label>
                  Reduction {index + 1} (%)
                  <input
                    aria-label={`Reduction ${index + 1}`}
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    required
                    value={row.reduction}
                    onChange={(e) =>
                      setRows((current) =>
                        current.map((item, i) =>
                          i === index ? { ...item, reduction: e.target.value } : item,
                        ),
                      )
                    }
                    style={{ display: "block", width: "100%" }}
                  />
                </label>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={
                    rows.length === 1 &&
                    !(performanceMode === "all_time_high" && upsideRows.length > 0)
                  }
                  onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn-secondary"
              onClick={() =>
                setRows((current) => [...current, { threshold: "-20", reduction: "30" }])
              }
            >
              Add threshold
            </button>

            {performanceMode === "all_time_high" && (
              <>
                <p style={{ margin: 0, fontSize: 13 }}>Upside points</p>
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  Spending rises when the portfolio finishes above its earlier high. At or below
                  that high, spending is not raised.
                </span>
                {upsideRows.map((row, index) => (
                  <div
                    key={index}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr auto",
                      gap: 8,
                      alignItems: "end",
                    }}
                  >
                    <label>
                      Upside threshold {index + 1} (% above earlier high)
                      <input
                        aria-label={`Upside threshold ${index + 1}`}
                        type="number"
                        min="0"
                        max="1000"
                        step="1"
                        required
                        value={row.threshold}
                        onChange={(e) =>
                          setUpsideRows((current) =>
                            current.map((item, i) =>
                              i === index ? { ...item, threshold: e.target.value } : item,
                            ),
                          )
                        }
                        style={{ display: "block", width: "100%" }}
                      />
                    </label>
                    <label>
                      Increase {index + 1} (%)
                      <input
                        aria-label={`Increase ${index + 1}`}
                        type="number"
                        min="0"
                        max="200"
                        step="1"
                        required
                        value={row.increase}
                        onChange={(e) =>
                          setUpsideRows((current) =>
                            current.map((item, i) =>
                              i === index ? { ...item, increase: e.target.value } : item,
                            ),
                          )
                        }
                        style={{ display: "block", width: "100%" }}
                      />
                    </label>
                    <button
                      type="button"
                      className="btn-secondary"
                      disabled={rows.length === 0 && upsideRows.length === 1}
                      onClick={() =>
                        setUpsideRows((current) => current.filter((_, i) => i !== index))
                      }
                    >
                      Remove upside point
                    </button>
                  </div>
                ))}
                {upsideRows.length < 10 && (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      setUpsideRows((current) => [...current, { threshold: "10", increase: "10" }])
                    }
                  >
                    Add upside point
                  </button>
                )}
              </>
            )}

            <label>
              Interpolation
              <select
                value={interpolation}
                onChange={(e) => setInterpolation(e.target.value as SpendingInterpolation)}
                style={{ display: "block", width: "100%" }}
              >
                <option value="step">Step</option>
                <option value="linear">Linear</option>
              </select>
            </label>

            <label>
              Spending floor (%)
              <input
                aria-label="Spending floor (%)"
                type="number"
                min="0"
                max="100"
                step="1"
                value={spendingFloor}
                onChange={(e) => setSpendingFloor(e.target.value)}
                style={{ display: "block", width: "100%" }}
              />
              <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                Minimum spending as a share of the original amount.
              </span>
            </label>

            {performanceMode === "trailing_return" && (
              <label>
                Trailing lookback period (years)
                <select
                  aria-label="Lookback period (years)"
                  value={lookbackYears}
                  onChange={(e) => setLookbackYears(Number(e.target.value))}
                  style={{ display: "block", width: "100%" }}
                >
                  {[1, 2, 3, 4, 5].map((years) => (
                    <option key={years} value={years}>
                      {years} year{years > 1 ? "s" : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <fieldset style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: 4 }}>
              <legend style={{ fontSize: 13, padding: 0 }}>Apply flex rules to</legend>
              {SCOPE_OPTIONS.map((option) => {
                const unavailable =
                  option.value === "leftover_spending" && surplusMode !== "spend_leftover";
                return (
                  <label
                    key={option.value}
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <input
                      type="checkbox"
                      disabled={unavailable}
                      checked={!unavailable && scope.includes(option.value)}
                      onChange={(e) =>
                        setScope((current) =>
                          e.target.checked
                            ? [...current, option.value]
                            : current.filter((value) => value !== option.value),
                        )
                      }
                    />
                    {option.label}
                  </label>
                );
              })}
            </fieldset>

            <label>
              Start milestone (optional)
              <select
                value={startMilestoneId}
                onChange={(e) => setStartMilestoneId(e.target.value)}
                style={{ display: "block", width: "100%" }}
              >
                <option value="">From the beginning</option>
                {milestones.map((milestone) => (
                  <option key={milestone.id} value={milestone.id}>
                    {milestone.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              End milestone (optional)
              <select
                value={endMilestoneId}
                onChange={(e) => setEndMilestoneId(e.target.value)}
                style={{ display: "block", width: "100%" }}
              >
                <option value="">No end milestone</option>
                {milestones.map((milestone) => (
                  <option key={milestone.id} value={milestone.id}>
                    {milestone.name}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}

        <label>
          Unallocated cash at year end
          <select
            aria-label="Unallocated cash at year end"
            value={surplusMode}
            onChange={(e) => setSurplusMode(e.target.value as SpendingSurplusMode)}
            style={{ display: "block", width: "100%" }}
          >
            <option value="save">Save it</option>
            <option value="spend_leftover">Spend it as extra discretionary spending</option>
          </select>
        </label>

        {error && (
          <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
            {error}
          </div>
        )}
        {!embedded && <button type="submit">{saving ? "Saving…" : "Save Spending Rules"}</button>}
      </fieldset>
      {!embedded && saved && <p role="status">Spending rules saved.</p>}
    </Wrapper>
  );
}
