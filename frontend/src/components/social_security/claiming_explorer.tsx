import { useEffect, useMemo, useRef, useState } from "react";

import { ChartHeader, ChartLegend, ChartTable, SegmentedControl } from "@/components/chart_chrome";
import SaveErrorNotice from "@/components/save_error_notice";
import { ownerLabel, ownerPossessive } from "@/domain/person_labels";
import type { PlanSectionKey } from "@/pages/plan_setup";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import type {
  ClaimingExplorerResponse,
  IncomeCreate,
  ClaimingNotAdjustableReason,
  ClaimingOwner,
  ClaimingPerson,
  ClaimingRun,
} from "@/types/plan";
import { fullCurrency, moneyLabel, ratePct, signedCompactCurrency } from "@/utils/format";
import { useAdjustedTimeline } from "@/utils/use_adjusted_timeline";
import { useChartSize } from "@/utils/use_chart_size";
import {
  ClaimingColumns,
  ClaimingHeatmap,
  CumulativeBenefitsChart,
  claimingChartHeight,
  type ClaimingCell,
} from "./claiming_charts";

type Metric = "end_net_worth" | "lifetime_social_security";

const METRICS: { value: Metric; label: string }[] = [
  { value: "end_net_worth", label: "End net worth, after tax" },
  { value: "lifetime_social_security", label: "Lifetime Social Security" },
];

const REASONS: Record<ClaimingNotAdjustableReason, string> = {
  no_benefit: "no Social Security benefit",
  multiple_benefits: "more than one Social Security benefit",
  already_claimed: "benefits already started",
  unresolved_claim_date: "claim date depends on a milestone without a fixed date",
  missing_birth_year: "no birth year",
  no_candidate_ages: "no claim age from 62 to 70 is still ahead",
};

const name = (owner: ClaimingOwner) => ownerLabel(owner);
const keyOf = (ages: Partial<Record<ClaimingOwner, number>>, owners: ClaimingOwner[]) =>
  owners.map((owner) => ages[owner]).join("|");
const sameAge = (a: number | undefined, b: number | null | undefined) =>
  a != null && b != null && Math.abs(a - b) < 1e-9;
const ageText = (age: number | null | undefined) => {
  if (age == null) return "—";
  const years = Math.floor(age + 1e-9);
  const months = Math.round((age - years) * 12);
  return months ? `${years} y ${months} m` : String(years);
};

/**
 * Compares Social Security claiming ages against the whole saved plan, as the
 * server ran them. Values follow the currency mode; the selected ages can be
 * saved to the plan's income streams.
 */
