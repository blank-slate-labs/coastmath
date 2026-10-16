import { useEffect, useRef, useState } from "react";

import { usePlanStore } from "@/stores/plan_store";
import { useStorage } from "@/storage/context";
import * as api from "@/api/client";
import type {
  Account,
  StrategyDrawdownPreset,
  StrategySearchCandidate,
  StrategySearchRequest,
  StrategySearchResponse,
  StrategySearchWindowRequest,
  TaxStrategyObjective,
} from "@/types/plan";
import { ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES } from "@/domain/account_types";
import { fillableBracketRates, includesRate } from "@/domain/federal_bracket_rates";
import { compactCurrency, ratePct } from "@/utils/format";
import {
  APPLY_STEP_LABELS,
  StrategyApplyConflict,
  StrategyApplyPartial,
  applyStrategyCandidate,
  stepsFor,
  type ApplyStep,
} from "./tax_strategy_apply";
import {
  STRATEGY_OBJECTIVES,
  formatObjective,
  formatObjectiveDelta,
  isImprovement,
  objectiveOption,
} from "./tax_strategy_objectives";
import { helpTextStyle } from "../form_styles";

const MAX_WINDOWS = 4;
const MAX_BUDGET = 128;
const PRESETS: { value: StrategyDrawdownPreset; label: string }[] = [
  { value: "taxable_first", label: "Cash and taxable accounts first" },
  { value: "pretax_first", label: "Pre-tax accounts first" },
  { value: "roth_before_pretax", label: "Roth before pre-tax" },
];
const PRESET_LABELS: Record<string, string> = {
  saved: "Saved order",
  ...Object.fromEntries(PRESETS.map((p) => [p.value, p.label])),
};
const VISIBLE = 10;

/** A side is "" (start or end of plan), a milestone id, YEAR or AGE; the value holds the year or age. */
interface WindowDraft {
  start: string;
  end: string;
  startValue?: string;
  endValue?: string;
}
const YEAR = "__year";
const AGE = "__age";

type Side = "start" | "end";

/** The request bound for one side, or an error message. */
function windowSide(
  w: WindowDraft,
  side: Side,
): { value: Partial<StrategySearchWindowRequest>; error: string | null } {
  const kind = w[side];
  if (kind !== YEAR && kind !== AGE)
    return { value: { [`${side}_milestone_id`]: kind || null }, error: null };
  const raw = (side === "start" ? w.startValue : w.endValue) ?? "";
  const number = Number(raw);
  const [min, max, what] = kind === YEAR ? [1900, 2200, "year"] : [0, 120, "age"];
  if (raw.trim() === "" || !Number.isInteger(number) || number < min || number > max) {
    return {
      value: {},
      error: `Window ${side} ${what} must be a whole number from ${min} to ${max}.`,
    };
  }
  return { value: { [`${side}_${what}`]: number }, error: null };
}

/** The search request for a window draft, or an error message. */
export function windowRequest(w: WindowDraft): {
  window: StrategySearchWindowRequest;
  error: string | null;
} {
  if (!w.start && !w.end)
    return { window: {}, error: "Each timing window needs a start or an end." };
  const start = windowSide(w, "start");
  const end = windowSide(w, "end");
  const window = { ...start.value, ...end.value } as StrategySearchWindowRequest;
  const error = start.error ?? end.error;
  if (error) return { window, error };
  for (const what of ["year", "age"] as const) {
    const first = window[`start_${what}`];
    const last = window[`end_${what}`];
    if (first != null && last != null && last < first)
      return { window, error: `A window's end ${what} must not be before its start ${what}.` };
  }
  return { window, error: null };
}

/**
 * Advanced bounded search: runs the full projection for a staged grid of tax-target
 * brackets, actions, withdrawal orders and timing windows. The best result is only
 * the best of what was simulated. Nothing changes until a candidate is reviewed and applied.
 */
