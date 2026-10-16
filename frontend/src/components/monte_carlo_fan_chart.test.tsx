import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import * as fs from "fs";
import * as path from "path";

import MonteCarloFanChart from "./monte_carlo_fan_chart";
import type { PercentileCurve } from "./monte_carlo_fan_chart";

// --- Fixtures ---

const years = [2024, 2025, 2026, 2027, 2028];

const percentileCurves: PercentileCurve[] = [
  { label: "p10", values: [100000, 90000, 80000, 70000, 60000] },
  { label: "p25", values: [100000, 110000, 120000, 130000, 140000] },
  { label: "p50", values: [100000, 130000, 160000, 190000, 220000] },
  { label: "p75", values: [100000, 150000, 200000, 260000, 330000] },
  { label: "p90", values: [100000, 170000, 250000, 340000, 450000] },
];

// --- Tests ---

describe("MonteCarloFanChart", () => {
  it('renders "No Monte Carlo data" when no data provided', () => {
    render(<MonteCarloFanChart percentileCurves={[]} years={[]} width={600} height={400} />);
    expect(screen.getByText("No Monte Carlo data")).toBeInTheDocument();
  });

  it("renders an SVG with 3 paths (2 bands + 1 median line)", () => {
    const { container } = render(
      <MonteCarloFanChart
        percentileCurves={percentileCurves}
        years={years}
        width={600}
        height={400}
      />,
    );

    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();

    const outerBand = container.querySelector('[data-testid="band-outer"]');
    const innerBand = container.querySelector('[data-testid="band-inner"]');
    const medianLine = container.querySelector('[data-testid="line-median"]');

    expect(outerBand).toBeInTheDocument();
    expect(innerBand).toBeInTheDocument();
    expect(medianLine).toBeInTheDocument();

    // All three should have a non-empty d attribute
    expect(outerBand?.getAttribute("d")).toBeTruthy();
    expect(innerBand?.getAttribute("d")).toBeTruthy();
    expect(medianLine?.getAttribute("d")).toBeTruthy();
  });

  it("shows tooltip with percentile values on hover", () => {
    const { container } = render(
      <MonteCarloFanChart
        percentileCurves={percentileCurves}
        years={years}
        width={600}
        height={400}
      />,
    );

    // Tooltip should not be visible initially
    expect(screen.queryByTestId("fan-tooltip")).not.toBeInTheDocument();

    // Find the invisible hover overlay (the transparent rect)
    const rects = container.querySelectorAll("rect[fill='transparent']");
    expect(rects.length).toBe(1);
    const overlay = rects[0];

    // Simulate mouse move over the overlay
    fireEvent.mouseMove(overlay, { clientX: 300, clientY: 200 });

    // Tooltip should now be visible
    const tooltip = screen.getByTestId("fan-tooltip");
    expect(tooltip).toBeInTheDocument();

    // Should contain percentile labels
    expect(tooltip.textContent).toContain("50th (Median)");
    expect(tooltip.textContent).toContain("90th");
    expect(tooltip.textContent).toContain("10th");

    // Mouse leave hides tooltip
    fireEvent.mouseLeave(overlay);
    expect(screen.queryByTestId("fan-tooltip")).not.toBeInTheDocument();
  });

  it("does not use D3 DOM manipulation (d3.select / d3.append)", () => {
    const source = fs.readFileSync(path.resolve(__dirname, "./monte_carlo_fan_chart.tsx"), "utf-8");

    expect(source).not.toMatch(/d3\.select/);
    expect(source).not.toMatch(/d3\.append/);
    expect(source).not.toMatch(/\.select\s*\(/);
    expect(source).not.toMatch(/\.append\s*\(\s*["']/);
    expect(source).not.toMatch(/axisBottom/);
    expect(source).not.toMatch(/axisLeft/);
  });
});
