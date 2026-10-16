import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  binLabel,
  EndingHistogram,
  TrialPathChart,
  TrialSparkline,
} from "@/components/monte_carlo_trial_charts";
import { compactCurrency, fullCurrency, moneyLabel } from "@/utils/format";
import {
  ageInYear,
  endingNetWorthHistogram,
  filterTrials,
  type MilestoneMode,
  type TrialSort,
} from "@/utils/monte_carlo_trials";
import { useChartSize } from "@/utils/use_chart_size";
import type { MonteCarloResult, MonteCarloTrialDetail, TrialSummaries } from "@/types/plan";

export const TRIAL_PAGE_SIZE = 20;

const OUTCOME_BADGES: Record<string, string> = {
  met_targets: "Met targets",
  survived_with_spending_cuts: "Spending cuts",
  survived_below_target: "Below target",
  funding_failure: "Failed",
};

interface Props {
  result: MonteCarloResult & { trials: TrialSummaries };
  /** Replays one trial of this run. Absent when the run reported no seed. */
  loadTrial?: (index: number) => Promise<MonteCarloTrialDetail>;
}

type DetailState =
  | { status: "loading"; index: number }
  | { status: "error"; index: number; message: string }
  | { status: "ready"; index: number; detail: MonteCarloTrialDetail };

function trialLabel(index: number) {
  return `Trial ${(index + 1).toLocaleString()}`;
}