export default function ClaimingExplorer({
  onEditSection,
}: {
  onEditSection: (key: PlanSectionKey) => void;
}) {
  const plan = usePlanStore((s) => s.plan);
  const isSimulating = usePlanStore((s) => s.isSimulating);
  const updateIncome = usePlanStore((s) => s.updateIncome);
  const { adapter } = useStorage();
  const { simulation, currencyMode, factorAt } = useAdjustedTimeline();
  const [result, setResult] = useState<ClaimingExplorerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric>("end_net_worth");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // The last applied change, with the saved values it replaced, so it can be undone.
  const [applied, setApplied] = useState<{
    summary: string;
    restore: { incomeId: string; changes: Partial<IncomeCreate> }[];
  } | null>(null);
  const request = useRef(0);
  const requestedFor = useRef<object | null>(null);
  const planId = plan?.id ?? null;
  const { ref: chartRef, width } = useChartSize(560, 300);

  // A new plan starts empty; a refreshed projection keeps the old result until the new one lands.
  useEffect(() => {
    request.current += 1;
    requestedFor.current = null;
    setResult(null);
    setError(null);
    setSelectedKey(null);
    setSaveError(null);
    setLoading(false);
    setApplied(null);
  }, [planId]);

  useEffect(() => {
    if (!planId || !simulation || requestedFor.current === simulation) return;
    requestedFor.current = simulation;
    const current = ++request.current;
    setLoading(true);
    setError(null);
    adapter
      .exploreClaimingAges(planId)
      .then((response) => {
        if (request.current !== current || usePlanStore.getState().plan?.id !== planId) return;
        setResult(response);
      })
      .catch(() => {
        if (request.current === current)
          setError("Could not compare claiming ages. Try again after the projection updates.");
      })
      .finally(() => {
        if (request.current === current) setLoading(false);
      });
  }, [adapter, planId, simulation]);

  const view = useMemo(() => {
    if (!result?.current) return null;
    const persons = result.persons.filter((p) => p.adjustable);
    const owners = persons.map((p) => p.owner);
    const last = result.years.length - 1;
    const today = currencyMode !== "nominal";
    const cumulative = (run: ClaimingRun) => {
      let total = 0;
      return run.social_security_by_year.map((amount, i) => (total += amount / factorAt(i)));
    };
    const lifetime = (run: ClaimingRun) =>
      today ? (cumulative(run)[last] ?? 0) : run.lifetime_social_security;
    const endNetWorth = (run: ClaimingRun) => run.end_net_worth_after_tax / factorAt(last);
    const current = result.current;
    const change = (run: ClaimingRun, which: Metric) =>
      which === "end_net_worth"
        ? run.end_net_worth_after_tax_change / factorAt(last)
        : today
          ? lifetime(run) - lifetime(current)
          : run.lifetime_social_security_change;
    return { persons, owners, last, cumulative, lifetime, endNetWorth, change, current };
  }, [result, currencyMode, factorAt]);

  if (!plan) return null;
  const busy = loading || (isSimulating && !result);

  if (!result) {
    // People the grid will likely vary, from the saved benefits; the server decides.
    const people = new Set(
      (plan.income_streams ?? [])
        .filter((income) => income.is_social_security && income.is_active)
        .map((income) => income.owner ?? "self"),
    ).size;
    return (
      <section className="card" style={{ display: "grid", gap: 14 }} aria-busy={busy}>
        <ChartHeader title="Social Security claiming ages" />
        {busy && (
          <p role="status" style={{ margin: 0 }}>
            Comparing claiming ages…
          </p>
        )}
        {busy && people > 0 && (
          // Reserves the grid's space so the page does not jump when results land.
          <div
            ref={chartRef}
            data-testid="claiming-placeholder"
            aria-hidden="true"
            style={{
              minWidth: 0,
              height: claimingChartHeight(people > 1 ? 2 : 1, width),
              borderRadius: 8,
              background: "var(--surface-sunken)",
            }}
          />
        )}
        {error && (
          <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>
            {error}
          </p>
        )}
      </section>
    );
  }

  const withheld = result.persons.filter(
    (p) => p.earnings_test_withholds && p.full_retirement_age != null,
  );
  const withheldLines = withheld.map((p) => (
    <p key={p.owner} style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
      {ownerPossessive(p.owner)} earnings withhold benefits before {ageText(p.full_retirement_age)}.
    </p>
  ));
  const blocked = result.persons.filter((p) => !p.adjustable);
  const blockedLines = blocked.length > 0 && (
    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
      {blocked.map((p: ClaimingPerson) => (
        <li
          key={p.owner}
          style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}
        >
          <span>
            {name(p.owner)}: {REASONS[p.reason ?? "no_benefit"]}.
          </span>
          <button
            type="button"
            className="btn-ghost"
            data-sample-view
            onClick={() => onEditSection("income")}
          >
            Edit income
          </button>
        </li>
      ))}
    </ul>
  );

  if (!view) {
    const none = result.persons.every((p) => p.reason === "no_benefit");
    return (
      <section className="card" style={{ display: "grid", gap: 10 }}>
        <ChartHeader title="Social Security claiming ages" />
        {none ? (
          <p style={{ margin: 0 }}>No Social Security benefits in this plan.</p>
        ) : (
          blockedLines
        )}
        {error && (
          <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>
            {error}
          </p>
        )}
      </section>
    );
  }

  const { persons, owners, cumulative, lifetime, endNetWorth, change, current } = view;
  const runs = result.runs;
  const best = result.best_index != null ? runs[result.best_index] : runs[0];
  const bestKey = keyOf(best.claim_ages, owners);
  const selected = runs.find((r) => keyOf(r.claim_ages, owners) === selectedKey) ?? best;
  const selectedRunKey = keyOf(selected.claim_ages, owners);
  const metricLabel = METRICS.find((m) => m.value === metric)!.label;
  const cells: ClaimingCell[] = runs.map((run) => {
    const key = keyOf(run.claim_ages, owners);
    return {
      key,
      ages: owners.map((o) => run.claim_ages[o]!),
      value: change(run, metric),
      best: key === bestKey,
    };
  });
  const isCurrent = owners.every((owner, i) =>
    sameAge(selected.claim_ages[owner], persons[i].current_claim_age),
  );
  const basis = currencyMode === "nominal" ? "Nominal dollars." : "Today’s dollars.";

  async function apply() {
    if (!plan) return;
    setSaving(true);
    setSaveError(null);
    setApplied(null);
    const pending = persons.filter(
      (p) => !sameAge(selected.claim_ages[p.owner], p.current_claim_age),
    );
    const restore: { incomeId: string; changes: Partial<IncomeCreate> }[] = [];
    for (const person of pending) {
      const patch = result!.patches.find(
        (x) => x.owner === person.owner && x.claiming_age === selected.claim_ages[person.owner],
      );
      if (!patch) continue;
      const before = plan.income_streams?.find((income) => income.id === patch.income_id);
      const saved = await updateIncome(plan.id, patch.income_id, patch.changes);
      if (!saved) {
        const key = `put /plans/${plan.id}/incomes/${patch.income_id}`;
        setSaveError(
          useSaveStore.getState().failures[key]?.message ??
            usePlanStore.getState().error ??
            `Could not save the ${name(person.owner).toLowerCase()}’s claiming age.`,
        );
        break;
      }
      if (before)
        restore.push({
          incomeId: before.id,
          changes: {
            claiming_age: before.claiming_age ?? null,
            start_milestone_id: before.start_milestone_id,
            start_month: before.start_month,
            ...("annual_amount" in patch.changes ? { annual_amount: before.annual_amount } : {}),
          },
        });
    }
    if (restore.length) {
      const ages = (pick: (owner: ClaimingOwner) => number | null | undefined) =>
        owners.map((owner) => ageText(pick(owner))).join(" / ");
      setApplied({
        summary: `Claiming ${owners.length > 1 ? "ages" : "age"} ${ages((o) => persons.find((p) => p.owner === o)?.current_claim_age)} → ${ages((o) => selected.claim_ages[o])}.`,
        restore,
      });
    }
    setSaving(false);
  }

  async function undo() {
    if (!plan || !applied) return;
    setSaving(true);
    setSaveError(null);
    for (const { incomeId, changes } of applied.restore) {
      if (!(await updateIncome(plan.id, incomeId, changes))) {
        setSaveError(
          useSaveStore.getState().failures[`put /plans/${plan.id}/incomes/${incomeId}`]?.message ??
            "Could not restore the previous claiming ages.",
        );
        setSaving(false);
        return;
      }
    }
    setApplied(null);
    setSaving(false);
  }

  const series = [
    {
      id: "current",
      label: "Current plan",
      color: "var(--viz-context)",
      dashed: true,
      values: cumulative(current),
    },
    ...(selectedRunKey !== bestKey
      ? [{ id: "selected", label: "Selected", color: "var(--viz-1)", values: cumulative(selected) }]
      : []),
    {
      id: "best",
      label: selectedRunKey === bestKey ? "Selected (highest)" : "Highest",
      color: "var(--viz-3)",
      values: cumulative(best),
    },
  ];
  const changeColor = (value: number) => ({
    color: value >= 0 ? "var(--color-success)" : "var(--color-danger)",
  });

  return (
    <section className="card" style={{ display: "grid", gap: 14 }} aria-busy={busy}>
      <ChartHeader title="Social Security claiming ages" subtitle={busy ? "Updating…" : undefined}>
        <SegmentedControl
          value={metric}
          options={METRICS}
          onChange={setMetric}
          ariaLabel="Color by"
        />
      </ChartHeader>
      {blockedLines}
      {withheldLines}
      <div ref={chartRef} style={{ minWidth: 0 }}>
        <ChartLegend
          entries={[
            { label: "Below current plan", color: "var(--viz-2)", kind: "swatch" },
            { label: "Above current plan", color: "var(--viz-1)", kind: "swatch" },
            { label: "Current plan", color: "var(--text-primary)", kind: "dashed" },
            { label: "Highest after-tax end net worth", color: "var(--text-primary)", kind: "dot" },
          ]}
        />
        {owners.length === 2 ? (
          <ClaimingHeatmap
            rowAges={persons[0].candidate_ages}
            columnAges={persons[1].candidate_ages}
            cells={cells}
            current={[persons[0].current_claim_age!, persons[1].current_claim_age!]}
            selected={selectedRunKey}
            onSelect={setSelectedKey}
            names={[name(owners[0]), name(owners[1])]}
            metric={metricLabel}
            width={width}
          />
        ) : (
          <ClaimingColumns
            cells={cells}
            current={persons[0].current_claim_age!}
            selected={selectedRunKey}
            onSelect={setSelectedKey}
            name={name(owners[0])}
            metric={metricLabel}
            width={Math.max(280, width)}
          />
        )}
        <ChartTable
          caption="Claiming-age comparison"
          note={`${moneyLabel(basis)} Pre-tax balances net of ${ratePct(result.pre_tax_discount_rate)} income tax.`}
          columns={[
            ...owners.map((o) => ({ key: o, label: name(o), numeric: true })),
            { key: "enw", label: "End net worth, after tax", numeric: true },
            { key: "enw_change", label: "Change", numeric: true },
            { key: "ss", label: "Lifetime Social Security", numeric: true },
            { key: "ss_change", label: "Change", numeric: true },
          ]}
          rows={runs.map((run) => ({
            ...Object.fromEntries(owners.map((o) => [o, ageText(run.claim_ages[o])])),
            enw: fullCurrency(endNetWorth(run)),
            enw_change: signedCompactCurrency(change(run, "end_net_worth")),
            ss: fullCurrency(lifetime(run)),
            ss_change: signedCompactCurrency(change(run, "lifetime_social_security")),
          }))}
        />
      </div>

      <div aria-live="polite" style={{ display: "grid", gap: 8 }}>
        <dl
          className="claiming-readout"
          style={{ display: "flex", flexWrap: "wrap", gap: "8px 20px", margin: 0, fontSize: 13 }}
        >
          {owners.map((owner) => (
            <div key={owner}>
              <dt style={{ color: "var(--text-secondary)" }}>{name(owner)}</dt>
              <dd style={{ margin: 0, fontWeight: 600 }}>
                {ageText(selected.claim_ages[owner])} ·{" "}
                {fullCurrency(selected.first_year_benefits[owner] ?? 0)}/yr
              </dd>
            </div>
          ))}
          <div>
            <dt style={{ color: "var(--text-secondary)" }}>End net worth, after tax</dt>
            <dd style={{ margin: 0 }}>
              {fullCurrency(endNetWorth(selected))}{" "}
              <span style={changeColor(change(selected, "end_net_worth"))}>
                {signedCompactCurrency(change(selected, "end_net_worth"))}
              </span>
            </dd>
          </div>
          <div>
            <dt style={{ color: "var(--text-secondary)" }}>Lifetime Social Security</dt>
            <dd style={{ margin: 0 }}>
              {fullCurrency(lifetime(selected))}{" "}
              <span style={changeColor(change(selected, "lifetime_social_security"))}>
                {signedCompactCurrency(change(selected, "lifetime_social_security"))}
              </span>
            </dd>
          </div>
          {!selected.success && (
            <div>
              <dt style={{ color: "var(--text-secondary)" }}>Plan</dt>
              <dd style={{ margin: 0, color: "var(--color-danger)" }}>
                Fails{selected.failure_year ? ` in ${selected.failure_year}` : ""}
              </dd>
            </div>
          )}
        </dl>
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)" }}>
          {moneyLabel("Benefits per year in today’s dollars at claim.")}
        </p>
        {!isCurrent && (
          <div>
            <button
              type="button"
              className="btn-primary"
              data-sample-edit
              disabled={saving || busy || isSimulating}
              onClick={() => void apply()}
            >
              {saving ? "Saving…" : "Use these ages"}
            </button>
          </div>
        )}
        {applied && (
          <p
            role="status"
            style={{ margin: 0, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}
          >
            {applied.summary}
            <button
              type="button"
              className="btn-quiet"
              data-sample-edit
              disabled={saving || busy || isSimulating}
              onClick={() => void undo()}
            >
              Undo
            </button>
          </p>
        )}
        <SaveErrorNotice message={saveError} />
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        <h4 style={{ margin: 0, fontSize: 14 }}>Cumulative Social Security</h4>
        <CumulativeBenefitsChart
          years={result.years}
          series={series}
          width={Math.max(280, width)}
          label="Household Social Security received to date by year"
        />
        <ChartTable
          caption="Cumulative household Social Security by year"
          note={moneyLabel(basis)}
          columns={[
            { key: "year", label: "Year" },
            ...series.map((s) => ({ key: s.id, label: s.label, numeric: true })),
          ]}
          rows={result.years.map((year, i) => ({
            year,
            ...Object.fromEntries(series.map((s) => [s.id, fullCurrency(s.values[i])])),
          }))}
        />
      </div>
      {error && (
        <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>
          {error}
        </p>
      )}
    </section>
  );
}
