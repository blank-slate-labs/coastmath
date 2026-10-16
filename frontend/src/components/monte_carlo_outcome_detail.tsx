import MonteCarloFanChart from "@/components/monte_carlo_fan_chart";
import { METRIC_LABELS } from "@/components/monte_carlo_method_settings";
import type { MonteCarloExtraMetric, OutcomeDetail, PercentileCurves } from "@/types/plan";

const percent = (rate: number) => `${(rate * 100).toFixed(1)}%`;

function Row({ label, count, rate }: { label: string; count: number; rate: number }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{count.toLocaleString()}</td>
      <td>{percent(rate)}</td>
    </tr>
  );
}

/** Failure timing of failed trials and surplus classes of successful ones. */
export function MonteCarloOutcomeDetail({ detail }: { detail: OutcomeDetail }) {
  const { failure_timing: timing, surplus } = detail;
  const early = Math.round(timing.early_fraction * 100);
  const late = Math.round(timing.late_fraction * 100);
  const reference = surplus.reference_milestone_name ?? "the first projection year";
  return (
    <div className="card" data-testid="outcome-detail">
      <div className="card-header">
        <h3 style={{ margin: 0, fontSize: 18 }}>Outcome detail</h3>
      </div>
      <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
        <table>
          <caption>When failed trials failed</caption>
          <thead>
            <tr>
              <th scope="col">Timing</th>
              <th scope="col">Trials</th>
              <th scope="col">Share of failed</th>
            </tr>
          </thead>
          <tbody>
            <Row
              label={`Early (before ${early}% of the plan)`}
              count={timing.early}
              rate={timing.early_rate}
            />
            <Row label="Mid" count={timing.mid} rate={timing.mid_rate} />
            <Row
              label={`Late (from ${late}% of the plan)`}
              count={timing.late}
              rate={timing.late_rate}
            />
          </tbody>
        </table>
        <table>
          <caption>How much successful trials had left, versus net worth at {reference}</caption>
          <thead>
            <tr>
              <th scope="col">Class</th>
              <th scope="col">Trials</th>
              <th scope="col">Share of successful</th>
            </tr>
          </thead>
          <tbody>
            <Row
              label={`Thin margin (below ${surplus.thin_margin_percent}%)`}
              count={surplus.thin_margin}
              rate={surplus.thin_margin_rate}
            />
            <Row
              label="Moderate margin"
              count={surplus.moderate_margin}
              rate={surplus.moderate_margin_rate}
            />
            <Row
              label={`Wide margin (above ${surplus.wide_margin_percent}%)`}
              count={surplus.wide_margin}
              rate={surplus.wide_margin_rate}
            />
          </tbody>
        </table>
      </div>
      {Object.values(detail.definitions).map((text) => (
        <p key={text} style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
          {text}
        </p>
      ))}
    </div>
  );
}

/** A percentile band chart for each requested extra metric. */
export function MonteCarloMetricBands({
  metrics,
  width,
}: {
  metrics: Partial<Record<MonteCarloExtraMetric, PercentileCurves>>;
  width: number;
}) {
  return (
    <>
      {(Object.keys(METRIC_LABELS) as MonteCarloExtraMetric[])
        .filter((key) => metrics[key])
        .map((key) => {
          const curves = metrics[key]!;
          return (
            <div className="card" key={key} data-testid={`metric-band-${key}`}>
              <div className="card-header">
                <h3 style={{ margin: 0, fontSize: 18 }}>{METRIC_LABELS[key]} (future dollars)</h3>
              </div>
              <MonteCarloFanChart
                percentileCurves={(["p10", "p25", "p50", "p75", "p90"] as const).map((label) => ({
                  label,
                  values: curves[label],
                }))}
                years={curves.years}
                width={width}
                height={260}
              />
            </div>
          );
        })}
    </>
  );
}