/** Filter, browse and replay individual Monte Carlo trials. */
export default function MonteCarloTrialExplorer({ result, loadTrial }: Props) {
  const trials = result.trials;
  const n = trials.success.length;
  const bins = useMemo(() => endingNetWorthHistogram(trials), [trials]);
  const [binIndex, setBinIndex] = useState<number | null>(null);
  const [outcome, setOutcome] = useState("all");
  const [milestoneId, setMilestoneId] = useState("");
  const [milestoneMode, setMilestoneMode] = useState<MilestoneMode>("any");
  const [milestoneAge, setMilestoneAge] = useState("");
  const [sort, setSort] = useState<TrialSort>("index");
  const [detail, setDetail] = useState<DetailState | null>(null);
  const requestId = useRef(0);
  const { ref: histogramRef, width: histogramWidth } = useChartSize(640, 150);
  const { ref: pathRef, width: pathWidth } = useChartSize(640, 240);

  // A response for a trial that is no longer selected, or after unmount, is ignored.
  useEffect(
    () => () => {
      requestId.current += 1;
    },
    [],
  );

  const milestones = useMemo(
    () =>
      (result.milestone_distributions ?? []).filter(
        (m) => trials.milestone_years[m.id] && m.reached_trials > 0,
      ),
    [result.milestone_distributions, trials],
  );
  const milestone = milestones.find((m) => m.id === milestoneId) ?? milestones[0] ?? null;
  const defaultAge =
    milestone?.median_year != null ? ageInYear(trials, milestone.median_year) : trials.start_age;
  const ageValue = milestoneAge === "" ? defaultAge : Number(milestoneAge);
  const milestoneKey = milestone?.id ?? null;
  const milestoneFilter = useMemo(
    () =>
      milestoneKey !== null && milestoneMode !== "any" && Number.isFinite(ageValue)
        ? { id: milestoneKey, mode: milestoneMode, age: ageValue }
        : null,
    [milestoneKey, milestoneMode, ageValue],
  );

  const showCategories = result.target_success_rate != null;
  const categories = (result.outcome_categories ?? []).filter(
    (c) => c.key !== "funding_failure" && c.count > 0,
  );
  const categoryLabel = (key: string) =>
    result.outcome_categories?.find((c) => c.key === key)?.label ?? OUTCOME_BADGES[key] ?? key;

  const bin = binIndex !== null ? (bins[binIndex] ?? null) : null;
  const matches = useMemo(
    () => filterTrials(trials, outcome, milestoneFilter, bin, sort),
    [trials, outcome, milestoneFilter, bin, sort],
  );
  // Any filter or order change returns to the first page.
  const filterKey = JSON.stringify([outcome, milestoneFilter, binIndex, sort]);
  const [pageState, setPageState] = useState({ key: filterKey, page: 0 });
  const page = pageState.key === filterKey ? pageState.page : 0;
  const setPage = (next: number) => setPageState({ key: filterKey, page: next });
  const pages = Math.max(1, Math.ceil(matches.length / TRIAL_PAGE_SIZE));
  const currentPage = Math.min(page, pages - 1);
  const visible = matches.slice(currentPage * TRIAL_PAGE_SIZE, (currentPage + 1) * TRIAL_PAGE_SIZE);
  const filtered = bin !== null || outcome !== "all" || milestoneFilter !== null;

  const selectTrial = async (index: number) => {
    if (!loadTrial) return;
    const id = ++requestId.current;
    setDetail({ status: "loading", index });
    try {
      const response = await loadTrial(index);
      if (id === requestId.current) setDetail({ status: "ready", index, detail: response });
    } catch (err) {
      if (id === requestId.current) {
        setDetail({
          status: "error",
          index,
          message: err instanceof Error ? err.message : "Could not load this trial.",
        });
      }
    }
  };

  const clearFilters = () => {
    setBinIndex(null);
    setOutcome("all");
    setMilestoneMode("any");
    setMilestoneAge("");
  };

  return (
    <div className="card mc-trial-explorer" id="trial_explorer">
      <div className="card-header" style={{ marginBottom: 8 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 18 }}>Explore individual trials</h3>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--text-tertiary)" }}>
            Ending net worth of each of {n.toLocaleString()} trials, nominal. Select a bar to list
            its trials; select it again to clear.
          </p>
        </div>
      </div>

      <div ref={histogramRef} style={{ width: "100%" }}>
        <EndingHistogram
          bins={bins}
          selected={binIndex}
          width={histogramWidth}
          onSelect={(i) => setBinIndex((current) => (current === i ? null : i))}
        />
      </div>
      <p style={{ margin: "4px 0 12px", fontSize: 12, color: "var(--text-tertiary)" }}>
        <span style={{ color: "var(--chart-blue)" }}>■</span> Funded{" "}
        <span style={{ color: "var(--chart-red)", marginLeft: 8 }}>■</span> Failed
        {bin && <> · Showing {binLabel(bin)}</>}
      </p>

      <div
        className="mc-trial-filters"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 16,
          alignItems: "flex-end",
          marginBottom: 12,
        }}
      >
        <label>
          Outcome
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="all">All trials</option>
            <option value="success">Funded</option>
            <option value="failure">Failed</option>
            {showCategories &&
              categories.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
          </select>
        </label>
        {milestone && (
          <>
            <label>
              Milestone
              <select
                value={milestone.id}
                onChange={(e) => {
                  setMilestoneId(e.target.value);
                  setMilestoneAge("");
                }}
              >
                {milestones.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Timing
              <select
                aria-label="Milestone timing"
                value={milestoneMode}
                onChange={(e) => setMilestoneMode(e.target.value as MilestoneMode)}
              >
                <option value="any">Any timing</option>
                <option value="by">Reached by age</option>
                <option value="after">Reached after age</option>
                <option value="never">Never reached</option>
              </select>
            </label>
            {(milestoneMode === "by" || milestoneMode === "after") && (
              <label>
                Age
                <input
                  aria-label="Milestone age"
                  type="number"
                  min={0}
                  max={130}
                  step={1}
                  style={{ width: 80 }}
                  value={milestoneAge === "" ? String(defaultAge) : milestoneAge}
                  onChange={(e) => setMilestoneAge(e.target.value)}
                />
              </label>
            )}
          </>
        )}
        <label>
          Order
          <select value={sort} onChange={(e) => setSort(e.target.value as TrialSort)}>
            <option value="index">Trial number</option>
            <option value="ending_asc">Ending net worth, lowest first</option>
            <option value="ending_desc">Ending net worth, highest first</option>
          </select>
        </label>
        {filtered && (
          <button type="button" className="btn-secondary" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      <p role="status" aria-live="polite" style={{ margin: "0 0 8px", fontSize: 13 }}>
        {matches.length.toLocaleString()} of {n.toLocaleString()} trials match
        {matches.length > TRIAL_PAGE_SIZE && (
          <>
            {" "}
            · showing {(currentPage * TRIAL_PAGE_SIZE + 1).toLocaleString()}–
            {(currentPage * TRIAL_PAGE_SIZE + visible.length).toLocaleString()}
          </>
        )}
      </p>

      <ul
        className="mc-trial-list"
        aria-label="Trials"
        style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 4 }}
      >
        {visible.map((index) => {
          const ok = trials.success[index];
          const failureYear = trials.failure_year[index];
          const selected = detail?.index === index;
          return (
            <li key={index}>
              <button
                type="button"
                className="mc-trial-row"
                aria-pressed={selected}
                disabled={!loadTrial}
                onClick={() => selectTrial(index)}
                style={{
                  width: "100%",
                  display: "grid",
                  gridTemplateColumns:
                    "minmax(84px, 1fr) minmax(96px, 1fr) minmax(80px, 1fr) minmax(90px, 1fr) 124px",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 10px",
                  textAlign: "left",
                  font: "inherit",
                  fontSize: 13,
                  background: selected ? "var(--brand-primary-light)" : "transparent",
                  border: "1px solid var(--surface-border)",
                  borderRadius: 10,
                  color: "var(--text-primary)",
                  cursor: loadTrial ? "pointer" : "default",
                }}
              >
                <span style={{ fontWeight: 600 }}>{trialLabel(index)}</span>
                <span
                  className="pill"
                  style={{
                    color: ok ? "var(--text-secondary)" : "var(--chart-red)",
                    justifySelf: "start",
                  }}
                >
                  {OUTCOME_BADGES[trials.outcome[index]] ?? categoryLabel(trials.outcome[index])}
                </span>
                <span style={{ fontVariantNumeric: "tabular-nums" }} title="Ending net worth">
                  {compactCurrency(trials.ending_net_worth[index])}
                </span>
                <span style={{ color: "var(--text-tertiary)" }}>
                  {failureYear !== null ? `Failed ${failureYear}` : "No failure"}
                </span>
                <TrialSparkline values={trials.sparklines[index]} failed={!ok} />
              </button>
            </li>
          );
        })}
      </ul>
      {matches.length === 0 && (
        <p style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
          No trials match these filters.
        </p>
      )}
      {pages > 1 && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
          <button
            type="button"
            className="btn-secondary"
            disabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
          >
            Previous
          </button>
          <span style={{ fontSize: 13 }}>
            Page {currentPage + 1} of {pages.toLocaleString()}
          </span>
          <button
            type="button"
            className="btn-secondary"
            disabled={currentPage >= pages - 1}
            onClick={() => setPage(currentPage + 1)}
          >
            Next
          </button>
        </div>
      )}
      {!loadTrial && (
        <p style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
          Run again to open a trial&apos;s full projection.
        </p>
      )}

      <div ref={pathRef} style={{ width: "100%", marginTop: 16 }}>
        {detail && (
          <TrialDetailPanel
            state={detail}
            result={result}
            width={pathWidth}
            onRetry={() => selectTrial(detail.index)}
            categoryLabel={categoryLabel}
          />
        )}
      </div>
    </div>
  );
}

