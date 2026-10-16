import { useMemo, useState } from "react";

import { compactCurrency, dollarsOr } from "@/utils/format";
import type { MonteCarloResult } from "@/types/plan";

const failureLabels: Record<string, string> = {
  liquid_assets_depleted: "Cash and investments depleted",
  net_worth_depleted: "Net worth depleted",
  simulation_failure: "Spending could not be funded",
};

function successColor(rate: number): string {
  if (rate >= 0.9) return "var(--text-primary)";
  if (rate >= 0.75) return "var(--text-primary)";
  return "var(--chart-red)";
}

interface FailureGroup {
  cause: string;
  count: number;
  avgAge: number;
}

interface Props {
  result: MonteCarloResult;
}

export default function MonteCarloSummary({ result }: Props) {
  const [failureOpen, setFailureOpen] = useState(false);

  const failureCount = result.failure_analysis.length;

  const failureGroups = useMemo<FailureGroup[]>(() => {
    if (failureCount === 0) return [];

    const map = new Map<string, { count: number; totalAge: number }>();
    for (const f of result.failure_analysis) {
      const entry = map.get(f.cause);
      if (entry) {
        entry.count += 1;
        entry.totalAge += f.failure_age;
      } else {
        map.set(f.cause, { count: 1, totalAge: f.failure_age });
      }
    }

    return Array.from(map.entries())
      .map(([cause, { count, totalAge }]) => ({
        cause,
        count,
        avgAge: Math.round(totalAge / count),
      }))
      .sort((a, b) => b.count - a.count);
  }, [result.failure_analysis, failureCount]);

  const avgFailureAge = useMemo(() => {
    if (failureCount === 0) return null;
    const total = result.failure_analysis.reduce((sum, f) => sum + f.failure_age, 0);
    return Math.round(total / failureCount);
  }, [result.failure_analysis, failureCount]);

  const color = successColor(result.success_rate);

  return (
    <div>
      <h3 style={{ margin: "0 0 20px", fontSize: 16, fontWeight: 600 }}>Monte Carlo results</h3>

      {/* Success rate hero */}
      <div
        style={{
          textAlign: "left",
          marginBottom: 24,
          padding: "20px 0",
          borderRadius: "var(--radius-md)",
        }}
      >
        <div
          style={{ fontSize: 13, color: "var(--text-tertiary)", marginBottom: 6, fontWeight: 600 }}
        >
          Funding success rate
        </div>
        <div
          style={{
            fontSize: 44,
            fontWeight: 700,
            color,
            letterSpacing: "-0.02em",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {(result.success_rate * 100).toFixed(1)}%
        </div>
        <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 6 }}>
          {result.n_trials - failureCount} funded · {failureCount} failed
        </div>
        {result.target_success_rate != null && (
          <div style={{ marginTop: 14 }}>
            <div
              style={{
                fontSize: 13,
                color: "var(--text-tertiary)",
                marginBottom: 4,
                fontWeight: 600,
              }}
            >
              Target success rate
            </div>
            <div
              style={{
                fontSize: 28,
                fontWeight: 700,
                color: successColor(result.target_success_rate),
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {(result.target_success_rate * 100).toFixed(1)}%
            </div>
            <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 4 }}>
              {result.definitions?.target_success_rate}
            </div>
          </div>
        )}
      </div>

      {/* Without a goal, the categories only repeat the funded and failed counts above. */}
      {result.target_success_rate != null &&
        result.outcome_categories &&
        result.outcome_categories.length > 0 && (
          <div style={{ marginBottom: 20 }} data-testid="outcome-categories">
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Outcome categories</div>
            {result.outcome_categories
              .filter((c) => c.count > 0 || c.key === "funding_failure" || c.key === "met_targets")
              .map((c) => (
                <div key={c.key} className="stat-row" title={c.definition}>
                  <span className="stat-label">{c.label}</span>
                  <span className="stat-value" style={{ fontVariantNumeric: "tabular-nums" }}>
                    {c.count} · {(c.rate * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
          </div>
        )}

      {/* Final net worth stats */}
      <div style={{ marginBottom: 20 }}>
        <div className="stat-row">
          <span className="stat-label">
            Median final net worth ({dollarsOr("future dollars", "future amounts")},{" "}
            {result.percentile_curves.years.at(-1)})
          </span>
          <span className="stat-value">{compactCurrency(result.median_final_net_worth)}</span>
        </div>
        <div className="stat-row">
          <span className="stat-label">
            Middle 80% of final outcomes ({dollarsOr("future dollars", "future amounts")},{" "}
            {result.percentile_curves.years.at(-1)})
          </span>
          <span className="stat-value" style={{ fontVariantNumeric: "tabular-nums" }}>
            {compactCurrency(result.p10_final_net_worth)} –{" "}
            {compactCurrency(result.p90_final_net_worth)}
          </span>
        </div>
      </div>

      {/* Failure analysis (collapsible) */}
      {failureCount > 0 && (
        <div>
          <button
            className="nav-item"
            onClick={() => setFailureOpen((v) => !v)}
            style={{
              background: "none",
              border: "none",
              padding: 0,
              fontSize: 14,
              fontWeight: 600,
              color: "var(--text-secondary)",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <span
              style={{
                display: "inline-block",
                transition: "transform 0.15s",
                transform: failureOpen ? "rotate(90deg)" : "rotate(0deg)",
                fontSize: 10,
              }}
            >
              &#9654;
            </span>
            Failure Analysis ({failureCount} failures, avg age {avgFailureAge})
          </button>

          {failureOpen && (
            <div style={{ marginTop: 12 }}>
              {failureGroups.map((g) => (
                <div key={g.cause} className="stat-row" style={{ fontSize: 13 }}>
                  <span className="stat-label">
                    {failureLabels[g.cause] ??
                      g.cause.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}
                  </span>
                  <span style={{ color: "var(--text-tertiary)", fontSize: 12 }}>
                    {g.count} failures, avg age {g.avgAge}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {failureCount === 0 && (
        <div style={{ fontSize: 13, color: "var(--chart-green)", fontWeight: 500 }}>
          No failures across all trials
        </div>
      )}
    </div>
  );
}
