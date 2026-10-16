import { useCallback, useState, type MouseEvent } from "react";
import type { ScaleLinear } from "d3-scale";
import type { YearSnapshot } from "@/types/plan";
import { yearBisector, yearValueBisector } from "@/utils/year_bisector";

type YearSeries = readonly number[] | readonly YearSnapshot[];

function isYearList(years: YearSeries): years is readonly number[] {
  return typeof years[0] === "number";
}

/**
 * Year hover for a line chart's pointer overlay: the index of the year nearest the pointer, a
 * mouse-move handler that sets it from the x scale, and a mouse-leave handler that clears it
 * (also returned as `clearHover` for a chart that drops its hover when its data is replaced).
 * `years` is the chart's ascending years, as plain numbers or as snapshots.
 */
export function useYearHover(years: YearSeries, xScale: ScaleLinear<number, number>) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const handleMouseMove = useCallback(
    (e: MouseEvent<SVGRectElement>) => {
      if (years.length === 0) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const year = xScale.invert(e.clientX - rect.left);
      setHoverIndex(isYearList(years) ? yearValueBisector(years, year) : yearBisector(years, year));
    },
    [years, xScale],
  );

  const clearHover = useCallback(() => setHoverIndex(null), []);

  return { hoverIndex, handleMouseMove, handleMouseLeave: clearHover, clearHover };
}
