import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import SankeyChart, { buildSankeyData } from "./sankey_chart";
import type { CashFlowBreakdown, CashFlowGraph } from "@/types/plan";

// Routing is the service's (backend tests/test_cash_flow_graph.py); these graphs are shaped as it serves them.
const breakdownWith = (graph: CashFlowGraph | undefined): CashFlowBreakdown => ({
  income_sources: [],
  gross_income: 0,
  tax_withheld: 0,
  payroll_deductions: 0,
  net_pay: 0,
  tax_delta: 0,
  expenses: [],
  contributions: [],
  transfers: [],
  drawdowns: [],
  graph,
});

const retirementGraph: CashFlowGraph = {
  nodes: [
    { id: "hub:cash", name: "After-tax cash", group: "hub" },
    { id: "from:savings", name: "savings", group: "saving" },
    { id: "expense:Housing", name: "Housing", group: "spending" },
    { id: "expense:Living", name: "Living", group: "spending" },
  ],
  links: [
    { source: "from:savings", target: "hub:cash", amount: 125000 },
    { source: "hub:cash", target: "expense:Housing", amount: 50000 },
    { source: "hub:cash", target: "expense:Living", amount: 75000 },
  ],
};

const workingGraph: CashFlowGraph = {
  nodes: [
    { id: "hub:gross", name: "Gross income", group: "hub" },
    { id: "hub:cash", name: "After-tax cash", group: "hub" },
    { id: "income:Pay", name: "Pay", group: "income" },
    { id: "employer:work", name: "Employer contributions", group: "income" },
    { id: "to:work", name: "Work plan", group: "saving" },
    { id: "tax:taxes", name: "Taxes", group: "tax" },
    { id: "expense:Living", name: "Living", group: "spending" },
    { id: "from:ira", name: "IRA", group: "saving" },
    { id: "to:roth", name: "Roth IRA", group: "saving" },
  ],
  links: [
    { source: "income:Pay", target: "hub:gross", amount: 100 },
    { source: "employer:work", target: "to:work", amount: 10 },
    { source: "hub:gross", target: "to:work", amount: 20 },
    { source: "hub:gross", target: "tax:taxes", amount: 15 },
    { source: "hub:gross", target: "hub:cash", amount: 65 },
    { source: "hub:cash", target: "expense:Living", amount: 65 },
    { source: "from:ira", target: "to:roth", amount: 40 },
  ],
};

describe("SankeyChart", () => {
  it("indexes the served graph for d3-sankey without changing it", () => {
    const { nodes, links } = buildSankeyData(workingGraph);
    expect(nodes.map((node) => node.name)).toEqual(workingGraph.nodes.map((node) => node.name));
    expect(links[2]).toEqual({ source: 0, target: 4, value: 20 });
    expect(nodes[links[3].target]).toEqual({ name: "Taxes", group: "tax" });
  });
  it("counts income and employer money as inflow, never pass-throughs or transfers", () => {
    render(
      <SankeyChart
        breakdown={breakdownWith(workingGraph)}
        selectedYear={2026}
        width={800}
        height={400}
      />,
    );
    expect(screen.getByText(/\$110 total inflow/)).toBeInTheDocument();
    expect(screen.getAllByText("Taxes").length).toBeGreaterThan(0);
  });
  it("renders when only drawdowns+expenses exist (retirement year)", () => {
    render(
      <SankeyChart
        breakdown={breakdownWith(retirementGraph)}
        selectedYear={2055}
        width={800}
        height={400}
      />,
    );
    expect(screen.queryByText(/No cash flow data/)).toBeNull();
    expect(screen.getByRole("img", { name: /Cash flow breakdown for 2055/ })).toBeInTheDocument();
    expect(screen.getByText("Savings & investments")).toBeInTheDocument();
    expect(screen.getByText("Spending")).toBeInTheDocument();
    // An account the plan left unnamed is served by its type and labelled readably.
    expect(screen.getAllByText("Savings").length).toBeGreaterThan(0);
  });

  it("clears a hovered flow when the selected year changes", () => {
    const { rerender } = render(
      <SankeyChart
        breakdown={breakdownWith(retirementGraph)}
        selectedYear={2055}
        width={800}
        height={400}
      />,
    );
    const diagram = screen.getByRole("img", { name: "Cash flow breakdown for 2055" });
    fireEvent.pointerEnter(diagram.querySelector("path")!);
    expect(document.querySelector(".viz-tooltip")).not.toBeNull();
    const next = {
      ...retirementGraph,
      nodes: retirementGraph.nodes.map((node) =>
        node.id === "from:savings" ? { ...node, name: "IRA" } : node,
      ),
    };
    rerender(
      <SankeyChart breakdown={breakdownWith(next)} selectedYear={2056} width={800} height={400} />,
    );
    expect(document.querySelector(".viz-tooltip")).toBeNull();
    expect(screen.getByRole("img", { name: "Cash flow breakdown for 2056" })).toBeInTheDocument();
  });

  it("shows empty state when no activity at all", () => {
    render(
      <SankeyChart
        breakdown={breakdownWith({ nodes: [], links: [] })}
        selectedYear={2030}
        width={800}
        height={400}
      />,
    );
    expect(screen.getByText(/No cash flow data for 2030/)).toBeInTheDocument();
    render(
      <SankeyChart
        breakdown={breakdownWith(undefined)}
        selectedYear={2031}
        width={800}
        height={400}
      />,
    );
    expect(screen.getByText(/No cash flow data for 2031/)).toBeInTheDocument();
  });
});
