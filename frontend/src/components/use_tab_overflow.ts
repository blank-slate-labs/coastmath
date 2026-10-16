import { useEffect, useState, type RefObject } from "react";

/** Width of the edge fade on `.tab-cluster` (theme.css). A revealed tab is moved clear of it. */
const EDGE_FADE = 48;

export interface TabOverflow {
  /** Tabs are hidden past the left edge. */
  start: boolean;
  /** Tabs are hidden past the right edge. */
  end: boolean;
}

/** Scrolls a row horizontally so `tab` sits clear of the edge fades, without scrolling the page. */
export function revealTab(row: HTMLElement, tab: HTMLElement) {
  const bounds = row.getBoundingClientRect();
  const rect = tab.getBoundingClientRect();
  const edge = Math.min(EDGE_FADE, Math.max(0, (bounds.width - rect.width) / 2));
  if (rect.left < bounds.left + edge) row.scrollLeft -= bounds.left + edge - rect.left;
  else if (rect.right > bounds.right - edge) row.scrollLeft += rect.right - (bounds.right - edge);
}

/**
 * Which ends of a horizontally scrolling tab row hide tabs, kept current on scroll and resize.
 * Also brings the active tab (`aria-current="page"`) into view when it changes, and any tab that
 * takes focus, so keyboard focus never lands on a tab hidden off the edge.
 */
export function useTabOverflow(
  ref: RefObject<HTMLElement | null>,
  activeKey: string,
  tabCount: number,
): TabOverflow {
  const [overflow, setOverflow] = useState<TabOverflow>({ start: false, end: false });

  useEffect(() => {
    const row = ref.current;
    if (!row) return;
    const measure = () => {
      const hidden = row.scrollWidth - row.clientWidth - row.scrollLeft;
      const start = row.scrollLeft > 1;
      const end = hidden > 1;
      setOverflow((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
    };
    const reveal = (event: FocusEvent) => {
      if (event.target instanceof HTMLElement && event.target !== row) revealTab(row, event.target);
    };
    measure();
    row.addEventListener("scroll", measure, { passive: true });
    row.addEventListener("focusin", reveal);
    // The row's width follows the window; the tabs' widths follow font loading.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(row);
    for (const tab of Array.from(row.children)) observer?.observe(tab);
    return () => {
      row.removeEventListener("scroll", measure);
      row.removeEventListener("focusin", reveal);
      observer?.disconnect();
    };
  }, [ref, tabCount]);

  useEffect(() => {
    const row = ref.current;
    const active = row?.querySelector<HTMLElement>('[aria-current="page"]');
    if (row && active) revealTab(row, active);
  }, [ref, activeKey, tabCount]);

  return overflow;
}