function TrialDetailPanel({
  state,
  result,
  width,
  onRetry,
  categoryLabel,
}: {
  state: DetailState;
  result: MonteCarloResult & { trials: TrialSummaries };
  width: number;
  onRetry: () => void;
  categoryLabel: (key: string) => string;
}) {
  const heading = <h4 style={{ margin: "0 0 8px", fontSize: 16 }}>{trialLabel(state.index)}</h4>;
  if (state.status === "loading") {
    return (
      <section aria-busy="true" aria-label="Trial detail">
        {heading}
        <p role="status">Replaying {trialLabel(state.index).toLowerCase()}…</p>
      </section>
    );
  }
  if (state.status === "error") {
    return (
      <section aria-label="Trial detail">
        {heading}
        <p role="alert" style={{ color: "var(--color-danger)" }}>
          {state.message}
        </p>
        <button type="button" className="btn-secondary" onClick={onRetry}>
          Try again
        </button>
      </section>
    );
  }
  return (
    <TrialDetailReady
      detail={state.detail}
      result={result}
      width={width}
      heading={heading}
      categoryLabel={categoryLabel}
    />
  );
}

function TrialDetailReady({
  detail,
  result,
  width,
  heading,
  categoryLabel,
}: {
  detail: MonteCarloTrialDetail;
  result: MonteCarloResult & { trials: TrialSummaries };
  width: number;
  heading: ReactNode;
  categoryLabel: (key: string) => string;
}) {
  const snapshots = detail.simulation.yearly_snapshots;
  const path = snapshots.map((s) => ({ year: s.year, value: s.net_worth }));
  const curves = result.percentile_curves;
  const median = curves.years.map((year, i) => ({ year, value: curves.p50[i] }));
  const failureYear = detail.failure?.failure_year ?? null;

  const keyYears = useMemo(() => {
    const rows: { label: string; year: number; age: number; value: string }[] = [];
    if (snapshots.length === 0) return rows;
    const peak = snapshots.reduce(
      (best, s) => (s.net_worth > best.net_worth ? s : best),
      snapshots[0],
    );
    rows.push({
      label: "Peak net worth",
      year: peak.year,
      age: peak.age,
      value: fullCurrency(peak.net_worth),
    });
    let worst: { year: number; age: number; change: number } | null = null;
    for (let i = 1; i < snapshots.length; i += 1) {
      const change = snapshots[i].net_worth - snapshots[i - 1].net_worth;
      if (change < 0 && (worst === null || change < worst.change)) {
        worst = { year: snapshots[i].year, age: snapshots[i].age, change };
      }
    }
    if (worst)
      rows.push({
        label: "Largest one-year fall",
        year: worst.year,
        age: worst.age,
        value: fullCurrency(worst.change),
      });
    for (const m of result.milestone_distributions ?? []) {
      const year = detail.milestone_years[m.id];
      if (year != null)
        rows.push({ label: m.name, year, age: ageInYear(result.trials, year), value: "Reached" });
    }
    if (detail.failure) {
      rows.push({
        label: "Failure",
        year: detail.failure.failure_year,
        age: detail.failure.failure_age,
        value: fullCurrency(detail.failure.net_worth_at_failure),
      });
    }
    const last = snapshots[snapshots.length - 1];
    rows.push({
      label: "Final year",
      year: last.year,
      age: last.age,
      value: fullCurrency(last.net_worth),
    });
    return rows.sort((a, b) => a.year - b.year);
  }, [detail, snapshots, result]);

  return (
    <section aria-label="Trial detail">
      {heading}
      <p style={{ margin: "0 0 8px", fontSize: 13 }}>
        <strong>{categoryLabel(detail.outcome)}</strong> · Ending net worth{" "}
        {fullCurrency(detail.ending_net_worth)} · Cash and investments{" "}
        {fullCurrency(detail.ending_liquid)}
        {detail.failure && (
          <>
            {" "}
            · Failed in {detail.failure.failure_year} at age {detail.failure.failure_age}
          </>
        )}
      </p>
      <TrialPathChart path={path} median={median} failureYear={failureYear} width={width} />
      <p style={{ margin: "4px 0 12px", fontSize: 12, color: "var(--text-tertiary)" }}>
        Solid line: this trial&apos;s net worth. Dashed: median of all trials in each year.{" "}
        {moneyLabel("Nominal dollars.")}
      </p>
      <table
        className="mc-trial-key-years"
        style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}
      >
        <caption style={{ textAlign: "left", fontWeight: 600, marginBottom: 4 }}>Key years</caption>
        <thead>
          <tr>
            <th scope="col" style={{ textAlign: "left" }}>
              Event
            </th>
            <th scope="col" style={{ textAlign: "left" }}>
              Year
            </th>
            <th scope="col" style={{ textAlign: "left" }}>
              Age
            </th>
            <th scope="col" style={{ textAlign: "right" }}>
              Amount
            </th>
          </tr>
        </thead>
        <tbody>
          {keyYears.map((row) => (
            <tr key={`${row.label}-${row.year}`}>
              <td>{row.label}</td>
              <td>{row.year}</td>
              <td>{row.age}</td>
              <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                {row.value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
