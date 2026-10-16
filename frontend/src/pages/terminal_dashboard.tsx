import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useAuthStore } from "@/stores/auth_store";
import { usePlanStore } from "@/stores/plan_store";
import { StorageProvider } from "@/storage/context";
import { resolveFinancialIndependence } from "@/utils/financial_independence";
import { useFiEstimateHidden } from "@/stores/fi_estimate_store";
import { planStatus } from "@/utils/plan_status";
import { compactCurrency, fullCurrency } from "@/utils/format";
import { usePlanDisplayCurrency } from "@/components/intl/use_display_currency";

// ── palette ──────────────────────────────────────────────────────────
const C = {
  bg: "#f5f0e8",
  card: "#faf7f2",
  border: "#e8dfd0",
  text: "#5c4a3a",
  muted: "#8b7355",
  dim: "#b8a88a",
  bar1: "#c4a882",
  bar2: "#b8a070",
  bar3: "#a89060",
  bar4: "#987850",
  green: "#6b8f5e",
  red: "#a85c4a",
} as const;

const FONT = '"SF Mono", "Fira Code", "JetBrains Mono", monospace';

// ── floating ticker symbols ──────────────────────────────────────────
const TICKER_SYMBOLS = [
  "SPY",
  "QQQ",
  "VTI",
  "BND",
  "AAPL",
  "MSFT",
  "GOOG",
  "AMZN",
  "NVDA",
  "META",
  "TSLA",
  "JPM",
  "V",
  "WMT",
  "DIS",
  "NFLX",
  "AMD",
  "INTC",
  "BA",
  "GS",
  "BRK.B",
  "UNH",
  "HD",
  "PG",
  "COST",
  "ABBV",
  "CRM",
  "AVGO",
  "LLY",
  "XOM",
];

interface FloatingTicker {
  id: number;
  symbol: string;
  x: number;
  y: number;
  speed: number;
  opacity: number;
  change: number;
  fontSize: number;
}

function useFloatingTickers(count: number = 18) {
  const [tickers, setTickers] = useState<FloatingTicker[]>([]);
  const frameRef = useRef<number>(0);
  const tickersRef = useRef<FloatingTicker[]>([]);

  useEffect(() => {
    const initial: FloatingTicker[] = Array.from({ length: count }, (_, i) => ({
      id: i,
      symbol: TICKER_SYMBOLS[i % TICKER_SYMBOLS.length],
      x: Math.random() * 100,
      y: Math.random() * 100,
      speed: 0.008 + Math.random() * 0.02,
      opacity: 0.04 + Math.random() * 0.06,
      change: (Math.random() - 0.45) * 8,
      fontSize: 10 + Math.random() * 4,
    }));
    tickersRef.current = initial;
    setTickers(initial);

    let lastTime = performance.now();
    const animate = (time: number) => {
      const dt = Math.min(time - lastTime, 50);
      lastTime = time;
      const updated = tickersRef.current.map((t) => {
        let newY = t.y - t.speed * dt * 0.06;
        let newChange = t.change;
        if (newY < -5) {
          newY = 105;
          newChange = (Math.random() - 0.45) * 8;
        }
        return { ...t, y: newY, change: newChange };
      });
      tickersRef.current = updated;
      setTickers(updated);
      frameRef.current = requestAnimationFrame(animate);
    };
    frameRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frameRef.current);
  }, [count]);

  return tickers;
}

// ── scrolling ticker tape data ───────────────────────────────────────
const TAPE_ITEMS = [
  { sym: "SPY", price: "587.32", chg: "+1.24%" },
  { sym: "QQQ", price: "512.18", chg: "+0.87%" },
  { sym: "DJI", price: "43,821", chg: "+0.34%" },
  { sym: "VIX", price: "14.23", chg: "-3.12%" },
  { sym: "TNX", price: "4.31", chg: "+0.02%" },
  { sym: "BTC", price: "97,432", chg: "+2.18%" },
  { sym: "GLD", price: "238.10", chg: "+0.44%" },
  { sym: "NVDA", price: "924.50", chg: "+3.41%" },
  { sym: "AAPL", price: "198.11", chg: "-0.22%" },
  { sym: "MSFT", price: "467.55", chg: "+0.91%" },
  { sym: "TSLA", price: "312.80", chg: "-1.55%" },
  { sym: "AMZN", price: "219.34", chg: "+1.03%" },
  { sym: "META", price: "582.91", chg: "+0.67%" },
  { sym: "GOOG", price: "178.40", chg: "+0.38%" },
  { sym: "JPM", price: "221.76", chg: "+0.52%" },
  { sym: "V", price: "308.42", chg: "+0.19%" },
];

