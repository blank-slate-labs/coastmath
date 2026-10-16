import { useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";

import { compactCurrency } from "@/utils/format";

interface YearPoint {
  year: number;
  age: number;
  net_worth: number;
}

/**
 * A compact age scrubber that pins to the top of the dashboard once the
 * hero chart (and its own scrubber) has scrolled out of view, so the
 * selected year can be changed while reading the panels further down.
 *
 * It is a zero-height sticky anchor, so it never shifts the layout. The
 * same CSS works whether the page scrolls (mobile) or the right pane
 * does (desktop): visibility compares the anchor's stuck position with
 * the bottom of `anchorRef`, so no header height is hard-coded.
 */
export function StickyYearBar({
  data,
  selectedYear,
  onSelectYear,
  anchorRef,
}: {
  data: YearPoint[];
  selectedYear: number;
  onSelectYear: (year: number) => void;
  anchorRef: RefObject<HTMLElement | null>;
}) {
  const stickyRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      const sticky = stickyRef.current;
      const anchor = anchorRef.current;
      if (!sticky || !anchor) return;
      const rect = anchor.getBoundingClientRect();
      // No layout (hidden, or a test DOM) means nothing has scrolled away.
      setVisible(rect.height > 0 && rect.bottom <= sticky.getBoundingClientRect().top);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    // Scroll events do not bubble, but a capturing listener sees the
    // window's and the right pane's alike.
    document.addEventListener("scroll", schedule, { capture: true, passive: true });
    window.addEventListener("resize", schedule);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    if (anchorRef.current) observer?.observe(anchorRef.current);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      document.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      observer?.disconnect();
    };
  }, [anchorRef]);

  // React 18 has no `inert` prop; keep the hidden bar out of the tab order.
  useEffect(() => {
    if (barRef.current) barRef.current.inert = !visible;
  }, [visible]);

  const index = data.findIndex((point) => point.year === selectedYear);
  if (index < 0) return null;
  const point = data[index];
  const select = (next: number) => {
    const target = data[Math.max(0, Math.min(data.length - 1, next))];
    if (target && target.year !== selectedYear) onSelectYear(target.year);
  };

  const last = data.length - 1;
  const progress = last > 0 ? index / last : 0;

  return (
    <div ref={stickyRef} className="dash-year-sticky">
      <div
        ref={barRef}
        className={`dash-year-bar${visible ? " is-visible" : ""}`}
        role="group"
        aria-label="Selected age"
        aria-hidden={!visible}
      >
        <div className="dash-year-bar-label" aria-live="off">
          <strong>Age {point.age}</strong>
          <span>
            {point.year} · {compactCurrency(point.net_worth)}
          </span>
        </div>
        <input
          type="range"
          className="dash-year-bar-range"
          data-sample-view
          min={0}
          max={last}
          step={1}
          value={index}
          disabled={data.length < 2}
          aria-label="Age"
          aria-valuetext={`Age ${point.age}, ${point.year}`}
          onChange={(event) => select(Number(event.target.value))}
          style={{ "--progress": progress } as CSSProperties}
        />
        <div className="dash-year-steps">
          <button
            type="button"
            className="dash-year-step"
            aria-label="Previous age"
            disabled={index <= 0}
            onClick={() => select(index - 1)}
          >
            <Chevron direction="left" />
          </button>
          <button
            type="button"
            className="dash-year-step"
            aria-label="Next age"
            disabled={index >= last}
            onClick={() => select(index + 1)}
          >
            <Chevron direction="right" />
          </button>
        </div>
      </div>
    </div>
  );
}

function Chevron({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={direction === "left" ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"} />
    </svg>
  );
}
