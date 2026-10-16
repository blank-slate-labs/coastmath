import { useEffect, useMemo, useState } from "react";
import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";

import { usePlanStore } from "@/stores/plan_store";
import { useStorage } from "@/storage/context";
import type {
  WithdrawalCompareResponse,
  WithdrawalMethod,
  WithdrawalStrategyOutcome,
} from "@/types/plan";
import { compactCurrency, moneyLabel, pct } from "@/utils/format";
import { ChartLegend } from "@/components/chart_chrome";

const METHODS: { value: WithdrawalMethod; label: string; help: string }[] = [
  {
    value: "constant_dollar",
    label: "Constant dollar",
    help: "Initial rate × starting portfolio, inflation-adjusted annually.",
  },
  {
    value: "constant_percentage",
    label: "Constant percentage",
    help: "Fixed percentage of each year’s portfolio value.",
  },
  {
    value: "guyton_klinger",
    label: "Guyton-Klinger guardrails",
    help: "±10% adjustment when the rate drifts 20% from initial; no inflation raise after a losing year; guardrails off in the last 15 years.",
  },
  {
    value: "vanguard_dynamic",
    label: "Vanguard dynamic spending",
    help: "Initial rate of current portfolio, changes capped at −2.5% / +5% real.",
  },
  {
    value: "rmd_table",
    label: "IRS life-expectancy percentage",
    help: "Portfolio ÷ IRS life-expectancy factor for your age.",
  },
];

const COLORS = [
  "var(--chart-blue, #2563eb)",
  "var(--chart-green)",
  "var(--chart-amber, #d97706)",
  "var(--chart-red)",
  "var(--chart-purple, #7c3aed)",
];

function SpendingChart({
  planned,
  strategies,
  width,
}: {
  planned: WithdrawalStrategyOutcome;
  strategies: WithdrawalStrategyOutcome[];
  width: number;
}) {
  const height = 260;
  const margin = { top: 12, right: 12, bottom: 28, left: 56 };
  const series = useMemo(
    () =>
      [{ ...planned, label: "Planned spending" }, ...strategies].filter(
        (s) => s.spending_path.length > 0,
      ),
    [planned, strategies],
  );
  const years = series.flatMap((s) => s.spending_path.map((p) => p.year));
  const values = series.flatMap((s) => s.spending_path.map((p) => p.real));
  if (years.length === 0) return null;
  const x = scaleLinear()
    .domain([Math.min(...years), Math.max(...years)])
    .range([margin.left, width - margin.right]);
  const y = scaleLinear()
    .domain([0, Math.max(...values, 1) * 1.1])
    .nice()
    .range([height - margin.top, margin.top]);
  const path = line<{ year: number; real: number }>()
    .x((d) => x(d.year))
    .y((d) => y(d.real));
  const ticks = y.ticks(4);
  const xTicks = x.ticks(Math.min(8, years.length));
  return (
    <div>
      <ChartLegend
        entries={series.map((s, i) => ({
          label: s.label,
          color: i === 0 ? "var(--text-tertiary)" : COLORS[(i - 1) % COLORS.length],
          kind: i === 0 ? "dashed" : "line",
        }))}
      />
      <svg
        viewBox={`0 0 ${width} ${height + margin.bottom}`}
        width={width}
        height={height + margin.bottom}
        role="img"
        aria-label="Real spending by year for each withdrawal strategy"
        style={{ maxWidth: "100%", height: "auto", display: "block" }}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={margin.left}
              x2={width - margin.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--surface-border)"
            />
            <text
              x={margin.left - 6}
              y={y(t)}
              dy="0.32em"
              textAnchor="end"
              fontSize={11}
              fill="var(--text-tertiary)"
            >
              {compactCurrency(t)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text
            key={t}
            x={x(t)}
            y={height + 16}
            textAnchor="middle"
            fontSize={11}
            fill="var(--text-tertiary)"
          >
            {Math.round(t)}
          </text>
        ))}
        {series.map((s, i) => (
          <path
            key={s.method}
            d={path(s.spending_path) ?? undefined}
            fill="none"
            stroke={i === 0 ? "var(--text-tertiary)" : COLORS[(i - 1) % COLORS.length]}
            strokeWidth={i === 0 ? 1.5 : 2}
            strokeDasharray={i === 0 ? "4 4" : undefined}
          />
        ))}
      </svg>
    </div>
  );
}

