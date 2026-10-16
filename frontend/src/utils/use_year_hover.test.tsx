import { fireEvent, render, screen } from "@testing-library/react";
import { scaleLinear } from "d3-scale";
import { expect, it } from "vitest";
import type { YearSnapshot } from "@/types/plan";
import { useYearHover } from "./use_year_hover";

// jsdom lays nothing out, so the overlay's rect sits at 0 and clientX is the plot x.
const xScale = scaleLinear().domain([2030, 2040]).range([0, 100]);

function Overlay({ years }: { years: readonly number[] | readonly YearSnapshot[] }) {
  const { hoverIndex, handleMouseMove, handleMouseLeave } = useYearHover(years, xScale);
  return (
    <svg>
      <rect data-testid="overlay" onMouseMove={handleMouseMove} onMouseLeave={handleMouseLeave} />
      <text data-testid="index">{hoverIndex ?? "none"}</text>
    </svg>
  );
}

it("tracks the nearest of a list of years and clears on leave", () => {
  render(<Overlay years={[2030, 2032, 2035, 2040]} />);
  const overlay = screen.getByTestId("overlay");
  expect(screen.getByTestId("index")).toHaveTextContent("none");
  fireEvent.mouseMove(overlay, { clientX: 31 });
  expect(screen.getByTestId("index")).toHaveTextContent("1");
  fireEvent.mouseMove(overlay, { clientX: 95 });
  expect(screen.getByTestId("index")).toHaveTextContent("3");
  fireEvent.mouseLeave(overlay);
  expect(screen.getByTestId("index")).toHaveTextContent("none");
});

it("bisects snapshots by year and ignores an empty series", () => {
  const snapshots = [2030, 2031, 2032].map((year) => ({ year }) as YearSnapshot);
  const view = render(<Overlay years={snapshots} />);
  fireEvent.mouseMove(screen.getByTestId("overlay"), { clientX: 12 });
  expect(screen.getByTestId("index")).toHaveTextContent("1");
  view.rerender(<Overlay years={[]} />);
  fireEvent.mouseMove(screen.getByTestId("overlay"), { clientX: 50 });
  expect(screen.getByTestId("index")).toHaveTextContent("1");
});