// ── hover hook ───────────────────────────────────────────────────────
function useHover() {
  const [hovered, setHovered] = useState(false);
  const bind = useMemo(
    () => ({
      onMouseEnter: () => setHovered(true),
      onMouseLeave: () => setHovered(false),
    }),
    [],
  );
  return [hovered, bind] as const;
}

// ── helpers ──────────────────────────────────────────────────────────
// Money prints in the open plan's currency through the shared formatters.
const fmt = compactCurrency;
const fmtFull = fullCurrency;

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

// ── bar component ────────────────────────────────────────────────────
const BAR_COLORS = [C.bar1, C.bar2, C.bar3, C.bar4];

function HBar({
  label,
  value,
  maxValue,
  index = 0,
}: {
  label: string;
  value: number;
  maxValue: number;
  index?: number;
}) {
  const w = maxValue > 0 ? Math.max((value / maxValue) * 100, 1) : 0;
  const [hovered, bind] = useHover();
  const barColor = BAR_COLORS[index % BAR_COLORS.length];
  return (
    <div
      {...bind}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: 4,
        padding: "2px 4px",
        marginLeft: -4,
        marginRight: -4,
        borderRadius: 3,
        background: hovered ? C.border + "66" : "transparent",
        transition: "background 0.2s ease",
        cursor: "default",
      }}
    >
      <span
        style={{
          color: hovered ? C.text : C.muted,
          fontSize: 11,
          width: 60,
          textAlign: "right",
          flexShrink: 0,
          transition: "color 0.2s ease",
        }}
      >
        {label}
      </span>
      <div
        style={{ flex: 1, background: C.border, borderRadius: 2, height: 16, overflow: "hidden" }}
      >
        <div
          style={{
            width: `${w}%`,
            background: barColor,
            height: "100%",
            borderRadius: 2,
            transition:
              "width 0.6s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.2s ease, filter 0.2s ease",
            boxShadow: hovered
              ? `0 0 8px ${barColor}66, inset 0 0 4px rgba(255,255,255,0.15)`
              : "none",
            filter: hovered ? "brightness(1.12)" : "brightness(1)",
          }}
        />
      </div>
      <span
        style={{
          color: hovered ? C.text : C.text,
          fontSize: 11,
          width: 72,
          textAlign: "right",
          flexShrink: 0,
          fontWeight: hovered ? 700 : 400,
          transition: "font-weight 0.2s ease",
        }}
      >
        {fmtFull(value)}
      </span>
    </div>
  );
}

// ── section header ───────────────────────────────────────────────────
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const [hovered, bind] = useHover();
  return (
    <div
      {...bind}
      style={{
        background: C.card,
        border: `1px solid ${hovered ? C.bar1 + "88" : C.border}`,
        borderRadius: 5,
        padding: "14px 18px",
        marginBottom: 12,
        transition: "border-color 0.3s ease, box-shadow 0.3s ease, transform 0.2s ease",
        boxShadow: hovered ? `0 2px 12px ${C.bar2}22` : "none",
        transform: hovered ? "translateY(-1px)" : "translateY(0)",
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: hovered ? C.text : C.muted,
          letterSpacing: 1.5,
          marginBottom: 12,
          transition: "color 0.2s ease",
        }}
      >
        [{title}]
      </div>
      {children}
    </div>
  );
}

// ── clock hook ───────────────────────────────────────────────────────
function useClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

