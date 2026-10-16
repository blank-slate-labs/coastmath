import { useMemo, useState } from "react";
import { sankey, sankeyLinkHorizontal, sankeyJustify } from "d3-sankey";

import {
  ChartLegend,
  ChartTable,
  TooltipRow,
  VizTooltip,
  placeTooltip,
  type LegendEntry,
} from "@/components/chart_chrome";
import type { CashFlowBreakdown, CashFlowGraph, CashFlowGroup } from "@/types/plan";
import { compactCurrency, fullCurrency, pct } from "@/utils/format";
import { useChartSize } from "@/utils/use_chart_size";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SankeyChartProps {
  breakdown: CashFlowBreakdown;
  selectedYear: number;
  width?: number;
  height?: number;
}

interface SankeyNode {
  name: string;
  group: Group;
}

interface SankeyLink {
  source: number;
  target: number;
  value: number;
}

interface LayoutNode extends SankeyNode {
  index: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  value: number;
}

interface LayoutLink {
  index: number;
  source: LayoutNode;
  target: LayoutNode;
  value: number;
  width: number;
}

// ---------------------------------------------------------------------------
// Color: five identity groups + neutral hubs. Slots are the validated viz
// palette in fixed order; the shortfall node wears the status token.
// ---------------------------------------------------------------------------

type Group = CashFlowGroup;

const GROUPS: Record<Group, { label: string; color: string }> = {
  income: { label: "Income", color: "var(--viz-1)" },
  tax: { label: "Taxes", color: "var(--viz-2)" },
  saving: { label: "Savings & investments", color: "var(--viz-3)" },
  spending: { label: "Spending", color: "var(--viz-4)" },
  shortfall: { label: "Shortfall", color: "var(--viz-critical)" },
  hub: { label: "", color: "var(--viz-hub)" },
};

const isHub = (node: SankeyNode): boolean => node.group === "hub";

const NODE_WIDTH = 12;
const NODE_PADDING = 14;
const LINK_OPACITY = 0.3;
const MARGIN_DESKTOP = { top: 28, right: 150, bottom: 12, left: 150 };
const MARGIN_MOBILE = { top: 24, right: 20, bottom: 12, left: 20 };
const MOBILE_LABEL_LIMIT = 12;

// An account the plan left unnamed is served by its type ("roth_ira").
const displayNodeName = (name: string): string => {
  const cleaned = name.replace(/_/g, " ").trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
};

const truncateLabel = (label: string, maxLength: number): string =>
  label.length > maxLength ? `${label.slice(0, maxLength - 1)}…` : label;

// ---------------------------------------------------------------------------
// The service routes every flow (backend coastmath/engine/cash_flow_graph.py):
// sources → Gross income → After-tax cash → destinations, with a paycheck's
// deferrals and taxes leaving gross income first. This only indexes it.
// ---------------------------------------------------------------------------

