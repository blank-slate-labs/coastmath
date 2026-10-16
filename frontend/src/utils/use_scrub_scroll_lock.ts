import { useCallback, useEffect, useState } from "react";

/** A finger held this long before moving is scrubbing, whatever direction it then takes. */
const HOLD_MS = 250;

/**
 * Keep the page still while a finger scrubs a chart. The first move of a touch
 * decides the gesture: mostly sideways, or after a press-and-hold, it scrubs and
 * vertical page scrolling is blocked until the finger lifts; mostly vertical, it
 * scrolls the page as usual. Returns a callback ref for the chart's hit target.
 */
export function useScrubScrollLock<T extends Element>() {
  const [element, setElement] = useState<T | null>(null);
  const ref = useCallback((node: T | null) => setElement(node), []);

  useEffect(() => {
    if (!element) return;
    let start: { x: number; y: number; time: number } | null = null;
    let scrubbing: boolean | null = null;

    const onStart = (event: Event) => {
      const { touches } = event as TouchEvent;
      scrubbing = null;
      start =
        touches.length === 1
          ? { x: touches[0].clientX, y: touches[0].clientY, time: event.timeStamp }
          : null;
    };
    const onMove = (event: Event) => {
      const { touches } = event as TouchEvent;
      if (!start || touches.length !== 1) return;
      if (scrubbing === null) {
        const dx = Math.abs(touches[0].clientX - start.x);
        const dy = Math.abs(touches[0].clientY - start.y);
        if (dx === 0 && dy === 0) return;
        scrubbing = dx >= dy || event.timeStamp - start.time >= HOLD_MS;
      }
      if (scrubbing && event.cancelable) event.preventDefault();
    };
    const onEnd = () => {
      start = null;
      scrubbing = null;
    };

    element.addEventListener("touchstart", onStart, { passive: true });
    // Non-passive: a passive listener cannot cancel the scroll.
    element.addEventListener("touchmove", onMove, { passive: false });
    element.addEventListener("touchend", onEnd);
    element.addEventListener("touchcancel", onEnd);
    return () => {
      element.removeEventListener("touchstart", onStart);
      element.removeEventListener("touchmove", onMove);
      element.removeEventListener("touchend", onEnd);
      element.removeEventListener("touchcancel", onEnd);
    };
  }, [element]);

  return ref;
}