/**
 * Runs the plan under textbook withdrawal rules and compares real spending and
 * success against the plan's own expenses. Purely a comparison: nothing is
 * written to the plan.
 */
export default function WithdrawalStrategiesPanel() {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  // Start from the plan's saved strategy when one is enabled.
  const saved = plan?.withdrawal_strategy?.enabled ? plan.withdrawal_strategy : null;
  const savedMethod = METHODS.find((m) => m.value === saved?.method)?.value;
  const [methods, setMethods] = useState<WithdrawalMethod[]>(() => {
    const defaults: WithdrawalMethod[] = ["constant_dollar", "guyton_klinger", "vanguard_dynamic"];
    return savedMethod && !defaults.includes(savedMethod) ? [savedMethod, ...defaults] : defaults;
  });
  const [initialRate, setInitialRate] = useState(
    saved?.initial_rate != null ? String(Math.round(saved.initial_rate * 1e6) / 1e4) : "4",
  );
  const savedStartAge =
    saved && !saved.start_milestone_id && saved.start_age != null ? String(saved.start_age) : "";
  const defaultMilestone =
    saved?.start_milestone_id ??
    (savedStartAge
      ? ""
      : (plan?.milestones.find((m) => /retir/i.test(m.name))?.id ?? plan?.milestones[0]?.id ?? ""));
  const defaultAge = savedStartAge || (defaultMilestone ? "" : "65");
  const [startMilestone, setStartMilestone] = useState(defaultMilestone);
  const [startAge, setStartAge] = useState(defaultAge);
  const [trials, setTrials] = useState("0");
  const [seed, setSeed] = useState("42");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<WithdrawalCompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setResult(null);
  }, [plan]);
  useEffect(() => {
    setStartMilestone(defaultMilestone);
    setStartAge(defaultAge);
  }, [plan?.id, defaultMilestone, defaultAge]);

  if (!plan) return null;
  const currentPlan = plan;

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    const rate = Number(initialRate) / 100;
    if (initialRate.trim() === "" || !Number.isFinite(rate) || rate <= 0 || rate > 0.2) {
      setError("Initial withdrawal rate must be between 0 and 20 percent.");
      return;
    }
    if (methods.length === 0) {
      setError("Choose at least one strategy.");
      return;
    }
    const age = startAge.trim() === "" ? null : Number(startAge);
    if (age !== null && (!Number.isInteger(age) || age < 18 || age > 110)) {
      setError("Start age must be a whole age between 18 and 110, or blank.");
      return;
    }
    if (!startMilestone && age === null) {
      setError("Choose the milestone or age at which withdrawals begin.");
      return;
    }
    const mc = Number(trials);
    if (!Number.isInteger(mc) || mc < 0 || mc > 500) {
      setError("Monte Carlo trials must be a whole number from 0 to 500.");
      return;
    }
    setRunning(true);
    try {
      setResult(
        await adapter.compareWithdrawalStrategies(currentPlan.id, {
          methods,
          initial_rate: rate,
          start_milestone_id: startMilestone || null,
          start_age: age,
          monte_carlo_trials: mc,
          seed: seed.trim() === "" ? null : Number(seed),
        }),
      );
    } catch {
      setError(
        "Could not compare withdrawal strategies. Check the plan simulates successfully and try again.",
      );
    } finally {
      setRunning(false);
    }
  }

  const rows = result
    ? [{ ...result.planned, label: "Planned spending (this plan)" }, ...result.strategies]
    : [];

  return (
    <div className="card" style={{ display: "grid", gap: 12 }}>
      <div>
        <div className="eyebrow">Withdrawal strategies</div>
        <h3 style={{ margin: "6px 0 8px", fontSize: 18 }}>Withdrawal rules</h3>
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
          Each scenario replaces planned retirement expenses with portfolio-based spending. Your
          plan stays unchanged.
        </p>
      </div>
      <form onSubmit={run} style={{ display: "grid", gap: 10 }}>
        <fieldset
          disabled={running}
          style={{ border: 0, padding: 0, minWidth: 0, display: "grid", gap: 10 }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: 10,
            }}
          >
            <label>
              Initial withdrawal rate (%)
              <input
                type="number"
                min={0.1}
                max={20}
                step={0.1}
                value={initialRate}
                onChange={(e) => setInitialRate(e.target.value)}
              />
            </label>
            <label>
              Withdrawals start at milestone
              <select
                value={startMilestone}
                onChange={(e) => {
                  setStartMilestone(e.target.value);
                  setStartAge("");
                }}
              >
                <option value="">— choose or use age —</option>
                {plan.milestones.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              …or at age
              <input
                type="number"
                min={18}
                max={110}
                step={1}
                value={startAge}
                onChange={(e) => {
                  setStartAge(e.target.value);
                  setStartMilestone("");
                }}
                placeholder="e.g. 65"
              />
            </label>
            <label>
              Monte Carlo trials per rule (0 = skip)
              <input
                type="number"
                min={0}
                max={500}
                step={50}
                value={trials}
                onChange={(e) => setTrials(e.target.value)}
              />
            </label>
            <label>
              Seed
              <input type="number" min={0} value={seed} onChange={(e) => setSeed(e.target.value)} />
            </label>
          </div>
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend style={{ fontSize: 13 }}>Rules to compare</legend>
            <div style={{ display: "grid", gap: 6 }}>
              {METHODS.map((m) => (
                <label
                  key={m.value}
                  style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}
                >
                  <input
                    type="checkbox"
                    checked={methods.includes(m.value)}
                    onChange={(e) =>
                      setMethods(
                        e.target.checked
                          ? [...methods, m.value]
                          : methods.filter((x) => x !== m.value),
                      )
                    }
                  />
                  <span>
                    <strong>{m.label}</strong>{" "}
                    <span style={{ color: "var(--text-secondary)" }}>{m.help}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <button type="submit">
              {running ? "Simulating rules…" : "Compare withdrawal rules"}
            </button>
          </div>
        </fieldset>
      </form>
      {error && (
        <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ display: "grid", gap: 12 }}>
          <SpendingChart planned={result.planned} strategies={result.strategies} width={760} />
          <p style={{ margin: 0, fontSize: 12, color: "var(--text-tertiary)" }}>
            {moneyLabel("Dashed: planned spending. Solid: strategy spending. Today’s dollars.")}
          </p>
          <div style={{ overflowX: "auto" }}>
            <table
              style={{ width: "100%", fontSize: 13 }}
              aria-label="Withdrawal strategy comparison"
            >
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Rule</th>
                  <th style={{ textAlign: "right" }}>Start year</th>
                  <th style={{ textAlign: "right" }}>
                    {moneyLabel("Starting spending (nominal $)")}
                  </th>
                  <th style={{ textAlign: "right" }}>Median real spending</th>
                  <th style={{ textAlign: "right" }}>Lowest real</th>
                  <th style={{ textAlign: "right" }}>Largest real cut</th>
                  <th style={{ textAlign: "right" }}>Years below plan</th>
                  <th style={{ textAlign: "right" }}>Final net worth</th>
                  <th style={{ textAlign: "right" }}>Deterministic</th>
                  <th style={{ textAlign: "right" }}>Monte Carlo success</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.method}>
                    <td>{s.label}</td>
                    <td style={{ textAlign: "right" }}>{s.start_year ?? "Not reached"}</td>
                    <td style={{ textAlign: "right" }}>{compactCurrency(s.first_year_spending)}</td>
                    <td style={{ textAlign: "right" }}>
                      {compactCurrency(s.median_real_spending)}
                    </td>
                    <td style={{ textAlign: "right" }}>{compactCurrency(s.min_real_spending)}</td>
                    <td style={{ textAlign: "right" }}>
                      {s.method === "planned" ? "—" : pct(s.real_spending_drawdown, 0)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {s.method === "planned" ? "—" : s.years_below_planned}
                    </td>
                    <td style={{ textAlign: "right" }}>{compactCurrency(s.final_net_worth)}</td>
                    <td
                      style={{
                        textAlign: "right",
                        color: s.success ? "var(--chart-green)" : "var(--chart-red)",
                      }}
                    >
                      {s.success ? "Survives" : `Fails ${s.failure_year}`}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {s.monte_carlo_success_rate == null
                        ? "—"
                        : pct(s.monte_carlo_success_rate, 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary style={{ cursor: "pointer", fontSize: 13 }}>
              How to read this comparison
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
    </div>
  );
}