// ── inner dashboard (needs store) ────────────────────────────────────
function Dashboard() {
  const plan = usePlanStore((s) => s.plan);
  const plans = usePlanStore((s) => s.plans);
  const simulation = usePlanStore((s) => s.simulation);
  const loadPlans = usePlanStore((s) => s.loadPlans);
  const loadPlan = usePlanStore((s) => s.loadPlan);
  const now = useClock();
  const fiEstimateHidden = useFiEstimateHidden(plan?.id);
  usePlanDisplayCurrency(plan?.currency);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadPlans().then(() => setLoaded(true));
  }, [loadPlans]);

  useEffect(() => {
    if (loaded && plans.length > 0 && !plan) {
      loadPlan(plans[0].id);
    }
  }, [loaded, loadPlan, plan, plans]);

  const snapshots = simulation?.yearly_snapshots ?? [];
  const first = snapshots[0];
  const last = snapshots[snapshots.length - 1];
  const hasData = snapshots.length > 0;

  // net worth change pct
  const nwChange =
    hasData && first.net_worth !== 0
      ? ((last.net_worth - first.net_worth) / Math.abs(first.net_worth)) * 100
      : 0;

  const fireYear = resolveFinancialIndependence(plan, simulation, fiEstimateHidden)?.year ?? null;
  const fireYears = hasData && fireYear != null ? fireYear - first.year : null;
  const projectionYears = hasData ? last.year - first.year : 0;

  // savings rate from latest
  const savingsRate =
    hasData && last.gross_income > 0 ? Math.max(last.net_cash_flow, 0) / last.gross_income : 0;

  // sample every ~5 years for bar chart
  const barSnapshots =
    snapshots.length <= 8
      ? snapshots
      : snapshots.filter(
          (_, i) =>
            i % Math.max(1, Math.floor(snapshots.length / 8)) === 0 || i === snapshots.length - 1,
        );

  const maxNW = hasData ? Math.max(...barSnapshots.map((s) => s.net_worth), 1) : 1;

  // accounts from last snapshot
  const accounts = hasData ? Object.entries(last.accounts) : [];
  const maxAcct = accounts.length > 0 ? Math.max(...accounts.map(([, v]) => v), 1) : 1;

  // time string
  const timeStr = now.toLocaleTimeString("en-US", { hour12: false });
  const dateStr = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, "0")}.${String(now.getDate()).padStart(2, "0")}`;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  // income & tax from first snapshot (current year) with trajectory to last
  const income = hasData ? (first.calendar_year_gross_income ?? first.gross_income) : 0;
  const fedTax = hasData ? first.federal_tax : 0;
  const stateTax = hasData ? first.state_tax : 0;
  const ficaTax = hasData ? first.fica_tax : 0;
  const cgTax = hasData ? first.capital_gains_tax : 0;
  const totalTax = hasData ? first.taxes : 0;
  const netIncome = income - totalTax;
  const maxTaxBar = Math.max(income, totalTax, 1);

  // income change over projection
  const incomeChange =
    hasData && income > 0
      ? (((last.calendar_year_gross_income ?? last.gross_income) - income) / income) * 100
      : 0;
  const taxChange =
    hasData && first.taxes > 0 ? ((last.taxes - first.taxes) / first.taxes) * 100 : 0;

  // status
  const status = hasData ? planStatus(simulation) : null;

  // floating tickers
  const floatingTickers = useFloatingTickers(18);

  // hoverable cash flow stat
  const CashFlowStat = useCallback(function CashFlowStat({
    label,
    value,
    color,
    prefix,
  }: {
    label: string;
    value: number;
    color: string;
    prefix: string;
  }) {
    const [h, b] = useHover();
    return (
      <div {...b} style={{ cursor: "default" }}>
        <div
          style={{
            fontSize: 11,
            color: h ? C.text : C.muted,
            transition: "color 0.2s ease",
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            color,
            transition: "transform 0.2s ease, text-shadow 0.2s ease",
            transform: h ? "scale(1.05)" : "scale(1)",
            transformOrigin: "left center",
            textShadow: h ? `0 0 12px ${color}44` : "none",
          }}
        >
          {prefix}
          {fmtFull(value)}
        </div>
      </div>
    );
  }, []);

  // hoverable account row
  const AccountRow = useCallback(function AccountRow({
    name,
    value,
    maxVal,
    idx,
    isLast,
  }: {
    name: string;
    value: number;
    maxVal: number;
    idx: number;
    isLast: boolean;
  }) {
    const [h, b] = useHover();
    const barColor = BAR_COLORS[idx % BAR_COLORS.length];
    return (
      <div
        {...b}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "4px 4px",
          marginLeft: -4,
          marginRight: -4,
          borderBottom: isLast ? "none" : `1px solid ${C.border}`,
          borderRadius: 3,
          background: h ? C.border + "44" : "transparent",
          transition: "background 0.2s ease",
          cursor: "default",
        }}
      >
        <span
          style={{
            color: h ? C.text : C.muted,
            fontSize: 11,
            width: 140,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flexShrink: 0,
            transition: "color 0.2s ease",
          }}
        >
          {name.toUpperCase().replace(/ /g, "_")}
        </span>
        <div
          style={{ flex: 1, background: C.border, borderRadius: 2, height: 12, overflow: "hidden" }}
        >
          <div
            style={{
              width: `${Math.max((value / maxVal) * 100, 1)}%`,
              background: barColor,
              height: "100%",
              borderRadius: 2,
              transition:
                "width 0.6s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.2s ease, filter 0.2s ease",
              boxShadow: h ? `0 0 6px ${barColor}55` : "none",
              filter: h ? "brightness(1.15)" : "brightness(1)",
            }}
          />
        </div>
        <span
          style={{
            color: C.text,
            fontSize: 11,
            width: 90,
            textAlign: "right",
            flexShrink: 0,
            fontWeight: h ? 700 : 400,
            transition: "font-weight 0.15s ease",
          }}
        >
          {fmtFull(value)}
        </span>
      </div>
    );
  }, []);

  // hoverable mini cash flow bar
  const FlowBar = useCallback(function FlowBar({
    s,
    maxFlow,
  }: {
    s: (typeof snapshots)[0];
    maxFlow: number;
  }) {
    const [h, b] = useHover();
    const hVal = (Math.abs(s.net_cash_flow) / maxFlow) * 36;
    const isPos = s.net_cash_flow >= 0;
    return (
      <div
        {...b}
        title={`${s.year}: ${fmtFull(s.net_cash_flow)}`}
        style={{
          flex: 1,
          height: Math.max(hVal, 2),
          background: isPos ? C.bar2 : C.red + "88",
          borderRadius: "2px 2px 0 0",
          alignSelf: "flex-end",
          transition: "transform 0.15s ease, filter 0.15s ease, box-shadow 0.15s ease",
          transform: h ? "scaleY(1.25)" : "scaleY(1)",
          transformOrigin: "bottom",
          filter: h ? "brightness(1.2)" : "brightness(1)",
          boxShadow: h ? `0 -2px 6px ${isPos ? C.bar2 : C.red}44` : "none",
          cursor: "default",
        }}
      />
    );
  }, []);

  const maxFlow = hasData ? Math.max(...snapshots.map((x) => Math.abs(x.net_cash_flow)), 1) : 1;

  return (
    <div
      style={{
        fontFamily: FONT,
        background: C.bg,
        color: C.text,
        minHeight: "100vh",
        fontSize: 13,
        lineHeight: 1.5,
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* ── FLOATING TICKERS BACKGROUND ──────────────────── */}
      <div
        style={{
          position: "fixed",
          inset: 0,
          pointerEvents: "none",
          zIndex: 0,
          overflow: "hidden",
        }}
      >
        {floatingTickers.map((t) => (
          <div
            key={t.id}
            style={{
              position: "absolute",
              left: `${t.x}%`,
              top: `${t.y}%`,
              fontSize: t.fontSize,
              fontFamily: FONT,
              fontWeight: 600,
              color: t.change >= 0 ? C.green : C.red,
              opacity: t.opacity,
              whiteSpace: "nowrap",
              letterSpacing: 0.5,
              userSelect: "none",
              willChange: "top",
            }}
          >
            {t.symbol}{" "}
            <span style={{ fontSize: t.fontSize - 2 }}>
              {t.change >= 0 ? "+" : ""}
              {t.change.toFixed(2)}%
            </span>
          </div>
        ))}
      </div>

      {/* ── TITLE BAR ────────────────────────────────────── */}
      <div
        style={{
          background: C.card,
          borderBottom: `1px solid ${C.border}`,
          padding: "10px 20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          position: "relative",
          zIndex: 2,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span
            style={{
              color: C.green,
              fontSize: 10,
              animation: "statusPulse 2s ease-in-out infinite",
            }}
          >
            ●
          </span>
          <span style={{ fontWeight: 700, letterSpacing: 1.5, fontSize: 13 }}>COASTMATH</span>
          <span style={{ color: C.dim, fontSize: 11 }}>&lt;ANALYTICS&gt;</span>
          <span
            style={{
              background: C.border,
              color: C.muted,
              fontSize: 10,
              padding: "2px 6px",
              borderRadius: 3,
              letterSpacing: 1,
            }}
          >
            ENV:PROD
          </span>
          <span
            style={{
              background: C.green + "22",
              color: C.green,
              fontSize: 10,
              padding: "2px 6px",
              borderRadius: 3,
              letterSpacing: 1,
              animation: "livePulse 3s ease-in-out infinite",
            }}
          >
            STREAM:LIVE
          </span>
        </div>
        <div style={{ display: "flex", gap: 16, color: C.muted, fontSize: 11 }}>
          <span>{dateStr}</span>
          <span style={{ fontVariantNumeric: "tabular-nums" }}>{timeStr}</span>
          <span style={{ color: C.dim }}>{tz}</span>
        </div>
      </div>

      {/* ── SCROLLING TICKER TAPE ────────────────────────── */}
      <div
        style={{
          borderBottom: `1px solid ${C.border}`,
          background: C.card,
          overflow: "hidden",
          position: "relative",
          zIndex: 2,
          height: 26,
        }}
      >
        <div
          style={{
            display: "flex",
            gap: 32,
            fontSize: 10,
            fontFamily: FONT,
            letterSpacing: 0.5,
            whiteSpace: "nowrap",
            animation: "tickerScroll 40s linear infinite",
            paddingTop: 6,
          }}
        >
          {[...TAPE_ITEMS, ...TAPE_ITEMS].map((item, i) => (
            <span key={i} style={{ display: "inline-flex", gap: 6 }}>
              <span style={{ color: C.muted, fontWeight: 700 }}>{item.sym}</span>
              <span style={{ color: C.text }}>{item.price}</span>
              <span style={{ color: item.chg.startsWith("+") ? C.green : C.red }}>{item.chg}</span>
            </span>
          ))}
        </div>
      </div>

      {/* ── STATS TICKER ─────────────────────────────────── */}
      <div
        style={{
          padding: "8px 20px",
          display: "flex",
          gap: 24,
          fontSize: 11,
          color: C.muted,
          borderBottom: `1px solid ${C.border}`,
          background: C.card,
          flexWrap: "wrap",
          position: "relative",
          zIndex: 2,
        }}
      >
        {hasData ? (
          <>
            <span>
              NW <span style={{ color: C.text, fontWeight: 700 }}>{fmt(last.net_worth)}</span>{" "}
              <span
                style={{
                  color: nwChange >= 0 ? C.green : C.red,
                  animation: "fadeFlicker 4s ease-in-out infinite",
                }}
              >
                {nwChange >= 0 ? "▲" : "▼"}
                {Math.abs(nwChange).toFixed(1)}%
              </span>
            </span>
            <span style={{ color: C.dim }}>|</span>
            <span>
              FIRE{" "}
              <span style={{ color: C.text, fontWeight: 700 }}>
                {fireYears === null ? "N/A" : `${fireYears} yrs`}
              </span>
            </span>
            <span style={{ color: C.dim }}>|</span>
            <span>
              SAVINGS{" "}
              <span style={{ color: C.text, fontWeight: 700 }}>
                {(savingsRate * 100).toFixed(1)}%
              </span>
            </span>
            <span style={{ color: C.dim }}>|</span>
            <span>
              TAX_RATE{" "}
              <span style={{ color: C.text, fontWeight: 700 }}>{pct(last.effective_rate)}</span>
            </span>
            <span style={{ color: C.dim }}>|</span>
            <span>
              STATUS:{" "}
              <span
                style={{
                  color: status?.tone === "success" ? C.green : C.red,
                  fontWeight: 700,
                  animation:
                    status?.tone === "success"
                      ? "statusGlow 3s ease-in-out infinite"
                      : "alertPulse 1.5s ease-in-out infinite",
                }}
              >
                {status?.label}
              </span>
            </span>
          </>
        ) : (
          <span style={{ color: C.dim, animation: "fadeFlicker 2s ease-in-out infinite" }}>
            AWAITING_DATA ...
          </span>
        )}
      </div>

      {/* ── MAIN CONTENT ─────────────────────────────────── */}
      <div
        style={{
          padding: "16px 20px",
          maxWidth: 1100,
          margin: "0 auto",
          position: "relative",
          zIndex: 1,
        }}
      >
        {/* NET WORTH */}
        <Section title="NET_WORTH">
          {hasData ? (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 14 }}>
                <span style={{ fontSize: 28, fontWeight: 700, color: C.text }}>
                  {fmtFull(last.net_worth)}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    color: nwChange >= 0 ? C.green : C.red,
                    animation: "fadeFlicker 4s ease-in-out infinite",
                  }}
                >
                  {nwChange >= 0 ? "+" : ""}
                  {nwChange.toFixed(1)}% over {projectionYears}yr projection
                </span>
              </div>
              {barSnapshots.map((s, i) => (
                <HBar
                  key={s.year}
                  label={String(s.year)}
                  value={s.net_worth}
                  maxValue={maxNW}
                  index={i}
                />
              ))}
            </>
          ) : (
            <div style={{ color: C.dim, padding: "20px 0" }}>NO_DATA — run simulation first</div>
          )}
        </Section>

        {/* INCOME vs TAX */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Section title={`INCOME_${first?.year ?? ""}`}>
            {hasData ? (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
                  <span style={{ fontSize: 22, fontWeight: 700 }}>{fmtFull(income)}</span>
                  <span style={{ fontSize: 11, color: C.muted, fontWeight: 400 }}>
                    gross @ age {first.age}
                  </span>
                </div>
                <HBar label="CAL_GROSS" value={income} maxValue={maxTaxBar} index={0} />
                <HBar label="AFTER_TAX" value={netIncome} maxValue={maxTaxBar} index={1} />
                <div style={{ marginTop: 8, fontSize: 11, color: C.dim }}>
                  EFF_RATE: {pct(first.effective_rate)} &nbsp;|&nbsp; MARG:{" "}
                  {pct(first.marginal_rate)}
                </div>
                <div style={{ marginTop: 4, fontSize: 10, color: C.dim }}>
                  BY_{last.year}: {fmtFull(last.calendar_year_gross_income ?? last.gross_income)}{" "}
                  <span style={{ color: incomeChange >= 0 ? C.green : C.red }}>
                    ({incomeChange >= 0 ? "+" : ""}
                    {incomeChange.toFixed(0)}%)
                  </span>
                </div>
              </>
            ) : (
              <div style={{ color: C.dim, padding: "20px 0" }}>NO_DATA</div>
            )}
          </Section>

          <Section title={`TAX_${first?.year ?? ""}`}>
            {hasData ? (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
                  <span style={{ fontSize: 22, fontWeight: 700 }}>{fmtFull(totalTax)}</span>
                  <span style={{ fontSize: 11, color: C.muted, fontWeight: 400 }}>
                    total @ age {first.age}
                  </span>
                </div>
                <HBar label="FED" value={fedTax} maxValue={totalTax || 1} index={0} />
                <HBar label="STATE" value={stateTax} maxValue={totalTax || 1} index={1} />
                <HBar label="FICA" value={ficaTax} maxValue={totalTax || 1} index={2} />
                <HBar label="CAP_GN" value={cgTax} maxValue={totalTax || 1} index={3} />
                <div style={{ marginTop: 8, fontSize: 10, color: C.dim }}>
                  BY_{last.year}: {fmtFull(last.taxes)}{" "}
                  <span style={{ color: taxChange >= 0 ? C.red : C.green }}>
                    ({taxChange >= 0 ? "+" : ""}
                    {taxChange.toFixed(0)}%)
                  </span>
                </div>
              </>
            ) : (
              <div style={{ color: C.dim, padding: "20px 0" }}>NO_DATA</div>
            )}
          </Section>
        </div>

        {/* ACCOUNTS */}
        <Section title="ACCOUNTS">
          {hasData && accounts.length > 0 ? (
            <div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr",
                  gap: 2,
                }}
              >
                {accounts.map(([name, value], i) => (
                  <AccountRow
                    key={name}
                    name={name}
                    value={value}
                    maxVal={maxAcct}
                    idx={i}
                    isLast={i === accounts.length - 1}
                  />
                ))}
              </div>
              <div style={{ marginTop: 10, fontSize: 11, color: C.dim }}>
                TOTAL: {fmtFull(Object.values(last.accounts).reduce((a, b) => a + b, 0))}
                &nbsp;&nbsp;|&nbsp;&nbsp; REAL_ASSETS: {fmtFull(last.real_assets_value)}
                &nbsp;&nbsp;|&nbsp;&nbsp; LIABILITIES: {fmtFull(last.liabilities_balance)}
              </div>
            </div>
          ) : (
            <div style={{ color: C.dim, padding: "20px 0" }}>NO_DATA</div>
          )}
        </Section>

        {/* CASH FLOW */}
        <Section title="CASH_FLOW">
          {hasData ? (
            <div>
              <div style={{ display: "flex", gap: 32, marginBottom: 12 }}>
                <CashFlowStat label="INCOME" value={last.gross_income} color={C.green} prefix="+" />
                <CashFlowStat label="EXPENSES" value={last.expenses} color={C.red} prefix="-" />
                <CashFlowStat
                  label={last.post_start_taxes != null ? "TAXES_AFTER_START" : "FULL_YEAR_TAXES"}
                  value={last.post_start_taxes ?? last.taxes}
                  color={C.red}
                  prefix="-"
                />
                <CashFlowStat
                  label="NET_FLOW"
                  value={Math.abs(last.net_cash_flow)}
                  color={last.net_cash_flow >= 0 ? C.green : C.red}
                  prefix={last.net_cash_flow >= 0 ? "+" : "-"}
                />
              </div>
              {/* mini year-over-year flow bars */}
              <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 40 }}>
                {snapshots.map((s, i) => (
                  <FlowBar key={i} s={s} maxFlow={maxFlow} />
                ))}
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 10,
                  color: C.dim,
                  marginTop: 2,
                }}
              >
                <span>{first.year}</span>
                <span>{last.year}</span>
              </div>
            </div>
          ) : (
            <div style={{ color: C.dim, padding: "20px 0" }}>NO_DATA</div>
          )}
        </Section>
      </div>

      {/* ── TERMINAL PROMPT FOOTER ────────────────────────── */}
      <div
        style={{
          borderTop: `1px solid ${C.border}`,
          background: C.card,
          padding: "10px 20px",
          fontSize: 12,
          color: C.muted,
          position: "sticky",
          bottom: 0,
          zIndex: 2,
        }}
      >
        <span style={{ color: C.green }}>{">"}</span>{" "}
        <span style={{ color: C.text }}>coastmath</span>
        <span style={{ color: C.dim }}>@terminal:~$</span>{" "}
        <span style={{ color: C.muted }}>live --stream</span>
        <span
          style={{
            display: "inline-block",
            width: 7,
            height: 14,
            background: C.text,
            marginLeft: 4,
            verticalAlign: "text-bottom",
            animation: "termBlink 1s step-end infinite",
          }}
        />
      </div>

      {/* ── ALL ANIMATIONS ──────────────────────────────── */}
      <style>{`
        @keyframes termBlink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        @keyframes statusPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes livePulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        @keyframes fadeFlicker {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
        @keyframes statusGlow {
          0%, 100% { text-shadow: 0 0 0px transparent; }
          50% { text-shadow: 0 0 6px ${C.green}66; }
        }
        @keyframes alertPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        @keyframes tickerScroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}

// ── exported page (wraps with storage provider) ──────────────────────
export function TerminalDashboard() {
  const { user, isLoading, error, ensureSession } = useAuthStore();
  useEffect(() => {
    void ensureSession();
  }, [ensureSession]);
  if (isLoading) return <p role="status">Opening planner…</p>;
  if (error)
    return (
      <main>
        <p role="alert">{error}</p>
        <button type="button" onClick={() => void ensureSession()}>
          Retry opening planner
        </button>
      </main>
    );
  // Signed out, the terminal shows the read-only sample plan; it has no controls to guard.
  return (
    <StorageProvider sample={!user}>
      <Dashboard />
    </StorageProvider>
  );
}
