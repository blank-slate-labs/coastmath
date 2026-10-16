import { useEffect, useRef, useState } from "react";

import { usePlanStore } from "@/stores/plan_store";
import { useStorage } from "@/storage/context";
import * as api from "@/api/client";
import { priorityPayload } from "../savings_priorities_panel";
import type {
  TaxStrategyCompareResponse,
  TaxStrategyObjective,
  TaxStrategyType,
} from "@/types/plan";
import { ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES } from "@/domain/account_types";
import { ownerLabel, ownerSuffix } from "@/domain/person_labels";
import { compactCurrency, moneyLabel, ratePct } from "@/utils/format";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import MoneyInput from "@/components/money_input";
import {
  STRATEGY_OBJECTIVES,
  formatObjective,
  formatObjectiveDelta,
  isImprovement,
  objectiveOption,
} from "./tax_strategy_objectives";
import { TaxStrategySearchPanel } from "./tax_strategy_search_panel";
import { fillableBracketRates, includesRate } from "@/domain/federal_bracket_rates";
import { helpTextStyle } from "../form_styles";

const LTCG_BRACKETS = [0.0, 0.15];

/**
 * Compares a bounded set of bracket-fill Roth conversion strategies by
 * running the full projection for each. Nothing changes until the user
 * applies a strategy, which adds a conversion rule to the plan's priorities.
 */
