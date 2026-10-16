import { useCallback, useEffect, useState } from "react";
import { ledger } from "@/api/ledger";
import type { LedgerMonths } from "@/api/ledger";
import { apiErrorCode, spendingFeeds, spendingModels } from "@/api/spending_models";
import type {
  FuturePhases,
  IncomeMode,
  SpendingCompareResponse,
  SpendingFeedState,
  SpendingVariant,
} from "@/api/spending_models";
import { SegmentedControl } from "@/components/chart_chrome";
import { money, muted, row, stack } from "@/components/ledger/ledger_format";
import { errorMessage } from "@/utils/error_message";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import CategoryDifferences from "./category_differences";
import CompareChart from "./compare_chart";
import { MAX_COMBINED, MAX_SEPARATE, monthsText } from "./month_format";
import MonthStrip from "./month_strip";
import OutcomeTable from "./outcome_table";

const MONTE_CARLO_TRIALS = 250;

interface Loaded {
  months: LedgerMonths;
  labels: Record<string, string>;
  feed: SpendingFeedState;
}
interface Preview {
  response: SpendingCompareResponse;
  variants: SpendingVariant[];
}

/** Project the plan with chosen months' spending, compare the outcomes and apply one. */
export default function MonthCompareTab({
  onOpenTransactions,
}: {
  onOpenTransactions: () => void;
}) {
  const plan = usePlanStore((s) => s.plan);
  const mode = usePlanStore((s) => s.currencyMode);
  const setMode = usePlanStore((s) => s.setCurrencyMode);
  const { sample } = useStorage();
  const planId = plan?.id;
  const currency = plan?.currency ?? "USD";
  const [data, setData] = useState<Loaded | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [combine, setCombine] = useState(false);
  const [futurePhases, setFuturePhases] = useState<FuturePhases>("scale");
  const [income, setIncome] = useState<IncomeMode>("as_planned");
  const [monteCarlo, setMonteCarlo] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!planId) return;
    const [months, categories, feed] = await Promise.all([
      ledger.months({ plan_id: planId }),
      ledger.categories(),
      spendingFeeds.get(planId),
    ]);
    setData({ months, feed, labels: Object.fromEntries(categories.map((c) => [c.id, c.label])) });
  }, [planId]);

  useEffect(() => {
    if (sample) return;
    setData(null);
    setSelected([]);
    setPreview(null);
    setConfirming(null);
    setError(null);
    setNotice(null);
    void load().catch((e) => setError(errorMessage(e)));
  }, [load, sample]);

  const variants = (): SpendingVariant[] =>
    combine
      ? [{ kind: "months", months: [...selected].sort() }]
      : [...selected].sort().map((month) => ({ kind: "months", months: [month] }));

  const runCompare = useCallback(
    async (next: SpendingVariant[]) => {
      if (!planId) return;
      const response = await spendingModels.compare(planId, {
        variants: next,
        future_phases: futurePhases,
        income,
        monte_carlo_trials: monteCarlo ? MONTE_CARLO_TRIALS : 0,
      });
      setPreview({ response, variants: next });
    },
    [planId, futurePhases, income, monteCarlo],
  );

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function reloadPlan() {
    if (!planId) return;
    usePlanStore.setState({ simulation: null });
    await usePlanStore.getState().loadPlan(planId);
  }

  async function apply(index: number) {
    if (!planId || !preview) return;
    const variant = preview.variants[index];
    const label = preview.response.variants[index].label;
    setConfirming(null);
    await run(async () => {
      try {
        await spendingModels.apply(planId, {
          variant,
          future_phases: futurePhases,
          expected_fingerprint: preview.response.fingerprint,
        });
      } catch (e) {
        if (apiErrorCode(e) !== "CONFLICT") throw e;
        // The plan changed after the preview: refresh it and keep the selection for review.
        await runCompare(preview.variants);
        setNotice(
          "The plan changed after this preview. Review the refreshed preview, then apply again.",
        );
        return;
      }
      await reloadPlan();
      await load();
      await runCompare(preview.variants);
      setNotice(`Applied ${label}.`);
    });
  }

  function toggle(month: string) {
    setPreview(null);
    setConfirming(null);
    setSelected((current) =>
      current.includes(month) ? current.filter((m) => m !== month) : [...current, month],
    );
  }

  if (sample || !planId) return null;
  if (!data)
    return (
      <div className="page-shell">
        {error ? <p role="alert">{error}</p> : <p role="status">Loading months…</p>}
      </div>
    );

  const complete = data.months.months.filter((m) => m.complete);
  if (complete.length === 0)
    return (
      <div className="page-shell">
        <section className="card" style={stack} aria-label="Compare months">
          <p style={{ margin: 0 }}>No complete months yet.</p>
          <div>
            <button type="button" onClick={onOpenTransactions}>
              Open Transactions
            </button>
          </div>
        </section>
      </div>
    );

  const limit = combine ? MAX_COMBINED : MAX_SEPARATE;
  const { feed } = data;
  const response = preview?.response;
  const monthOutcomes =
    response?.variants.filter((v) => v.kind === "months" && v.by_category) ?? [];
  const pending = confirming != null && response ? response.variants[confirming] : null;

  return (
    <div className="page-shell">
      <section className="card" style={stack} aria-label="Compare months">
        {feed.active && (
          <div style={row}>
            <span>
              Spending from transactions:{" "}
              <strong>
                {feed.basis === "months" ? monthsText(feed.basis_months) : "Recent months"}
              </strong>
            </span>
            {feed.basis === "months" && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await spendingFeeds.put(planId, {
                      source_ids: feed.source_ids,
                      basis: "trailing",
                    });
                    setPreview(null);
                    await reloadPlan();
                    await load();
                  })
                }
              >
                Use recent months
              </button>
            )}
          </div>
        )}
        {feed.error && <p role="alert">{feed.error}</p>}
        <MonthStrip
          months={data.months.months}
          sources={data.months.sources}
          currency={data.months.currency}
          selected={selected}
          full={selected.length >= limit}
          onToggle={toggle}
        />
        <div style={{ ...row, gap: 16 }}>
          <SegmentedControl<"separate" | "combined">
            ariaLabel="Selected months"
            value={combine ? "combined" : "separate"}
            onChange={(value) => {
              setPreview(null);
              setCombine(value === "combined");
              if (value === "separate") setSelected((current) => current.slice(0, MAX_SEPARATE));
            }}
            options={[
              { value: "separate", label: "Each month" },
              { value: "combined", label: "Average them" },
            ]}
          />
          <span style={row}>
            Later phases
            <SegmentedControl<FuturePhases>
              ariaLabel="Later phases"
              value={futurePhases}
              onChange={(value) => {
                setPreview(null);
                setFuturePhases(value);
              }}
              options={[
                { value: "scale", label: "Scale" },
                { value: "as_planned", label: "As planned" },
              ]}
            />
          </span>
          <span style={row}>
            Take-home
            <SegmentedControl<IncomeMode>
              ariaLabel="Take-home"
              value={income}
              onChange={(value) => {
                setPreview(null);
                setIncome(value);
              }}
              options={[
                { value: "as_planned", label: "As planned" },
                { value: "scale_to_take_home", label: "Scale to month" },
              ]}
            />
          </span>
          <label>
            <input
              type="checkbox"
              checked={monteCarlo}
              onChange={(e) => {
                setPreview(null);
                setMonteCarlo(e.target.checked);
              }}
            />{" "}
            Monte Carlo
          </label>
        </div>
        <div style={row}>
          <button
            type="button"
            className="btn-primary"
            disabled={busy || selected.length === 0}
            onClick={() => void run(() => runCompare(variants()))}
          >
            {busy && !preview ? "Comparing…" : "Compare"}
          </button>
          {selected.length > 0 && (
            <button
              type="button"
              className="btn-quiet"
              disabled={busy}
              onClick={() => {
                setSelected([]);
                setPreview(null);
              }}
            >
              Clear
            </button>
          )}
        </div>
        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
      </section>

      {response && preview && (
        <>
          <CompareChart
            plan={response.plan}
            variants={response.variants}
            mode={mode}
            onModeChange={setMode}
          />
          <section className="card" style={stack} aria-label="Outcomes">
            <OutcomeTable
              plan={response.plan}
              variants={response.variants}
              currency={currency}
              mode={mode}
              busy={busy}
              onApply={(index) => setConfirming(index)}
            />
            {response.caveats
              .concat(...response.variants.map((v) => v.caveats))
              .filter((c, i, all) => all.indexOf(c) === i)
              .map((caveat) => (
                <p key={caveat} style={muted}>
                  {caveat}
                </p>
              ))}
            {pending && confirming != null && (
              <div
                role="dialog"
                aria-label={`Apply ${pending.label}`}
                className="card"
                style={stack}
              >
                <p style={{ margin: 0 }}>
                  {response.spending_feed ? (
                    <>
                      Spending from transactions follows <strong>{pending.label}</strong> instead of{" "}
                      {feed.basis === "months" ? monthsText(feed.basis_months) : "recent months"}:{" "}
                      {money(pending.essential_annual, currency)} essential and{" "}
                      {money(pending.discretionary_annual, currency)} discretionary a year.
                    </>
                  ) : (
                    <>
                      Living expenses scale to {money(pending.essential_annual, currency)} essential
                      and {money(pending.discretionary_annual, currency)} discretionary a year
                      {futurePhases === "scale" ? ", later phases included" : ""}. Income stays as
                      entered.
                    </>
                  )}
                </p>
                <div style={row}>
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={busy}
                    onClick={() => void apply(confirming)}
                  >
                    Apply
                  </button>
                  <button type="button" onClick={() => setConfirming(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </section>
          {monthOutcomes.length >= 2 && (
            <CategoryDifferences
              a={monthOutcomes[0]}
              b={monthOutcomes[1]}
              labels={data.labels}
              currency={currency}
            />
          )}
        </>
      )}
    </div>
  );
}
