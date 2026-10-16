import "@testing-library/jest-dom";

// Polyfill ResizeObserver for jsdom (used by useChartSize hook)
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof globalThis.ResizeObserver;

// The planner keeps its tab and open editor in the address (?tab=…&edit=…). jsdom keeps one URL
// per file, so return to a clean address after each test instead of leaking an open editor.
import { afterEach } from "vitest";
afterEach(() => {
  window.history.replaceState(null, "", window.location.pathname);
});