export function TaxStrategyOptimizer() {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  const { accounts, status: accountStatus } = usePlanAccounts(adapter, plan?.id);
  const [strategyType, setStrategyType] = useState<TaxStrategyType>("roth_conversion");
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [startMilestone, setStartMilestone] = useState("");
  const [endMilestone, setEndMilestone] = useState("");
  const [brackets, setBrackets] = useState<number[]>([0.12, 0.22, 0.24]);
  const [magiCap, setMagiCap] = useState("");
  const [objective, setObjective] = useState<TaxStrategyObjective>("net_legacy");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TaxStrategyCompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);
  const accountsRevision = usePlanStore((s) => s.accountsRevision);
  const request = useRef(0);

  useEffect(() => {
    request.current += 1;
    setResult(null);
    setRunning(false);
    return () => {
      request.current += 1;
    };
  }, [plan, accountsRevision]);

  useEffect(() => {
    if (accountStatus === "error") setError("Could not load accounts. Reopen tax tools to retry.");
  }, [accountStatus]);

  if (!plan) return null;
  const currentPlan = plan;
  const hasPartner = plan.spouse != null;
  const harvest = strategyType === "gain_harvest";
  const sources = accounts.filter((a) =>
    harvest
      ? a.account_type === "taxable_brokerage"
      : TRADITIONAL_RETIREMENT_TYPES.has(a.account_type),
  );
  const selectedSource = sources.find((a) => a.id === source);
  // The built-in top bracket has no top, so filling it would convert the whole balance.
  const bracketOptions = harvest ? LTCG_BRACKETS : fillableBracketRates(plan.tax_settings);
  // A default ceiling the plan's brackets lack is neither shown nor sent.
  const chosenBrackets = brackets.filter((b) => includesRate(bracketOptions, b));
  const targets = accounts.filter(
    (a) =>
      ROTH_TYPES.has(a.account_type) && (a.owner ?? "self") === (selectedSource?.owner ?? "self"),
  );
  const flat = plan.tax_settings?.mode === "flat";

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setApplied(null);
    setResult(null);
    if (!selectedSource) {
      setError(
        harvest
          ? "Choose a taxable brokerage account with a known cost basis."
          : "Choose a pre-tax source and a Roth destination for the same person.",
      );
      return;
    }
    if (!harvest && !targets.some((a) => a.id === target)) {
      setError("Choose a pre-tax source and a Roth destination for the same person.");
      return;
    }
    if (harvest && selectedSource.cost_basis == null) {
      setError("Enter the brokerage account's cost basis under Accounts before harvesting gains.");
      return;
    }
    if (chosenBrackets.length === 0) {
      setError("Choose at least one bracket to test.");
      return;
    }
    const cap = magiCap.trim() === "" ? null : Number(magiCap);
    if (cap !== null && (!Number.isFinite(cap) || cap <= 0)) {
      setError("MAGI cap must be a positive dollar amount or blank.");
      return;
    }
    setRunning(true);
    const currentRequest = ++request.current;
    try {
      const compared = await api.compareTaxStrategies(currentPlan.id, {
        strategy_type: strategyType,
        source_account_id: source,
        target_account_id: harvest ? null : target,
        bracket_ceilings: [...chosenBrackets].sort((a, b) => a - b),
        magi_cap: cap,
        start_milestone_id: startMilestone || null,
        end_milestone_id: endMilestone || null,
        objective,
      });
      if (request.current === currentRequest) setResult(compared);
    } catch {
      if (request.current === currentRequest)
        setError(
          "Could not compare strategies. Check the plan simulates successfully and try again.",
        );
    } finally {
      if (request.current === currentRequest) setRunning(false);
    }
  }

  async function apply(key: string) {
    if (!result) return;
    const candidate = result.candidates.find((c) => c.key === key);
    if (!candidate || key === "baseline") return;
    const rate = Number(key.replace("fill_", "")) / 10000;
    setApplying(true);
    setError(null);
    try {
      const items = priorityPayload(currentPlan.priorities);
      items.push({
        priority_rank: items.length + 1,
        priority_type: harvest ? "gain_harvest" : "roth_conversion",
        source_account_id: source,
        target_account_id: harvest ? null : target,
        conversion_mode: "fill_bracket",
        bracket_ceiling_rate: rate,
        magi_cap: magiCap.trim() === "" ? null : Number(magiCap),
        start_milestone_id: startMilestone || null,
        end_milestone_id: endMilestone || null,
        max_annual_amount: null,
      });
      await adapter.updatePriorities(currentPlan.id, items, currentPlan.priorities_revision ?? 0);
      if (usePlanStore.getState().plan?.id === currentPlan.id)
        await usePlanStore.getState().loadPlan(currentPlan.id);
      setApplied(candidate.label);
    } catch (err) {
      setError(
        `Could not apply the strategy. ${err instanceof Error ? err.message : ""} Reload the latest plan and compare again.`,
      );
    } finally {
      setApplying(false);
    }
  }

  return (
    <section style={{ display: "grid", gap: 12 }} data-sample-editor>
      <h3 style={{ margin: 0 }}>Tax strategy comparison</h3>
      <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
        {harvest
          ? "Annual gain harvesting up to the selected bracket. No cash moves."
          : "Annual conversions up to the selected bracket."}{" "}
        Compares full-plan scenarios. Nothing changes until applied.
      </p>
      {flat && (
        <p role="alert" style={{ margin: 0, fontSize: 13, color: "var(--color-danger)" }}>
          This plan uses flat tax rates, so bracket-fill conversions have no headroom to fill.
        </p>
      )}
      <form
        onSubmit={run}
        onChange={() => {
          request.current += 1;
          setResult(null);
          setApplied(null);
        }}
        style={{ display: "grid", gap: 10 }}
      >
        <fieldset
          disabled={running || applying || flat}
          style={{ border: 0, padding: 0, minWidth: 0, display: "grid", gap: 10 }}
        >
          <label>
            Strategy
            <select
              value={strategyType}
              onChange={(e) => {
                const next = e.target.value as TaxStrategyType;
                setStrategyType(next);
                setSource("");
                setTarget("");
                setBrackets(next === "gain_harvest" ? [0.0, 0.15] : [0.12, 0.22, 0.24]);
                setResult(null);
              }}
            >
              <option value="roth_conversion">Roth conversions to fill an income bracket</option>
              <option value="gain_harvest">
                Capital-gain harvesting to fill a capital-gains bracket
              </option>
            </select>
          </label>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: 10,
            }}
          >
            <label>
              {harvest ? "Taxable account" : "Pre-tax source"}
              <select
                required
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  setTarget("");
                }}
              >
                <option value="">Choose account</option>
                {sources.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {ownerSuffix(a.owner, hasPartner)}
                  </option>
                ))}
              </select>
            </label>
            {!harvest && (
              <label>
                Roth destination
                <select
                  required
                  disabled={!selectedSource || !targets.length}
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                >
                  <option value="">
                    {!selectedSource
                      ? "Choose a source first"
                      : !targets.length
                        ? "No eligible Roth account"
                        : "Choose account"}
                  </option>
                  {selectedSource &&
                    targets.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                        {ownerSuffix(a.owner, hasPartner)}
                      </option>
                    ))}
                </select>
              </label>
            )}
            {!harvest && !selectedSource && (
              <p style={helpTextStyle}>Source and Roth destination must have the same owner.</p>
            )}
            {!harvest && selectedSource && targets.some((a) => a.id === target) && (
              <p style={helpTextStyle}>
                Converting from {selectedSource.name} to{" "}
                {targets.find((a) => a.id === target)?.name}
                {ownerSuffix(selectedSource.owner, hasPartner)}.
              </p>
            )}
            {!harvest && selectedSource && !targets.length && (
              <p role="status" style={helpTextStyle}>
                No Roth account belongs to the {ownerLabel(selectedSource.owner).toLowerCase()}. Add
                a Roth account for the same person under Accounts in the plan builder.
              </p>
            )}
            <label>
              Convert from
              <select value={startMilestone} onChange={(e) => setStartMilestone(e.target.value)}>
                <option value="">Start of plan</option>
                {plan.milestones.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Convert until
              <select value={endMilestone} onChange={(e) => setEndMilestone(e.target.value)}>
                <option value="">Funds are exhausted</option>
                {plan.milestones.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {moneyLabel("MAGI cap — modified adjusted gross income ($ today, optional)")}
              <MoneyInput
                min={0}
                step={1000}
                value={magiCap}
                onValueChange={setMagiCap}
                placeholder="e.g. ACA or IRMAA threshold"
              />
            </label>
            <label>
              Objective
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
          </div>
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend style={{ fontSize: 13 }}>
              {harvest ? "Capital-gains bracket ceilings to test" : "Bracket ceilings to test"}
            </legend>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {bracketOptions.map((b) => (
                <label
                  key={b}
                  style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}
                >
                  <input
                    type="checkbox"
                    checked={includesRate(chosenBrackets, b)}
                    onChange={(e) =>
                      setBrackets(
                        e.target.checked
                          ? [...chosenBrackets, b]
                          : chosenBrackets.filter((x) => x !== b),
                      )
                    }
                  />
                  Fill to {Math.round(b * 100)}%
                </label>
              ))}
            </div>
            <span style={helpTextStyle}>
              {harvest
                ? "Fills the capital-gains bracket headroom measured before the year's withdrawals."
                : "Fills the ordinary-income bracket headroom measured before the year's withdrawals."}
            </span>
          </fieldset>
          <div>
            <button type="submit">
              {running ? "Simulating candidates…" : "Compare strategies"}
            </button>
          </div>
        </fieldset>
      </form>
      {error && (
        <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
          {error}
        </div>
      )}
      {applied && (
        <p role="status" style={{ margin: 0, fontSize: 13 }}>
          Applied “{applied}” as a {harvest ? "gain-harvest" : "conversion"} rule.
          {!harvest && " Remove it under Conversion scenarios."}
        </p>
      )}

      {result && (
        <div style={{ display: "grid", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 13 }}>
            Objective: <strong>{result.objective_description}</strong>.
            {objectiveOption(result.objective).discounted &&
              result.pre_tax_discount_rate != null && (
                <>
                  {" "}
                  Pre-tax balances net of <strong>
                    {ratePct(result.pre_tax_discount_rate)}
                  </strong>{" "}
                  income tax.
                </>
              )}{" "}
            Deltas are against the baseline without the new rule.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 13 }} aria-label="Strategy comparison">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Strategy</th>
                  <th style={{ textAlign: "right" }}>Objective</th>
                  <th style={{ textAlign: "right" }}>Δ vs baseline</th>
                  <th style={{ textAlign: "right" }}>{harvest ? "Harvested" : "Converted"}</th>
                  <th style={{ textAlign: "right" }}>Lifetime taxes</th>
                  <th style={{ textAlign: "right" }}>Health costs</th>
                  <th style={{ textAlign: "right" }}>Net estate</th>
                  <th style={{ textAlign: "right" }}>IRMAA yrs</th>
                  <th style={{ textAlign: "right" }}>Credit lost yrs</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {result.candidates.map((c) => (
                  <tr
                    key={c.key}
                    style={{ fontWeight: c.is_best ? 600 : 400, opacity: c.success ? 1 : 0.7 }}
                  >
                    <td>
                      {c.label}
                      {c.is_best ? " · best tested" : ""}
                      {!c.success ? ` · fails ${c.failure_year}` : ""}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {formatObjective(result.objective, c.objective_value)}
                    </td>
                    <td
                      style={{
                        textAlign: "right",
                        color:
                          c.key === "baseline"
                            ? "inherit"
                            : c.delta_vs_baseline === 0 ||
                                isImprovement(result.objective, c.delta_vs_baseline)
                              ? "var(--chart-green)"
                              : "var(--chart-red)",
                      }}
                    >
                      {c.key === "baseline"
                        ? "—"
                        : formatObjectiveDelta(result.objective, c.delta_vs_baseline)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {c.key === "baseline"
                        ? "—"
                        : `${compactCurrency(c.total_converted)} over ${c.conversion_years} yr${c.conversion_years === 1 ? "" : "s"}`}
                    </td>
                    <td style={{ textAlign: "right" }}>{compactCurrency(c.lifetime_taxes)}</td>
                    <td style={{ textAlign: "right" }}>{compactCurrency(c.lifetime_healthcare)}</td>
                    <td style={{ textAlign: "right" }}>{compactCurrency(c.net_legacy)}</td>
                    <td style={{ textAlign: "right" }}>{c.irmaa_years}</td>
                    <td style={{ textAlign: "right" }}>{c.aca_credit_lost_years}</td>
                    <td>
                      {c.key !== "baseline" && c.total_converted > 0 && (
                        <button type="button" disabled={applying} onClick={() => void apply(c.key)}>
                          {applying ? "Applying…" : "Apply"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.candidates.some((c) => c.notes.length > 0) && (
            <ul
              style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--text-secondary)" }}
            >
              {result.candidates.flatMap((c) =>
                c.notes.map((n) => (
                  <li key={`${c.key}-${n}`}>
                    {c.label}: {n}
                  </li>
                )),
              )}
            </ul>
          )}
          <details>
            <summary style={{ cursor: "pointer", fontSize: 13 }}>
              What this comparison does not do
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
      <TaxStrategySearchPanel accounts={accounts} />
    </section>
  );
}

export default TaxStrategyOptimizer;
