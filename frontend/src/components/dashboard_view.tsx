import { useCallback, useMemo, useRef, useState } from "react";

import AccountCompositionChart, { type AccountLabel } from "@/components/account_composition_chart";
import ComparisonControls from "@/components/comparison_controls";
import EstateSummaryPanel from "@/components/estate_summary_panel";
import NetWorthChart from "@/components/net_worth_chart";
import SankeyPanel from "@/components/sankey_panel";
import { StickyYearBar } from "@/components/sticky_year_bar";
import TaxOverviewChart from "@/components/tax/tax_overview_chart";
import YearItemized from "@/components/year_itemized";
import YearLedger, { usedTaxLines, usesEarningsTest } from "@/components/year_ledger";
import { useFiEstimateHidden } from "@/stores/fi_estimate_store";
import { useStorage } from "@/storage/context";
import { dollarsOr, fullCurrency } from "@/utils/format";
import { timelineEvents } from "@/utils/timeline_events";
import { EMPTY_PLAN_TEXT, isEmptyProjection } from "@/utils/plan_inputs";
import { useAdjustedTimeline } from "@/utils/use_adjusted_timeline";
import { usePlanAccounts } from "@/utils/use_plan_accounts";

const ENABLE_ESTATE = true;
const NO_ACCOUNTS: AccountLabel[] = [];

/**
 * The projection dashboard. One year, chosen on any chart, drives the
 * ledger beside the hero, the cash-flow diagram and its itemized list, the
 * account composition readout and the tax chart's marker.
 */
