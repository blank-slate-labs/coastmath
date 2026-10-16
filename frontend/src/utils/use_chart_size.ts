import { useCallback, useEffect, useState, type RefObject } from "react";

export const COMPACT_CHART_WIDTH = 640;
export const TINY_CHART_WIDTH = 420;

/**
 * Measure a chart container. Returns a callback ref so the observer attaches
 * whenever the container mounts — including after an empty state is replaced
 * by the real chart — rather than only on the hook's first render.
 */
export function useChartSize(fallbackWidth = 960, fallbackHeight = 380) {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  const ref = useCallback((node: HTMLDivElement | null) => {
    setElement(node);
  }, []);

  useEffect(() => {
    if (!element) return;
    setSize({ width: element.clientWidth, height: element.clientHeight });
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);

  const width = size.width > 0 ? size.width : fallbackWidth;
  const height = size.height > 0 ? size.height : fallbackHeight;
  return {
    ref,
    width,
    height,
    isCompact: width < COMPACT_CHART_WIDTH,
    isTiny: width < TINY_CHART_WIDTH,
  };
}

/**
 * Observe an element the caller already holds a ref to. Unlike `useChartSize` there is no
 * fallback: the size stays zero until the observer reports, so a chart can wait for real room
 * before drawing. Change `resetKey` when the element may have mounted or been replaced.
 */
export function useObservedSize(ref: RefObject<HTMLElement>, resetKey?: unknown) {
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, resetKey]);

  return size;
}
