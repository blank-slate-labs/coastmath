import { useEffect, useRef, useState } from "react";
import { scaleLinear } from "d3-scale";

import { ChartHeader } from "@/components/chart_chrome";
import { PLAN_SECTIONS, type PlanSectionKey } from "@/pages/plan_setup";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import type { WellnessBands, WellnessMetric, WellnessResponse, WellnessStatus } from "@/types/plan";
import { intlCompactCurrency, pct } from "@/utils/format";
import { useAdjustedTimeline } from "@/utils/use_adjusted_timeline";
import { missingRiskInputs } from "@/utils/plan_inputs";
import "./wellness_scorecard.css";

const GROUPS: { status: Exclude<WellnessStatus, "not_applicable">; title: string }[] = [
  { status: "needs_attention", title: "Needs attention" },
  { status: "fair", title: "Fair" },
  { status: "strong", title: "Strong" },
];
const SECTION_KEYS = new Set<string>(PLAN_SECTIONS.map((section) => section.key));
const BAR_WIDTH = 100;

/** A metric value in its unit; currency is divided by the current mode's factor. */
export function formatWellnessValue(
  metric: Pick<WellnessMetric, "unit">,
  value: number | null,
  currencyFactor = 1,
): string {
  if (value === null) return "Not reached";
  switch (metric.unit) {
    case "percent":
      return pct(value, 1);
    case "months":
      return `${value.toFixed(1)} mo`;
    case "multiple":
      return `${value.toFixed(1)}×`;
    case "ratio":
      return value.toFixed(2);
    case "currency":
      return intlCompactCurrency(value / currencyFactor);
    case "year":
    case "age":
      return String(Math.round(value));
  }
}

/** Domain and bar positions for a band bar: D3 computes, React draws. */
export function bandGeometry(bands: WellnessBands, value: number | null, nonNegative: boolean) {
  const points = [bands.fair_at, bands.strong_at, ...(value === null ? [] : [value])];
  const min = Math.min(...points);
  const max = Math.max(...points);
  const pad = (max - min) * 0.25 || Math.abs(max) * 0.1 || 1;
  const low = nonNegative && min >= 0 ? Math.max(0, min - pad) : min - pad;
  const scale = scaleLinear()
    .domain([low, max + pad])
    .range([0, BAR_WIDTH])
    .clamp(true);
  const fair = scale(bands.fair_at);
  const strong = scale(bands.strong_at);
  // Zones left to right in the scale's direction.
  const zones: { status: Exclude<WellnessStatus, "not_applicable">; x: number; width: number }[] =
    bands.better === "higher"
      ? [
          { status: "needs_attention", x: 0, width: fair },
          { status: "fair", x: fair, width: strong - fair },
          { status: "strong", x: strong, width: BAR_WIDTH - strong },
        ]
      : [
          { status: "strong", x: 0, width: strong },
          { status: "fair", x: strong, width: fair - strong },
          { status: "needs_attention", x: fair, width: BAR_WIDTH - fair },
        ];
  return {
    zones,
    thresholds: [fair, strong],
    marker: value === null ? null : scale(value),
  };
}