export default function DashboardView({
  onEditAllocation,
  onReviewHistory,
}: {
  onEditAllocation: (rank?: number) => void;
  onReviewHistory?: () => void;
}) {
  const { simulation, plan, currencyMode, data, factorAt } = useAdjustedTimeline();
  const { adapter } = useStorage();
  const fiEstimateHidden = useFiEstimateHidden(plan?.id);
  const { accounts, status: accountStatus } = usePlanAccounts(adapter, plan?.id, {
    enabled: !!plan?.id,
  });
  // Labels come only from the current plan's latest read, never a stale or failed one.
  const currentLabels = useMemo(
    () =>
      accountStatus === "ready"
        ? {
            list: accounts.map(({ id, name }): AccountLabel => ({ id, name })),
            names: Object.fromEntries(accounts.map((account) => [account.id, account.name])),
          }
        : null,
    [accountStatus, accounts],
  );
  const accountNames = currentLabels?.names;
  const accountList = currentLabels?.list ?? NO_ACCOUNTS;
  // The composition chart is drawn only once its card is opened.
  const [compositionOpen, setCompositionOpen] = useState(false);
  const events = useMemo(
    () => timelineEvents(plan, simulation, { fiEstimateHidden }),
    [plan, simulation, fiEstimateHidden],
  );

  const years = useMemo(() => data.map((point) => point.year), [data]);
  // One set of tax lines for every year, so an open breakdown keeps its height.
  const taxLines = useMemo(() => usedTaxLines(data), [data]);
  const earningsTest = useMemo(() => usesEarningsTest(data), [data]);
  const [pinnedYear, setPinnedYear] = useState<number | null>(null);
  const [hoverYear, setHoverYear] = useState<number | null>(null);
  const heroChartRef = useRef<HTMLDivElement>(null);

  const selectedYear =
    pinnedYear !== null && years.includes(pinnedYear) ? pinnedYear : (years[0] ?? null);
  const displayYear = hoverYear !== null && years.includes(hoverYear) ? hoverYear : selectedYear;
  const displayIndex = displayYear !== null ? years.indexOf(displayYear) : -1;
  const snapshot = displayIndex >= 0 ? data[displayIndex] : null;
  const previous = displayIndex > 0 ? data[displayIndex - 1] : null;

  const step = useCallback(
    (delta: 1 | -1) => {
      if (selectedYear === null) return;
      const index = years.indexOf(selectedYear) + delta;
      if (index >= 0 && index < years.length) setPinnedYear(years[index]);
    },
    [selectedYear, years],
  );

  const warnings = simulation?.metadata.warnings ?? [];
  const mismatches = warnings.filter((warning) => warning.startsWith("Household mismatch:"));
  const historyWarning = warnings.find((warning) => warning.startsWith("Midyear projection:"));
  const imputedHistory = (simulation?.yearly_snapshots[0]?.warnings ?? []).includes(
    "ytd_imputed_pro_rata",
  );
  const caveats = warnings.filter(
    (warning) => warning !== historyWarning && !mismatches.includes(warning),
  );
  const isEmpty = !simulation || data.length === 0 || !snapshot || selectedYear === null;
  const dollarLabel =
    currencyMode === "nominal"
      ? dollarsOr("Future dollars", "Future (nominal) amounts")
      : dollarsOr(
          `${simulation?.metadata.start_year} dollars`,
          `${simulation?.metadata.start_year} money`,
        );
  // The cash-flow card is nominal, so its itemized list reads the service's snapshot.
  const nominalSnapshot =
    simulation?.yearly_snapshots.find((point) => point.year === selectedYear) ?? null;

  return (
    <div className="page-shell dash-grid">
      {mismatches.map((warning) => (
        <p key={warning} className="card" role="alert">
          {warning}
        </p>
      ))}
      {historyWarning && (
        <aside className="input-review-notice" aria-label="Review earlier tax-year inputs">
          <p>
            {imputedHistory
              ? "Enter earlier income and tax paid to replace the pro-rata estimate."
              : "Enter earlier income and tax paid; missing history is zero."}
          </p>
          <button type="button" className="btn-secondary" onClick={onReviewHistory}>
            Review tax history
          </button>
        </aside>
      )}

      {isEmpty || isEmptyProjection(simulation) ? (
        // An empty plan projects rows of $0, which are not results.
        <section className="card">
          {isEmpty ? (
            <NetWorthChart />
          ) : (
            <p role="status" style={{ margin: 0 }}>
              {EMPTY_PLAN_TEXT}
            </p>
          )}
        </section>
      ) : (
        <>
          <StickyYearBar
            data={data}
            selectedYear={selectedYear}
            anchorRef={heroChartRef}
            onSelectYear={(year) => {
              setPinnedYear(year);
              setHoverYear(null);
            }}
          />
          <section className="card hero-card" aria-label="Net worth and selected year">
            <div className="mobile-year-context" aria-label="Selected year overview">
              <span>
                Dec 31, {snapshot.year} · age {snapshot.age}
              </span>
              <strong>{fullCurrency(snapshot.net_worth)}</strong>
              <span>
                Projected net worth ·{" "}
                {currencyMode === "nominal"
                  ? "nominal $"
                  : `${simulation.metadata.start_year} dollars`}
              </span>
            </div>
            <div className="hero-chart" ref={heroChartRef}>
              <NetWorthChart
                selectedYear={selectedYear}
                hoverYear={hoverYear}
                onSelectYear={setPinnedYear}
                onHoverYear={setHoverYear}
                events={events}
                toolbar={<ComparisonControls />}
              />
            </div>
            <YearLedger
              snapshot={snapshot}
              accountNames={accountNames}
              dollarLabel={dollarLabel}
              previous={previous}
              initial={simulation.initial_snapshot ?? null}
              factor={factorAt(displayIndex)}
              previousFactor={displayIndex > 0 ? factorAt(displayIndex - 1) : 1}
              startDate={simulation.metadata.start_date ?? null}
              yearFraction={simulation.metadata.first_year_fraction ?? 1}
              isFirstYear={displayIndex === 0}
              events={events}
              taxLines={taxLines}
              earningsTest={earningsTest}
              onStep={step}
              canStepBack={years.indexOf(selectedYear) > 0}
              canStepForward={years.indexOf(selectedYear) < years.length - 1}
              preview={hoverYear !== null && hoverYear !== selectedYear}
            />
          </section>

          {caveats.length > 0 && (
            <details className="notice-details card is-inline">
              <summary>Model assumptions and limitations ({caveats.length})</summary>
              <ul>
                {caveats.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </details>
          )}
          <section className="card">
            <SankeyPanel year={selectedYear} onEditAllocation={onEditAllocation} />
            <YearItemized snapshot={nominalSnapshot} />
          </section>

          <details
            className="card dash-fold"
            onToggle={(event) => setCompositionOpen(event.currentTarget.open)}
          >
            <summary>
              <span className="chart-title">Where the money sits</span>
            </summary>
            {compositionOpen && (
              <div className="dash-fold-body">
                <AccountCompositionChart
                  data={data}
                  accounts={accountList}
                  selectedYear={selectedYear}
                  onSelectYear={setPinnedYear}
                  dollarLabel={dollarLabel}
                />
              </div>
            )}
          </details>

          <div className="dash-two">
            <section className="card">
              <TaxOverviewChart snapshots={data} selectedYear={selectedYear} />
            </section>
            {ENABLE_ESTATE && <EstateSummaryPanel />}
          </div>
        </>
      )}
    </div>
  );
}
