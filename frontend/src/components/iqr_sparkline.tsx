import { useMemo } from "react";
import { scaleLinear } from "d3-scale";
import { line, area } from "d3-shape";

interface IQRSparklineProps {
  p25: number[];
  p50: number[];
  p75: number[];
  width?: number;
  height?: number;
}

export default function IQRSparkline({
  p25,
  p50,
  p75,
  width = 120,
  height = 32,
}: IQRSparklineProps) {
  const len = p25.length;

  const xScale = useMemo(() => {
    if (len < 2) return null;
    return scaleLinear()
      .domain([0, len - 1])
      .range([0, width]);
  }, [len, width]);

  const yScale = useMemo(() => {
    if (len === 0) return null;
    const min = Math.min(...p25);
    const max = Math.max(...p75);
    const pad = (max - min) * 0.1 || 1;
    return scaleLinear()
      .domain([min - pad, max + pad])
      .range([height, 0]);
  }, [p25, p75, height, len]);

  const bandPath = useMemo(() => {
    if (!xScale || !yScale || len === 0) return "";
    const gen = area<number>()
      .x((_, i) => xScale(i))
      .y0((_, i) => yScale(p25[i]))
      .y1((_, i) => yScale(p75[i]));
    return gen(p50) ?? "";
  }, [p25, p50, p75, xScale, yScale, len]);

  const medianPath = useMemo(() => {
    if (!xScale || !yScale || len === 0) return "";
    const gen = line<number>()
      .x((_, i) => xScale(i))
      .y((d) => yScale(d));
    return gen(p50) ?? "";
  }, [p50, xScale, yScale, len]);

  if (len === 0 || !xScale || !yScale) {
    return <svg width={width} height={height} />;
  }

  return (
    <svg width={width} height={height}>
      <path d={bandPath} fill="rgba(74, 144, 217, 0.2)" stroke="none" />
      <path
        d={medianPath}
        fill="none"
        stroke="#4a90d9"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
