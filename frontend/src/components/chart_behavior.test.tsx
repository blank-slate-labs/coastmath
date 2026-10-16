import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { scaleLinear } from "d3-scale";
import { EffectiveTaxRateChart } from "./tax/effective_tax_rate_chart";
import { DeductionComparison } from "./tax/deduction_comparison";
import CompareOverlay from "./compare_overlay";
import type { YearSnapshot } from "@/types/plan";

let notify: (entries: ResizeObserverEntry[]) => void;
const disconnect = vi.fn();
beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: typeof notify) {
        notify = callback;
      }
      observe() {
        notify([{ contentRect: { width: 680, height: 360 } } as ResizeObserverEntry]);
      }
      disconnect = disconnect;
    },
  );
});
afterEach(() => vi.unstubAllGlobals());
const first = {
  year: 2026,
  age: 40,
  effective_rate: 0.15,
  marginal_rate: 0.24,
  standard_deduction: 10000,
  deduction_amount: 20000,
  deduction_used: "itemized",
} as YearSnapshot;
const second = {
  ...first,
  year: 2027,
  age: 41,
  effective_rate: 0.2,
  marginal_rate: 0.32,
  deduction_used: "standard",
  deduction_amount: 10000,
};

it("shows the selected year rates, updates hover after new results, and clears on leave", () => {
  const view = render(<EffectiveTaxRateChart snapshots={[first, second]} />);
  const overlay = view.container.querySelector('rect[fill="transparent"]')!;
  fireEvent.mouseMove(overlay, { clientX: 0 });
  expect(screen.getByText("15.0%")).toBeInTheDocument();
  expect(screen.getByText("24.0%")).toBeInTheDocument();
  fireEvent.mouseMove(overlay, { clientX: 600 });
  expect(screen.getByText("20.0%")).toBeInTheDocument();
  expect(screen.getByText("32.0%")).toBeInTheDocument();
  expect(view.container.querySelectorAll("circle")).toHaveLength(2);
  view.rerender(
    <EffectiveTaxRateChart snapshots={[first, { ...second, effective_rate: 0.125 }]} />,
  );
  expect(screen.getByText("12.5%")).toBeInTheDocument();
  fireEvent.mouseLeave(overlay);
  expect(screen.queryByText("12.5%")).not.toBeInTheDocument();
  expect(view.container.querySelectorAll("circle")).toHaveLength(0);
  view.unmount();
  expect(disconnect).toHaveBeenCalled();
});
it("recovers the rate chart from empty results and handles zero dimensions", () => {
  const view = render(<EffectiveTaxRateChart snapshots={[]} />);
  expect(screen.getByText("No simulation data")).toBeInTheDocument();
  act(() => notify([]));
  view.rerender(<EffectiveTaxRateChart snapshots={[first]} />);
  expect(view.container.querySelectorAll("path")).toHaveLength(2);
  act(() => notify([{ contentRect: { width: 0, height: 0 } } as ResizeObserverEntry]));
  expect(view.container.querySelectorAll("path")).toHaveLength(0);
});
it("renders the saved deduction values proportionally and counts itemization years", () => {
  const view = render(<DeductionComparison snapshots={[first, second]} />);
  expect(screen.getByText("You itemize in 1 of 2 years")).toBeInTheDocument();
  const standard = view.container.querySelectorAll('rect[fill="#4a90d9"]');
  const itemized = view.container.querySelector('rect[fill="#10b981"]')!;
  expect(standard).toHaveLength(2);
  expect(Number(itemized.getAttribute("height"))).toBeCloseTo(
    2 * Number(standard[0].getAttribute("height")),
  );
  expect(standard[0]).toHaveAttribute("opacity", "0.3");
  expect(standard[1]).toHaveAttribute("opacity", "1");
  expect(view.container.textContent).toContain("$10k");
});
it("renders deduction bars when empty results are replaced by a saved forecast", () => {
  const view = render(<DeductionComparison snapshots={[]} />);
  expect(screen.getByText("No simulation data")).toBeInTheDocument();
  view.rerender(<DeductionComparison snapshots={[first]} />);
  expect(view.container.querySelectorAll("rect")).toHaveLength(2);
});
it("labels long deduction timelines sparsely and formats million-dollar amounts", () => {
  const snapshots = Array.from({ length: 31 }, (_, i) => ({
    ...first,
    year: 2026 + i,
    standard_deduction: 1000000,
    deduction_amount: 2000000,
  }));
  const view = render(<DeductionComparison snapshots={snapshots} />);
  expect(view.container.querySelectorAll("rect")).toHaveLength(62);
  expect(screen.getByText("2026")).toBeInTheDocument();
  expect(screen.queryByText("2027")).not.toBeInTheDocument();
  expect(screen.getByText("$1.0M")).toBeInTheDocument();
  view.rerender(
    <DeductionComparison snapshots={[{ ...first, standard_deduction: 0, deduction_amount: 0 }]} />,
  );
  expect(Number(view.container.querySelector("rect")!.getAttribute("height"))).toBe(0);
  expect(view.container.textContent).toContain("$0");
});
it("plots the baseline and signed comparison area with independently scaled coordinates", () => {
  const props = {
    baselineTimeline: [
      { year: 2026, net_worth: 100 },
      { year: 2027, net_worth: 200 },
    ] as YearSnapshot[],
    delta: [
      { year: 2026, baselineNetWorth: 100, currentNetWorth: 200, delta: 100 },
      { year: 2027, baselineNetWorth: 200, currentNetWorth: 100, delta: -100 },
    ],
    innerWidth: 100,
    innerHeight: 100,
    xScale: scaleLinear().domain([2026, 2027]).range([0, 100]),
    yScale: scaleLinear().domain([0, 200]).range([100, 0]),
    hoverYear: 2026,
  };
  const view = render(
    <svg>
      <CompareOverlay {...props} />
    </svg>,
  );
  expect(view.container.querySelector("path[stroke-dasharray]")).toHaveAttribute(
    "d",
    "M0,50L100,0",
  );
  expect(view.container.querySelector("circle")).toHaveAttribute("cx", "0");
  expect(view.container.querySelector("circle")).toHaveAttribute("cy", "50");
  const fills = view.container.querySelectorAll("path[fill-opacity]");
  expect(fills).toHaveLength(2);
  expect(fills[0].getAttribute("d")).toBe("M0,0L100,50L100,0L0,50Z");
  expect(fills[0].getAttribute("clip-path")).not.toBe(fills[1].getAttribute("clip-path"));
  view.rerender(
    <svg>
      <CompareOverlay {...props} hoverYear={1999} />
    </svg>,
  );
  expect(view.container.querySelector("circle")).toBeNull();
  view.rerender(
    <svg>
      <CompareOverlay {...props} hoverYear={null} delta={[]} baselineTimeline={[]} />
    </svg>,
  );
  expect(view.container.querySelector("g")).toBeNull();
});
