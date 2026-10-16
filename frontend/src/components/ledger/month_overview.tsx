import { scaleBand, scaleLinear } from "d3-scale";
import type { LedgerMonth } from "@/api/ledger";
import { money, monthLabel, muted, row, stack } from "./ledger_format";

const WIDTH = 640;
const HEIGHT = 200;
const PAD = { top: 12, right: 8, bottom: 24, left: 8 };
const ESSENTIAL = "var(--chart-1, #3b6ea8)";
const DISCRETIONARY = "var(--chart-2, #e0a040)";
const TAKE_HOME = "var(--text-primary, #222)";

/** Monthly essential and discretionary spending, stacked, with take-home pay as a marker. */
export default function MonthOverview({
  months,
  currency,
}: {
  months: LedgerMonth[];
  currency: string;
}) {
  if (months.length === 0)
    return (
      <section aria-label="Months" style={stack}>
        <h3 style={{ margin: 0 }}>Months</h3>
        <p style={muted}>No months yet.</p>
      </section>
    );
  const x = scaleBand<string>()
    .domain(months.map((m) => m.month))
    .range([PAD.left, WIDTH - PAD.right])
    .padding(0.25);
  const top = Math.max(
    1,
    ...months.map((m) => Math.max(0, m.essential) + Math.max(0, m.discretionary)),
    ...months.map((m) => m.income),
  );
  const y = scaleLinear()
    .domain([0, top])
    .nice()
    .range([HEIGHT - PAD.bottom, PAD.top]);
  const base = y(0);
  const labelEvery = Math.ceil(months.length / 12);

  return (
    <section aria-label="Months" style={stack}>
      <h3 style={{ margin: 0 }}>Months</h3>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="Spending by month"
        style={{ width: "100%", height: "auto" }}
      >
        {months.map((m, index) => {
          const left = x(m.month) ?? 0;
          const essential = Math.max(0, m.essential);
          const discretionary = Math.max(0, m.discretionary);
          const essentialTop = y(essential);
          const total = y(essential + discretionary);
          const title = `${monthLabel(m.month)}: essential ${money(m.essential, currency)}, discretionary ${money(m.discretionary, currency)}, take-home ${money(m.income, currency)}${m.complete ? "" : ", incomplete"}`;
          return (
            <g
              key={m.month}
              data-month={m.month}
              data-complete={m.complete ? "true" : "false"}
              opacity={m.complete ? 1 : 0.35}
            >
              <title>{title}</title>
              <rect
                x={left}
                y={essentialTop}
                width={x.bandwidth()}
                height={base - essentialTop}
                fill={ESSENTIAL}
              />
              <rect
                x={left}
                y={total}
                width={x.bandwidth()}
                height={essentialTop - total}
                fill={DISCRETIONARY}
              />
              {!m.complete && (
                <rect
                  x={left}
                  y={PAD.top}
                  width={x.bandwidth()}
                  height={base - PAD.top}
                  fill="none"
                  stroke="currentColor"
                  strokeDasharray="3 3"
                />
              )}
              {m.income > 0 && (
                <line
                  data-take-home
                  x1={left - 2}
                  x2={left + x.bandwidth() + 2}
                  y1={y(m.income)}
                  y2={y(m.income)}
                  stroke={TAKE_HOME}
                  strokeWidth={2}
                />
              )}
              {index % labelEvery === 0 && (
                <text
                  x={left + x.bandwidth() / 2}
                  y={HEIGHT - 6}
                  textAnchor="middle"
                  fontSize={11}
                  fill="currentColor"
                >
                  {monthLabel(m.month)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div style={{ ...row, ...muted }} aria-hidden="true">
        <span>
          <svg width="10" height="10">
            <rect width="10" height="10" fill={ESSENTIAL} />
          </svg>{" "}
          Essential
        </span>
        <span>
          <svg width="10" height="10">
            <rect width="10" height="10" fill={DISCRETIONARY} />
          </svg>{" "}
          Discretionary
        </span>
        <span>
          <svg width="14" height="10">
            <line x1="0" x2="14" y1="5" y2="5" stroke={TAKE_HOME} strokeWidth="2" />
          </svg>{" "}
          Take-home
        </span>
        <span>
          <svg width="10" height="10">
            <rect
              x="0.5"
              y="0.5"
              width="9"
              height="9"
              fill="none"
              stroke="currentColor"
              strokeDasharray="2 2"
            />
          </svg>{" "}
          Incomplete
        </span>
      </div>
    </section>
  );
}
