import { useEffect, useMemo, useState } from "react";
import { scaleLinear, scaleTime } from "d3-scale";
import { line } from "d3-shape";
import { useStorage } from "@/storage/context";
import { compactCurrency, fullCurrency, moneyLabel } from "@/utils/format";
import { InlineValidity } from "@/components/inline_validity";
import { confirmDelete } from "@/components/confirm_dialog";
import type { ProgressPoint } from "@/types/plan";
import MoneyInput from "./money_input";

function localDate() {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export default function ProgressHistory() {
  const { adapter } = useStorage();
  const [points, setPoints] = useState<ProgressPoint[]>([]);
  const [date, setDate] = useState(localDate);
  // Blank, not $0: each total is entered, so recording only cash never saves $0 property or debt.
  const [liquid, setLiquid] = useState("");
  const [property, setProperty] = useState("");
  const [debt, setDebt] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    adapter
      .listProgressPoints()
      .then((p) => {
        if (active) setPoints(p);
      })
      .catch(() => {
        if (active) setError("Could not load progress history. Reopen Progress to retry.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [adapter]);
  const ordered = useMemo(
    () => [...points].sort((a, b) => a.recorded_date.localeCompare(b.recorded_date)),
    [points],
  );
  const chart = useMemo(() => {
    if (!ordered.length) return null;
    const dates = ordered.map((p) => new Date(`${p.recorded_date}T12:00:00`));
    const start = dates[0];
    const end = dates[dates.length - 1];
    const x = scaleTime()
      .domain(
        start.getTime() === end.getTime()
          ? [new Date(+start - 86400000), new Date(+end + 86400000)]
          : [start, end],
      )
      .range([80, 860]);
    const values = ordered.map((p) => p.net_worth);
    const low = Math.min(0, ...values);
    const high = Math.max(0, ...values);
    const y = scaleLinear()
      .domain([low, high === low ? low + 1 : high])
      .nice()
      .range([230, 20]);
    return {
      x,
      y,
      path: line<ProgressPoint>()
        .x((p) => x(new Date(`${p.recorded_date}T12:00:00`)))
        .y((p) => y(p.net_worth))(ordered),
    };
  }, [ordered]);
  async function save() {
    if (
      !date ||
      date > localDate() ||
      ![liquid, property, debt].every(
        (v) => v.trim() !== "" && Number.isFinite(Number(v)) && Number(v) >= 0,
      )
    ) {
      setError("Enter a date no later than today and non-negative asset and debt totals.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const point = await adapter.createProgressPoint({
        recorded_date: date,
        net_worth: Number(liquid) + Number(property) - Number(debt),
        assets_breakdown: { liquid_assets: Number(liquid), property: Number(property) },
        liabilities_breakdown: { debt: Number(debt) },
        auto_logged: false,
      });
      setPoints((p) => [...p, point]);
      setMessage("Progress recorded.");
    } catch {
      setError("Could not record progress. Your values are retained; try again.");
    } finally {
      setBusy(false);
    }
  }
  async function remove(point: ProgressPoint) {
    if (!(await confirmDelete(`the ${point.recorded_date} record`))) return;
    setBusy(true);
    setError("");
    try {
      await adapter.deleteProgressPoint(point.id);
      setPoints((p) => p.filter((item) => item.id !== point.id));
      setMessage("Progress record deleted.");
    } catch {
      setError("Could not delete the progress record. Try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card" data-sample-editor>
      <h2>Actual progress</h2>
      <p style={{ color: "var(--text-secondary)" }}>Shared across plans.</p>
      {loading && <p role="status">Loading progress…</p>}
      {chart && (
        <svg
          viewBox="0 0 900 275"
          width="100%"
          role="img"
          aria-label="Recorded net worth over time"
          style={{ maxHeight: 320 }}
        >
          {chart.y.ticks(5).map((t) => (
            <g key={t}>
              <line
                x1={80}
                x2={860}
                y1={chart.y(t)}
                y2={chart.y(t)}
                stroke="var(--surface-border-strong)"
              />
              <text
                x={72}
                y={chart.y(t) + 4}
                textAnchor="end"
                fill="var(--text-secondary)"
                fontSize={12}
              >
                {compactCurrency(t)}
              </text>
            </g>
          ))}
          <path d={chart.path ?? ""} fill="none" stroke="var(--brand-primary)" strokeWidth={2} />
          {ordered.map((p) => (
            <circle
              key={p.id}
              cx={chart.x(new Date(`${p.recorded_date}T12:00:00`))}
              cy={chart.y(p.net_worth)}
              r={4}
              fill="var(--brand-primary)"
            >
              <title>
                {p.recorded_date}: {compactCurrency(p.net_worth)}
              </title>
            </circle>
          ))}
          {ordered[0].recorded_date === ordered[ordered.length - 1].recorded_date ? (
            <text x={470} y={260} textAnchor="middle" fill="var(--text-secondary)" fontSize={12}>
              {ordered[0].recorded_date}
            </text>
          ) : (
            <>
              <text x={80} y={260} fill="var(--text-secondary)" fontSize={12}>
                {ordered[0].recorded_date}
              </text>
              <text x={860} y={260} textAnchor="end" fill="var(--text-secondary)" fontSize={12}>
                {ordered[ordered.length - 1].recorded_date}
              </text>
            </>
          )}
        </svg>
      )}
      <InlineValidity>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <fieldset
            disabled={busy || loading}
            style={{
              border: 0,
              padding: 0,
              display: "flex",
              flexWrap: "wrap",
              gap: 12,
              alignItems: "end",
            }}
          >
            <label>
              Record date
              <input
                type="date"
                required
                max={localDate()}
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
            <label>
              {moneyLabel("Cash and investments ($)")}
              <MoneyInput min="0" step="0.01" required value={liquid} onValueChange={setLiquid} />
            </label>
            <label>
              {moneyLabel("Property and other assets ($)")}
              <MoneyInput
                min="0"
                step="0.01"
                required
                value={property}
                onValueChange={setProperty}
              />
            </label>
            <label>
              {moneyLabel("Total debt ($)")}
              <MoneyInput min="0" step="0.01" required value={debt} onValueChange={setDebt} />
            </label>
            <button type="submit">{busy ? "Saving…" : "Record progress"}</button>
          </fieldset>
        </form>
      </InlineValidity>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {!loading && !points.length && <p>No observations yet.</p>}
      {!!points.length && (
        <div style={{ overflowX: "auto", marginTop: 20 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                <th>Date</th>
                <th>Recorded net worth</th>
                <th>Source</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {[...ordered].reverse().map((p) => (
                <tr key={p.id}>
                  <td>{p.recorded_date}</td>
                  <td>{fullCurrency(p.net_worth)}</td>
                  <td>{p.auto_logged ? "Automatic" : "Manual"}</td>
                  <td>
                    <button
                      disabled={busy}
                      onClick={() => void remove(p)}
                      aria-label={`Delete record ${p.recorded_date}`}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