function BandBar({
  metric,
  text,
  currencyFactor,
}: {
  metric: WellnessMetric;
  text: string;
  currencyFactor: number;
}) {
  const bands = metric.bands!;
  const geometry = bandGeometry(bands, metric.value, metric.unit !== "year");
  const label = `${metric.label} ${text}: fair at ${formatWellnessValue(metric, bands.fair_at, currencyFactor)}, strong at ${formatWellnessValue(metric, bands.strong_at, currencyFactor)}, ${bands.better} is better`;
  return (
    <svg
      className="wellness-band"
      viewBox={`0 0 ${BAR_WIDTH} 10`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {geometry.zones.map(
        (zone) =>
          zone.width > 0 && (
            <rect
              key={zone.status}
              className={`wellness-zone wellness-zone-${zone.status}`}
              x={zone.x}
              y={3}
              width={zone.width}
              height={4}
            />
          ),
      )}
      {geometry.thresholds.map((x, i) => (
        <rect key={i} className="wellness-threshold" x={x - 0.25} y={1} width={0.5} height={8} />
      ))}
      {geometry.marker !== null && (
        <rect
          data-testid="wellness-marker"
          className="wellness-marker"
          x={geometry.marker - 0.75}
          y={0}
          width={1.5}
          height={10}
        />
      )}
    </svg>
  );
}

/** Plan ratios graded against benchmarks, from the server's scorecard. */
export default function WellnessScorecard({
  onEditSection,
}: {
  onEditSection: (key: PlanSectionKey) => void;
}) {
  const { adapter } = useStorage();
  const planId = usePlanStore((s) => s.plan?.id ?? null);
  const simulation = usePlanStore((s) => s.simulation);
  const isSimulating = usePlanStore((s) => s.isSimulating);
  const { factorAt } = useAdjustedTimeline();
  const [result, setResult] = useState<{ planId: string; data: WellnessResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const request = useRef(0);

  // An empty plan grades as "Strong" on ratios of zero; it has nothing to grade yet.
  const missingInputs = missingRiskInputs(simulation);

  // Loads on open and after every refreshed projection; only the latest answer renders.
  useEffect(() => {
    if (!planId || !simulation || missingInputs) return;
    const id = ++request.current;
    setBusy(true);
    setError(null);
    adapter
      .runWellness(planId)
      .then((data) => {
        if (id === request.current) setResult({ planId, data });
      })
      .catch((err: unknown) => {
        if (id === request.current)
          setError(
            err instanceof Error && err.message
              ? err.message
              : "The scorecard could not be calculated.",
          );
      })
      .finally(() => {
        if (id === request.current) setBusy(false);
      });
  }, [adapter, planId, simulation, attempt, missingInputs]);

  if (!planId) return null;
  if (missingInputs) {
    return (
      <section className="card wellness-scorecard">
        <ChartHeader title="Wellness scorecard" />
        <p className="wellness-status">{missingInputs}</p>
      </section>
    );
  }
  const data = result?.planId === planId ? result.data : null;
  const graded = data?.metrics.filter((metric) => metric.status !== "not_applicable") ?? [];

  return (
    <section className="card wellness-scorecard" aria-busy={busy || isSimulating}>
      <ChartHeader title="Wellness scorecard" />
      {error && (
        <div className="wellness-error">
          <p role="alert">{error}</p>
          <button type="button" onClick={() => setAttempt((n) => n + 1)} disabled={busy}>
            Retry
          </button>
        </div>
      )}
      {!data && !error && (busy || isSimulating) && (
        <p className="wellness-status" role="status">
          Calculating…
        </p>
      )}
      {data && graded.length === 0 && !error && (
        <p className="wellness-status">No graded metrics for this plan.</p>
      )}
      {data &&
        !error &&
        GROUPS.map(({ status, title }) => {
          const metrics = graded.filter((metric) => metric.status === status);
          if (metrics.length === 0) return null;
          return (
            <div key={status} className={`wellness-group wellness-group-${status}`}>
              <h4>{title}</h4>
              <div className="wellness-grid">
                {metrics.map((metric) => {
                  const factor =
                    metric.unit === "currency" && metric.basis_year !== null
                      ? factorAt(metric.basis_year - data.start_year)
                      : 1;
                  const text = formatWellnessValue(metric, metric.value, factor);
                  const body = (
                    <>
                      <span className="wellness-label">{metric.label}</span>
                      <strong className="wellness-value">{text}</strong>
                      {metric.bands && (
                        <BandBar metric={metric} text={text} currencyFactor={factor} />
                      )}
                    </>
                  );
                  const section = metric.section;
                  return section && SECTION_KEYS.has(section) ? (
                    <button
                      key={metric.key}
                      type="button"
                      className="wellness-tile"
                      data-sample-view
                      onClick={() => onEditSection(section as PlanSectionKey)}
                    >
                      {body}
                    </button>
                  ) : (
                    <div key={metric.key} className="wellness-tile">
                      {body}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
    </section>
  );
}