export function buildSankeyData(graph: CashFlowGraph) {
  const index = new Map(graph.nodes.map((node, i) => [node.id, i]));
  return {
    nodes: graph.nodes.map(({ name, group }): SankeyNode => ({ name, group })),
    links: graph.links.map(({ source, target, amount }): SankeyLink => ({
      source: index.get(source)!,
      target: index.get(target)!,
      value: amount,
    })),
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type Hover = { kind: "node"; index: number } | { kind: "link"; index: number } | null;

export default function SankeyChart({
  breakdown,
  selectedYear,
  width: propWidth,
  height: propHeight,
}: SankeyChartProps) {
  const { ref: containerRef, width: measuredWidth } = useChartSize(960, 400);
  const [hoverContext, setHoverContext] = useState<{
    target: Hover;
    year: number;
    breakdown: CashFlowBreakdown;
  } | null>(null);
  // Node indexes can refer to entirely different flows after scrubbing or rerunning.
  const hover =
    hoverContext?.year === selectedYear && hoverContext.breakdown === breakdown
      ? hoverContext.target
      : null;
  const setHover = (target: Hover) =>
    setHoverContext(target ? { target, year: selectedYear, breakdown } : null);
  const [view, setView] = useState<"list" | "diagram" | null>(null);

  const w = propWidth ?? measuredWidth;
  const h = propHeight ?? 400;
  const isMobile = w > 0 && w < 560;
  const showList = view === "list" || (view === null && isMobile);
  const MARGIN = isMobile ? MARGIN_MOBILE : MARGIN_DESKTOP;
  const innerWidth = Math.max(w - MARGIN.left - MARGIN.right, 0);
  const innerHeight = Math.max(h - MARGIN.top - MARGIN.bottom, 0);

  const layout = useMemo(() => {
    if (innerWidth <= 0 || innerHeight <= 0) return null;
    if (!breakdown.graph) return null;
    const { nodes, links } = buildSankeyData(breakdown.graph);
    if (nodes.length === 0 || links.length === 0) return null;

    const generator = sankey<SankeyNode, SankeyLink>()
      .nodeWidth(NODE_WIDTH)
      .nodePadding(NODE_PADDING)
      .nodeAlign(sankeyJustify)
      .extent([
        [0, 0],
        [innerWidth, innerHeight],
      ]);

    const graph = generator({
      nodes: nodes.map((n) => ({ ...n })),
      links: links.map((l) => ({ ...l })),
    });
    return {
      nodes: graph.nodes as unknown as LayoutNode[],
      links: graph.links as unknown as LayoutLink[],
    };
  }, [breakdown, innerWidth, innerHeight]);

  const linkPath = sankeyLinkHorizontal();

  const hasActivity = (breakdown?.graph?.links.length ?? 0) > 0;

  if (!hasActivity) {
    return (
      <div
        ref={containerRef}
        style={{
          width: propWidth ?? "100%",
          height: h,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-tertiary)",
          fontSize: 14,
        }}
      >
        No cash flow data for {selectedYear}
      </div>
    );
  }

  const nodes = layout?.nodes ?? [];
  const links = layout?.links ?? [];

  const presentGroups = new Set<Group>(nodes.map((n) => n.group));
  const legendEntries: LegendEntry[] = (Object.keys(GROUPS) as Group[])
    .filter((g) => g !== "hub" && presentGroups.has(g))
    .map((g) => ({ label: GROUPS[g].label, color: GROUPS[g].color, kind: "swatch" as const }));

  // Money entering the year: income of any kind, withdrawals and refunds — the base for shares.
  // Account-to-account transfers move money already counted.
  const inflowTotal = links
    .filter((link) => !isHub(link.source) && (isHub(link.target) || link.source.group === "income"))
    .reduce((sum, link) => sum + link.value, 0);
  const share = (value: number): string => (inflowTotal > 0 ? pct(value / inflowTotal, 0) : "—");

  const isPassThrough = (link: LayoutLink): boolean => isHub(link.source) && isHub(link.target);
  const linkColor = (link: LayoutLink): string => {
    if (isPassThrough(link)) return GROUPS.income.color;
    return isHub(link.source) ? GROUPS[link.target.group].color : GROUPS[link.source.group].color;
  };
  const linkOpacity = (link: LayoutLink): number => (isPassThrough(link) ? 0.14 : LINK_OPACITY);

  const hoveredNode = hover?.kind === "node" ? hover.index : null;
  const hoveredLink = hover?.kind === "link" ? hover.index : null;
  const isLinkActive = (link: LayoutLink): boolean => {
    if (hoveredLink !== null) return link.index === hoveredLink;
    if (hoveredNode !== null)
      return link.source.index === hoveredNode || link.target.index === hoveredNode;
    return true;
  };
  const isNodeActive = (node: LayoutNode): boolean => {
    if (hoveredNode !== null) {
      return (
        node.index === hoveredNode ||
        links.some(
          (l) =>
            (l.source.index === hoveredNode && l.target.index === node.index) ||
            (l.target.index === hoveredNode && l.source.index === node.index),
        )
      );
    }
    if (hoveredLink !== null) {
      const link = links[hoveredLink];
      return link ? link.source.index === node.index || link.target.index === node.index : true;
    }
    return true;
  };

  const tableRows = links.map((link) => ({
    from: displayNodeName(link.source.name),
    to: displayNodeName(link.target.name),
    amount: fullCurrency(link.value),
    share: share(link.value),
  }));

  return (
    <div
      ref={containerRef}
      style={{ display: "grid", gap: 12, width: propWidth ?? "100%", minWidth: 0 }}
    >
      <div className="cash-flow-view seg-control" role="group" aria-label="Cash flow view">
        <button
          type="button"
          className={`seg-option${showList ? " active" : ""}`}
          aria-pressed={showList}
          onClick={() => setView("list")}
        >
          List
        </button>
        <button
          type="button"
          className={`seg-option${showList ? "" : " active"}`}
          aria-pressed={!showList}
          onClick={() => setView("diagram")}
        >
          Diagram
        </button>
      </div>
      {showList && (
        <div className="cash-flow-list" aria-label={`Cash flows for ${selectedYear}`}>
          {[...new Set(tableRows.map((row) => row.from))].map((source) => (
            <section key={source}>
              <h4>{source}</h4>
              <dl>
                {tableRows
                  .filter((row) => row.from === source)
                  .map((row, i) => (
                    <div key={`${row.to}-${i}`}>
                      <dt>{row.to}</dt>
                      <dd>{row.amount}</dd>
                    </div>
                  ))}
              </dl>
            </section>
          ))}
          <p>Flows show each step, including internal movements. Do not add the groups together.</p>
        </div>
      )}
      {!showList && <ChartLegend entries={legendEntries} />}

      <div
        className="viz-plot sankey-plot"
        style={{ width: "100%", height: h, display: showList ? "none" : undefined }}
        onMouseLeave={() => setHover(null)}
      >
        {w > 0 && layout && (
          <svg
            width={w}
            height={h}
            style={{ maxWidth: "100%", display: "block", overflow: "visible" }}
            role="img"
            aria-label={`Cash flow breakdown for ${selectedYear}`}
          >
            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              {links.map((link) => {
                const active = isLinkActive(link);
                return (
                  <path
                    key={`link-${link.index}`}
                    d={linkPath(link as never) ?? ""}
                    fill="none"
                    style={{ stroke: linkColor(link), transition: "stroke-opacity 120ms ease" }}
                    strokeOpacity={
                      hover
                        ? active
                          ? isPassThrough(link)
                            ? 0.28
                            : 0.55
                          : 0.06
                        : linkOpacity(link)
                    }
                    strokeWidth={Math.max(1, link.width)}
                    onPointerEnter={() => setHover({ kind: "link", index: link.index })}
                    onPointerLeave={() => setHover(null)}
                  >
                    <title>
                      {`${displayNodeName(link.source.name)} → ${displayNodeName(link.target.name)}: ${fullCurrency(link.value)}`}
                    </title>
                  </path>
                );
              })}

              {nodes.map((node) => {
                const color = GROUPS[node.group].color;
                const nodeHeight = Math.max(node.y1 - node.y0, 2);
                const nodeWidth = node.x1 - node.x0;
                const hub = isHub(node);
                const isLeft = node.x0 < innerWidth / 2;
                const displayName = displayNodeName(node.name);
                const active = isNodeActive(node);
                const midY = node.y0 + nodeHeight / 2;

                let label: JSX.Element | null;
                if (hub) {
                  label = (
                    <text
                      x={node.x0 + nodeWidth / 2}
                      y={node.y0 - 8}
                      textAnchor="middle"
                      fontSize={11}
                      style={{ fill: "var(--text-secondary)" }}
                    >
                      <tspan fontWeight={600} style={{ fill: "var(--text-primary)" }}>
                        {displayName}
                      </tspan>
                      <tspan dx={5}>{compactCurrency(node.value)}</tspan>
                    </text>
                  );
                } else if (isMobile) {
                  label =
                    nodeHeight >= 16 ? (
                      <text
                        x={isLeft ? node.x1 + 5 : node.x0 - 5}
                        y={midY}
                        dy="0.35em"
                        textAnchor={isLeft ? "start" : "end"}
                        fontSize={10}
                        fontWeight={600}
                        style={{
                          fill: "var(--text-primary)",
                          paintOrder: "stroke",
                          stroke: "var(--surface-card)",
                          strokeWidth: 3,
                          strokeLinejoin: "round",
                        }}
                      >
                        {truncateLabel(displayName, MOBILE_LABEL_LIMIT)}
                      </text>
                    ) : null;
                } else {
                  label = (
                    <text
                      x={isLeft ? node.x0 - 8 : node.x1 + 8}
                      y={midY}
                      dy="0.35em"
                      textAnchor={isLeft ? "end" : "start"}
                      fontSize={11.5}
                      style={{ fill: "var(--text-primary)" }}
                    >
                      <tspan fontWeight={500}>{displayName}</tspan>
                      <tspan dx={6} fontSize={11} style={{ fill: "var(--text-secondary)" }}>
                        {compactCurrency(node.value)}
                      </tspan>
                    </text>
                  );
                }

                return (
                  <g
                    key={`node-${node.index}`}
                    style={{ opacity: active ? 1 : 0.35, transition: "opacity 120ms ease" }}
                    onPointerEnter={() => setHover({ kind: "node", index: node.index })}
                    onPointerLeave={() => setHover(null)}
                  >
                    <title>{`${displayName}: ${fullCurrency(node.value)}`}</title>
                    {/* Enlarged hit target */}
                    <rect
                      x={node.x0 - 6}
                      y={node.y0 - 4}
                      width={nodeWidth + 12}
                      height={nodeHeight + 8}
                      fill="transparent"
                    />
                    <rect
                      x={node.x0}
                      y={node.y0}
                      width={nodeWidth}
                      height={nodeHeight}
                      rx={2}
                      style={{ fill: color }}
                    />
                    {label}
                  </g>
                );
              })}
            </g>
          </svg>
        )}

        {hover &&
          layout &&
          (() => {
            const tooltipWidth = 220;
            if (hover.kind === "node") {
              const node = nodes[hover.index];
              if (!node) return null;
              const placement = placeTooltip({
                anchorX: (node.x0 < innerWidth / 2 ? node.x1 : node.x0) + MARGIN.left,
                anchorY: node.y0 + (node.y1 - node.y0) / 2 + MARGIN.top,
                width: tooltipWidth,
                height: 90,
                containerWidth: w,
                containerHeight: h,
                gap: node.x0 < innerWidth / 2 ? 18 : -18 - tooltipWidth,
              });
              const group = node.group;
              return (
                <VizTooltip
                  placement={placement}
                  width={tooltipWidth}
                  title={displayNodeName(node.name)}
                >
                  <TooltipRow
                    label="Amount"
                    value={fullCurrency(node.value)}
                    color={GROUPS[group].color}
                    emphasis
                  />
                  <TooltipRow label="Share of inflow" value={share(node.value)} muted />
                  {group !== "hub" && (
                    <TooltipRow label="Category" value={GROUPS[group].label} muted />
                  )}
                </VizTooltip>
              );
            }
            const link = links[hover.index];
            if (!link) return null;
            const placement = placeTooltip({
              anchorX: (link.source.x1 + link.target.x0) / 2 + MARGIN.left,
              anchorY:
                (link.source.y0 + link.source.y1 + link.target.y0 + link.target.y1) / 4 +
                MARGIN.top,
              width: tooltipWidth,
              height: 90,
              containerWidth: w,
              containerHeight: h,
            });
            return (
              <VizTooltip
                placement={placement}
                width={tooltipWidth}
                title={`${displayNodeName(link.source.name)} → ${displayNodeName(link.target.name)}`}
              >
                <TooltipRow
                  label="Amount"
                  value={fullCurrency(link.value)}
                  color={linkColor(link)}
                  emphasis
                />
                <TooltipRow label="Share of inflow" value={share(link.value)} muted />
              </VizTooltip>
            );
          })()}
      </div>

      {!showList && (
        <ChartTable
          caption={`Cash flows for ${selectedYear}`}
          note={`${links.length} flows · ${compactCurrency(inflowTotal)} total inflow in ${selectedYear}`}
          columns={[
            { key: "from", label: "From" },
            { key: "to", label: "To" },
            { key: "amount", label: "Amount", numeric: true },
            { key: "share", label: "Share", numeric: true },
          ]}
          rows={tableRows}
        />
      )}
    </div>
  );
}
