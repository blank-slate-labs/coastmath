import { act, fireEvent, render } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  HoverLine,
  PointerOverlay,
  XAxisTicks,
  YAxisTicks,
  YGridLines,
  chartTickCounts,
} from "./chart_frame";
import { useObservedSize } from "@/utils/use_chart_size";

const double = (value: number) => value * 2;
const inSvg = (node: JSX.Element) =>
  render(
    <svg>
      <g>{node}</g>
    </svg>,
  ).container.querySelector("g") as SVGGElement;

describe("chartTickCounts", () => {
  it("spaces x ticks about 80px and y ticks about 50px apart, with at least two each", () => {
    expect(chartTickCounts(640, 300)).toEqual({ x: 8, y: 6 });
    expect(chartTickCounts(239, 149)).toEqual({ x: 2, y: 2 });
    expect(chartTickCounts(-40, -10)).toEqual({ x: 2, y: 2 });
  });
});

describe("YGridLines", () => {
  it("draws one dashed light line per tick across the plot width", () => {
    const lines = inSvg(
      <YGridLines ticks={[0, 10]} yScale={double} width={300} />,
    ).querySelectorAll("line");
    expect(lines).toHaveLength(2);
    expect(lines[1].getAttribute("x1")).toBe("0");
    expect(lines[1].getAttribute("x2")).toBe("300");
    expect(lines[1].getAttribute("y1")).toBe("20");
    expect(lines[1].getAttribute("y2")).toBe("20");
    expect(lines[1].getAttribute("stroke")).toBe("#e0e0e0");
    expect(lines[1].getAttribute("stroke-dasharray")).toBe("4 2");
    expect(lines[1].hasAttribute("stroke-width")).toBe(false);
  });

  it("takes a themed solid stroke", () => {
    const line = inSvg(
      <YGridLines
        ticks={[5]}
        yScale={double}
        width={10}
        stroke="var(--gray-100)"
        strokeDasharray={null}
        strokeWidth={1}
      />,
    ).querySelector("line") as SVGLineElement;
    expect(line.getAttribute("stroke")).toBe("var(--gray-100)");
    expect(line.hasAttribute("stroke-dasharray")).toBe(false);
    expect(line.getAttribute("stroke-width")).toBe("1");
  });
});

describe("axis ticks", () => {
  it("places x labels under the plot with a tick mark", () => {
    const groups = inSvg(
      <XAxisTicks ticks={[2030, 2040]} xScale={double} y={120} />,
    ).querySelectorAll("g");
    expect(groups).toHaveLength(2);
    expect(groups[0].getAttribute("transform")).toBe("translate(4060,120)");
    expect(groups[0].querySelector("line")?.getAttribute("y2")).toBe("6");
    const text = groups[0].querySelector("text") as SVGTextElement;
    expect(text.textContent).toBe("2030");
    expect(text.getAttribute("y")).toBe("20");
    expect(text.getAttribute("text-anchor")).toBe("middle");
    expect(text.getAttribute("fill")).toBe("#666");
  });

  it("formats y labels right-aligned beside a tick mark", () => {
    const group = inSvg(
      <YAxisTicks ticks={[25]} yScale={double} format={(v) => `${v}%`} />,
    ).querySelector("g") as SVGGElement;
    expect(group.getAttribute("transform")).toBe("translate(0,50)");
    expect(group.querySelector("line")?.getAttribute("x2")).toBe("-6");
    const text = group.querySelector("text") as SVGTextElement;
    expect(text.textContent).toBe("25%");
    expect(text.getAttribute("x")).toBe("-10");
    expect(text.getAttribute("text-anchor")).toBe("end");
  });

  it("omits tick marks and applies a themed label style", () => {
    const root = inSvg(
      <>
        <XAxisTicks
          ticks={[1]}
          xScale={double}
          y={0}
          tickLine={false}
          fill="var(--gray-400)"
          fontFamily="var(--font-sans)"
        />
        <YAxisTicks
          ticks={[1]}
          yScale={double}
          format={String}
          tickLine={false}
          fill="var(--gray-400)"
          fontFamily="var(--font-sans)"
        />
      </>,
    );
    expect(root.querySelectorAll("line")).toHaveLength(0);
    for (const text of root.querySelectorAll("text")) {
      expect(text.getAttribute("fill")).toBe("var(--gray-400)");
      expect(text.getAttribute("font-family")).toBe("var(--font-sans)");
    }
  });
});

describe("hover pieces", () => {
  it("draws a dashed vertical hover line that ignores the pointer", () => {
    const line = inSvg(<HoverLine x={42} height={200} />).querySelector("line") as SVGLineElement;
    expect([
      line.getAttribute("x1"),
      line.getAttribute("x2"),
      line.getAttribute("y1"),
      line.getAttribute("y2"),
    ]).toEqual(["42", "42", "0", "200"]);
    expect(line.getAttribute("stroke")).toBe("#999");
    expect(line.getAttribute("pointer-events")).toBe("none");
  });

  it("forwards pointer movement and leave from the overlay", () => {
    const onMouseMove = vi.fn();
    const onMouseLeave = vi.fn();
    const rect = inSvg(
      <PointerOverlay
        width={300}
        height={150}
        onMouseMove={onMouseMove}
        onMouseLeave={onMouseLeave}
      />,
    ).querySelector("rect") as SVGRectElement;
    expect(rect.getAttribute("width")).toBe("300");
    expect(rect.getAttribute("height")).toBe("150");
    expect(rect.getAttribute("fill")).toBe("transparent");
    fireEvent.mouseMove(rect, { clientX: 10 });
    fireEvent.mouseLeave(rect);
    expect(onMouseMove).toHaveBeenCalledTimes(1);
    expect(onMouseLeave).toHaveBeenCalledTimes(1);
  });
});

describe("useObservedSize", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("stays zero until observed and re-observes when the reset key changes", () => {
    const observed: Element[] = [];
    let notify: (entries: ResizeObserverEntry[]) => void = () => {};
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: typeof notify) {
          notify = callback;
        }
        observe(element: Element) {
          observed.push(element);
        }
        disconnect = disconnect;
      },
    );
    let show!: (value: boolean) => void;
    function Probe() {
      const ref = useRef<HTMLDivElement>(null);
      const [shown, setShown] = useState(false);
      show = setShown;
      const size = useObservedSize(ref, shown);
      return shown ? <div ref={ref} data-testid="box">{`${size.width}x${size.height}`}</div> : null;
    }
    const view = render(<Probe />);
    expect(observed).toHaveLength(0);
    act(() => show(true));
    expect(observed).toEqual([view.getByTestId("box")]);
    expect(view.getByTestId("box")).toHaveTextContent("0x0");
    act(() => notify([{ contentRect: { width: 320, height: 180 } } as ResizeObserverEntry]));
    expect(view.getByTestId("box")).toHaveTextContent("320x180");
    view.unmount();
    expect(disconnect).toHaveBeenCalledTimes(1);
  });
});