export function TaxStrategySearchPanel({ accounts }: { accounts: Account[] }) {
  const plan = usePlanStore((s) => s.plan);
  const accountsRevision = usePlanStore((s) => s.accountsRevision);
  const { adapter } = useStorage();
  const [objective, setObjective] = useState<TaxStrategyObjective>("net_legacy");
  const [rates, setRates] = useState<number[]>([0.12, 0.22, 0.24]);
  const [convert, setConvert] = useState(true);
  const [convSource, setConvSource] = useState("");
  const [convTarget, setConvTarget] = useState("");
  const [harvest, setHarvest] = useState(false);
  const [harvestSource, setHarvestSource] = useState("");
  const [blend, setBlend] = useState(false);
  const [presets, setPresets] = useState<StrategyDrawdownPreset[]>([]);
  const [windows, setWindows] = useState<WindowDraft[]>([]);
  const [budget, setBudget] = useState("64");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<StrategySearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [reviewKey, setReviewKey] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyDone, setApplyDone] = useState<ApplyStep[]>([]);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);
  const request = useRef(0);

  // A changed plan or account list makes a finished search obsolete, unless an apply is mid-flight.
  useEffect(() => {
    if (applying) return;
    request.current += 1;
    setResult(null);
    setRunning(false);
    setReviewKey(null);
    setApplyDone([]);
    setApplyError(null);
    setConflict(false);
    return () => {
      request.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- applying only gates the reset; an apply finishing must not clear its own result
  }, [plan, accountsRevision]);

  if (!plan) return null;
  const currentPlan = plan;
  const sources = accounts.filter((a) => TRADITIONAL_RETIREMENT_TYPES.has(a.account_type));
  const convSourceAccount = sources.find((a) => a.id === convSource);
  const roths = accounts.filter(
    (a) =>
      ROTH_TYPES.has(a.account_type) &&
      (a.owner ?? "self") === (convSourceAccount?.owner ?? "self"),
  );
  const brokerages = accounts.filter((a) => a.account_type === "taxable_brokerage");
  const harvestAccount = brokerages.find((a) => a.id === harvestSource);
  const hasAction = convert || harvest || blend;
  const budgetNumber = Number(budget);
  const unsimulated = result ? result.counts.skipped_by_budget + result.counts.screened_out : 0;
  const flat = currentPlan.tax_settings?.mode === "flat";
  // The plan's own bracket rates, without the built-in top bracket, which has no top
  // to fill; a chosen rate not offered is not sent.
  const availableRates = fillableBracketRates(currentPlan.tax_settings);
  const chosenRates = rates.filter((r) => includesRate(availableRates, r));

  function invalidate() {
    request.current += 1;
    setResult(null);
    setReviewKey(null);
    setApplied(null);
    setConflict(false);
    setApplyDone([]);
    setApplyError(null);
  }

  function validate(): string | null {
    if (!hasAction && presets.length === 0)
      return "Choose at least one action or withdrawal order to try.";
    if (hasAction && chosenRates.length === 0) return "Choose at least one bracket rate to try.";
    if (convert && (!convSourceAccount || !roths.some((a) => a.id === convTarget)))
      return "Choose a pre-tax source and a Roth destination for the same person.";
    if (harvest && !harvestAccount)
      return "Choose a taxable brokerage account for gain harvesting.";
    if (harvest && harvestAccount?.cost_basis == null)
      return "Enter the brokerage account's cost basis under Accounts before harvesting gains.";
    if (!Number.isInteger(budgetNumber) || budgetNumber < 2 || budgetNumber > MAX_BUDGET)
      return `The simulation budget must be a whole number from 2 to ${MAX_BUDGET}.`;
    if (hasAction && budgetNumber < chosenRates.length + 1)
      return "The budget must cover the baseline and one simulation for each bracket rate.";
    const windowError = windows.map(windowRequest).find((w) => w.error)?.error;
    if (windowError) return windowError;
    if (windows.length > 0 && !convert && !harvest)
      return "Timing windows apply to conversions and gain harvesting.";
    return null;
  }

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setApplied(null);
    setResult(null);
    setReviewKey(null);
    setConflict(false);
    setApplyDone([]);
    setApplyError(null);
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    const activeWindows: StrategySearchWindowRequest[] =
      convert || harvest ? windows.map((w) => windowRequest(w).window) : [];
    const body: StrategySearchRequest = {
      objective,
      bracket_rates: hasAction ? [...chosenRates].sort((a, b) => a - b) : [],
      conversion: convert ? { source_account_id: convSource, target_account_id: convTarget } : null,
      harvest: harvest ? { source_account_id: harvestSource } : null,
      blend_withdrawals: blend,
      drawdown_presets: presets,
      windows: activeWindows,
      max_simulations: budgetNumber,
    };
    setRunning(true);
    const current = ++request.current;
    try {
      const found = await api.searchTaxStrategies(currentPlan.id, body);
      if (request.current === current) {
        setResult(found);
        setShowAll(false);
      }
    } catch {
      if (request.current === current)
        setError(
          "Could not run the search. Check the plan simulates successfully and the choices are valid, then try again.",
        );
    } finally {
      if (request.current === current) setRunning(false);
    }
  }

  async function apply(candidate: StrategySearchCandidate) {
    if (!result) return;
    setApplying(true);
    setApplyError(null);
    setConflict(false);
    try {
      await applyStrategyCandidate(
        adapter,
        currentPlan.id,
        candidate,
        result.priorities_revision,
        applyDone,
      );
      setApplyDone([]);
      setReviewKey(null);
      setResult(null);
      setApplied(candidate.label);
      if (usePlanStore.getState().plan?.id === currentPlan.id)
        await usePlanStore.getState().loadPlan(currentPlan.id);
    } catch (err) {
      if (err instanceof StrategyApplyConflict) {
        setConflict(true);
        setApplyDone(err.done);
        setApplyError(err.message);
      } else if (err instanceof StrategyApplyPartial) {
        setApplyDone(err.done);
        setApplyError(
          `${err.message} Saved: ${err.done.map((s) => APPLY_STEP_LABELS[s]).join(", ") || "nothing"}. Not saved: ${err.remaining.map((s) => APPLY_STEP_LABELS[s]).join(", ")}.`,
        );
      } else
        setApplyError(`Could not apply the strategy. ${err instanceof Error ? err.message : ""}`);
    } finally {
      setApplying(false);
    }
  }

  async function reloadLatest() {
    setApplyError(null);
    setConflict(false);
    setApplyDone([]);
    await usePlanStore.getState().loadPlan(currentPlan.id);
  }

  const toggle = <T,>(list: T[], item: T, on: boolean) =>
    on ? [...list, item] : list.filter((x) => x !== item);
  const windowLabel = (c: StrategySearchCandidate) =>
    c.window_index == null ? "whole plan" : (result?.windows[c.window_index]?.label ?? "window");
  const ordered = result?.candidates ?? [];
  const visible = showAll ? ordered : ordered.slice(0, VISIBLE);
  const review = ordered.find((c) => c.key === reviewKey) ?? null;

  return (
    <details style={{ display: "grid", gap: 10 }}>
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>Advanced search</summary>
      <section
        style={{ display: "grid", gap: 10, marginTop: 10 }}
        aria-label="Advanced strategy search"
      >
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
          Runs a full projection for a bounded grid of tax-target brackets, actions, withdrawal
          orders and timing windows. It shows the best of the combinations it simulated, never a
          global optimum. Nothing changes until you review and apply a result.
        </p>
        {flat && (
          <p role="alert" style={{ margin: 0, fontSize: 13, color: "var(--color-danger)" }}>
            This plan uses flat tax rates, so bracket targets have no effect.
          </p>
        )}
        <form noValidate onSubmit={run} onChange={invalidate} style={{ display: "grid", gap: 10 }}>
          <fieldset
            disabled={running || applying || flat}
            style={{ border: 0, padding: 0, minWidth: 0, display: "grid", gap: 10 }}
          >
            <label>
              Search objective
              <select
                value={objective}
                onChange={(e) => setObjective(e.target.value as TaxStrategyObjective)}
              >
                {STRATEGY_OBJECTIVES.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend style={{ fontSize: 13 }}>
                Federal bracket rates to try as the tax target
              </legend>
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                {availableRates.map((r) => (
                  <label
                    key={r}
                    style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}
                  >
                    <input
                      type="checkbox"
                      checked={includesRate(chosenRates, r)}
                      onChange={(e) => setRates(toggle(chosenRates, r, e.target.checked))}
                    />
                    {Number((r * 100).toFixed(2))}% bracket
                  </label>
                ))}
              </div>
              <span style={helpTextStyle}>
                Each action below aims at the plan tax target set to one of these brackets. A saved
                target is replaced only if you apply a result.
              </span>
            </fieldset>
            <fieldset style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: 8 }}>
              <legend style={{ fontSize: 13 }}>Actions to try</legend>
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={convert}
                  onChange={(e) => setConvert(e.target.checked)}
                />{" "}
                Roth conversions to fill the bracket
              </label>
              {convert && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                    gap: 10,
                  }}
                >
                  <label>
                    Conversion source
                    <select
                      value={convSource}
                      onChange={(e) => {
                        setConvSource(e.target.value);
                        setConvTarget("");
                      }}
                    >
                      <option value="">Choose account</option>
                      {sources.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name} ({a.owner ?? "self"})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Conversion destination
                    <select
                      disabled={!convSourceAccount || !roths.length}
                      value={convTarget}
                      onChange={(e) => setConvTarget(e.target.value)}
                    >
                      <option value="">
                        {!convSourceAccount
                          ? "Choose a source first"
                          : !roths.length
                            ? "No eligible Roth account"
                            : "Choose account"}
                      </option>
                      {convSourceAccount &&
                        roths.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name} ({a.owner ?? "self"})
                          </option>
                        ))}
                    </select>
                  </label>
                </div>
              )}
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={harvest}
                  onChange={(e) => setHarvest(e.target.checked)}
                />{" "}
                Capital-gain harvesting
              </label>
              {harvest && (
                <label>
                  Harvest account
                  <select value={harvestSource} onChange={(e) => setHarvestSource(e.target.value)}>
                    <option value="">Choose account</option>
                    {brokerages.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.owner ?? "self"})
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={blend}
                  onChange={(e) => setBlend(e.target.checked)}
                />{" "}
                Blend withdrawals up to the tax target
              </label>
            </fieldset>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend style={{ fontSize: 13 }}>Withdrawal orders to try</legend>
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                {PRESETS.map((p) => (
                  <label
                    key={p.value}
                    style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}
                  >
                    <input
                      type="checkbox"
                      checked={presets.includes(p.value)}
                      onChange={(e) => setPresets(toggle(presets, p.value, e.target.checked))}
                    />
                    {p.label}
                  </label>
                ))}
              </div>
              <span style={helpTextStyle}>
                Regroups your saved accounts and keeps your saved order within each group. The saved
                order is always compared.
              </span>
            </fieldset>
            <fieldset style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: 8 }}>
              <legend style={{ fontSize: 13 }}>
                Timing windows for conversions and harvesting
              </legend>
              {windows.map((w, i) => {
                const update = (patch: Partial<WindowDraft>) => {
                  setWindows(windows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                  invalidate();
                };
                const sideControls = (side: Side) => {
                  const kind = w[side];
                  const verb = side === "start" ? "starts" : "ends";
                  const valueKey = side === "start" ? "startValue" : "endValue";
                  return (
                    <>
                      <label>
                        Window {i + 1} {verb}
                        <select value={kind} onChange={(e) => update({ [side]: e.target.value })}>
                          <option value="">
                            {side === "start" ? "Start of plan" : "End of plan"}
                          </option>
                          <option value={YEAR}>
                            {side === "start" ? "In a year" : "After a year"}
                          </option>
                          <option value={AGE}>
                            {side === "start" ? "At an age" : "After an age"}
                          </option>
                          {currentPlan.milestones.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      {(kind === YEAR || kind === AGE) && (
                        <label>
                          Window {i + 1} {side} {kind === YEAR ? "year" : "age"}
                          <input
                            type="number"
                            step={1}
                            min={kind === YEAR ? 1900 : 0}
                            max={kind === YEAR ? 2200 : 120}
                            style={{ width: 80 }}
                            value={w[valueKey] ?? ""}
                            onChange={(e) => update({ [valueKey]: e.target.value })}
                          />
                        </label>
                      )}
                    </>
                  );
                };
                return (
                  <div
                    key={i}
                    style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "end" }}
                  >
                    {sideControls("start")}
                    {sideControls("end")}
                    <button
                      type="button"
                      onClick={() => {
                        setWindows(windows.filter((_, j) => j !== i));
                        invalidate();
                      }}
                    >
                      Remove window {i + 1}
                    </button>
                  </div>
                );
              })}
              <div>
                <button
                  type="button"
                  disabled={windows.length >= MAX_WINDOWS}
                  onClick={() => {
                    setWindows([...windows, { start: "", end: "" }]);
                    invalidate();
                  }}
                >
                  Add timing window
                </button>
                <span style={{ ...helpTextStyle, marginLeft: 8 }}>
                  Windows begin and end at plan milestones, a calendar year or your age; a year or
                  age end is included. Applying a year or age window adds its milestones to the
                  plan. Without a window, rules run for the whole plan.
                </span>
              </div>
            </fieldset>
            <label>
              Simulation budget (2 to {MAX_BUDGET})
              <input
                type="number"
                min={2}
                max={MAX_BUDGET}
                step={1}
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
            </label>
            <span style={helpTextStyle}>
              Every simulation runs the whole plan. If the grid is larger than the budget, the
              simplest combinations run first and the rest are skipped.
            </span>
            <div>
              <button type="submit">{running ? "Searching…" : "Run search"}</button>
            </div>
          </fieldset>
        </form>
        {running && (
          <p role="status" style={helpTextStyle}>
            Running up to {Number.isFinite(budgetNumber) ? budgetNumber : "?"} full simulations…
          </p>
        )}
        {error && (
          <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
            {error}
          </div>
        )}
        {applied && (
          <p role="status" style={{ margin: 0, fontSize: 13 }}>
            Applied "{applied}". The projection has been recalculated.
          </p>
        )}

        {result && (
          <div style={{ display: "grid", gap: 10 }}>
            <p style={{ margin: 0, fontSize: 13 }} data-testid="search-counts">
              <strong>
                Simulated {result.counts.simulated} of up to {result.counts.max_simulations}
              </strong>{" "}
              ({result.counts.stage1_simulated} in the rate scan, {result.counts.stage2_simulated}{" "}
              in combinations; {result.counts.cache_hits} repeated{" "}
              {result.counts.cache_hits === 1 ? "candidate" : "candidates"} reused).
              {result.survivor_rates.length > 0 && (
                <> Searched first: {result.survivor_rates.map((r) => ratePct(r)).join(", ")}.</>
              )}
            </p>
            {result.counts.budget_exhausted && (
              <p role="status" style={{ margin: 0, fontSize: 13, color: "var(--color-danger)" }}>
                Budget used up: {unsimulated}{" "}
                {unsimulated === 1 ? "combination was" : "combinations were"} not simulated. Raise
                the budget or narrow the choices to cover them.
              </p>
            )}
            <p style={{ margin: 0, fontSize: 13 }}>
              {/* The description already says which end is better. */}
              Objective: <strong>{result.objective_description}</strong>.
              {objectiveOption(result.objective).discounted && (
                <>
                  {" "}
                  Pre-tax balances net of <strong>
                    {ratePct(result.pre_tax_discount_rate)}
                  </strong>{" "}
                  income tax.
                </>
              )}{" "}
              Best of the simulated:{" "}
              <strong>
                {result.candidates.find((c) => c.key === result.best_key)?.label ??
                  "none (no candidate keeps the plan funded)"}
              </strong>
              .
            </p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", fontSize: 13 }} aria-label="Search results">
                <thead>
                  <tr>
                    <th style={{ textAlign: "right" }}>#</th>
                    <th style={{ textAlign: "left" }}>Candidate</th>
                    <th style={{ textAlign: "right" }}>Objective</th>
                    <th style={{ textAlign: "right" }}>Δ vs saved plan</th>
                    <th style={{ textAlign: "right" }}>Net estate</th>
                    <th style={{ textAlign: "right" }}>Lifetime taxes</th>
                    <th style={{ textAlign: "right" }}>Effective rate</th>
                    <th style={{ textAlign: "right" }}>IRMAA</th>
                    <th style={{ textAlign: "right" }}>ACA credits</th>
                    <th style={{ textAlign: "right" }}>RMDs</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((c) => (
                    <tr
                      key={c.key}
                      style={{ fontWeight: c.is_best ? 600 : 400, opacity: c.success ? 1 : 0.7 }}
                    >
                      <td style={{ textAlign: "right" }}>{c.rank}</td>
                      <td>
                        {c.label}
                        {c.is_best ? " · best simulated" : ""}
                        {!c.success ? ` · fails ${c.failure_year}` : ""}
                        {!c.is_baseline && (
                          <div style={helpTextStyle}>
                            {c.bracket_rate != null ? `${ratePct(c.bracket_rate)} bracket · ` : ""}
                            {PRESET_LABELS[c.drawdown_preset] ?? c.drawdown_preset}
                            {c.actions.length ? ` · ${windowLabel(c)}` : ""}
                          </div>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {formatObjective(result.objective, c.objective_value)}
                      </td>
                      <td
                        style={{
                          textAlign: "right",
                          color:
                            c.is_baseline || c.delta_vs_baseline === 0
                              ? "inherit"
                              : isImprovement(result.objective, c.delta_vs_baseline)
                                ? "var(--chart-green)"
                                : "var(--chart-red)",
                        }}
                      >
                        {c.is_baseline
                          ? "—"
                          : formatObjectiveDelta(result.objective, c.delta_vs_baseline)}
                      </td>
                      <td style={{ textAlign: "right" }}>{compactCurrency(c.net_legacy)}</td>
                      <td style={{ textAlign: "right" }}>{compactCurrency(c.lifetime_taxes)}</td>
                      <td style={{ textAlign: "right" }}>
                        {ratePct(c.lifetime_effective_tax_rate)}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {compactCurrency(c.total_irmaa_surcharge)}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {compactCurrency(c.total_aca_subsidies)}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {compactCurrency(c.total_rmd_distributions)}
                      </td>
                      <td>
                        {!c.is_baseline && c.success && c.changes.length > 0 && (
                          <button
                            type="button"
                            disabled={applying}
                            onClick={() => {
                              setReviewKey(c.key);
                              setApplyError(null);
                              setConflict(false);
                              setApplyDone([]);
                            }}
                          >
                            Review {c.label}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {ordered.length > VISIBLE && (
              <div>
                <button type="button" onClick={() => setShowAll(!showAll)}>
                  {showAll ? "Show top results only" : `Show all ${ordered.length} results`}
                </button>
              </div>
            )}
            {review && (
              <section
                aria-label="Review changes"
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  padding: 12,
                  display: "grid",
                  gap: 8,
                }}
              >
                <h4 style={{ margin: 0 }}>Review changes: {review.label}</h4>
                <p style={{ margin: 0, fontSize: 13 }}>
                  Objective {formatObjective(result.objective, review.objective_value)},{" "}
                  {formatObjectiveDelta(result.objective, review.delta_vs_baseline)} against your
                  saved plan. Applying writes these changes:
                </p>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                  {review.changes.map((c) => (
                    <li key={`${c.target}-${c.summary}`}>{c.summary}</li>
                  ))}
                </ul>
                {review.notes.length > 0 && (
                  <ul
                    style={{
                      margin: 0,
                      paddingLeft: 18,
                      fontSize: 12,
                      color: "var(--text-secondary)",
                    }}
                  >
                    {review.notes.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                )}
                <p style={helpTextStyle}>
                  The allocation rules save against revision {result.priorities_revision}; if they
                  changed since this search, nothing is applied. Steps:{" "}
                  {stepsFor(review)
                    .map((s) => APPLY_STEP_LABELS[s])
                    .join(", ")}
                  .
                </p>
                {applyError && (
                  <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
                    {applyError}
                  </div>
                )}
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  {conflict ? (
                    <button type="button" disabled={applying} onClick={() => void reloadLatest()}>
                      Review latest saved plan
                    </button>
                  ) : (
                    <button type="button" disabled={applying} onClick={() => void apply(review)}>
                      {applying
                        ? "Applying…"
                        : applyDone.length > 0
                          ? "Retry remaining changes"
                          : "Apply to plan"}
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={applying}
                    onClick={() => {
                      setReviewKey(null);
                      setApplyError(null);
                      setConflict(false);
                      setApplyDone([]);
                    }}
                  >
                    Cancel review
                  </button>
                </div>
              </section>
            )}
            <details>
              <summary style={{ cursor: "pointer", fontSize: 13 }}>
                What this search does not do
              </summary>
              <ul
                style={{
                  margin: "6px 0 0",
                  paddingLeft: 18,
                  fontSize: 12,
                  color: "var(--text-secondary)",
                }}
              >
                {result.caveats.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </section>
    </details>
  );
}

export default TaxStrategySearchPanel;
