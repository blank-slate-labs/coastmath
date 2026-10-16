import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useScrubScrollLock } from "./use_scrub_scroll_lock";

function Target() {
  const ref = useScrubScrollLock<HTMLDivElement>();
  return <div ref={ref} data-testid="target" />;
}

function touch(target: Element, type: string, points: Array<[number, number]>, timeStamp = 0) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "touches", {
    value: points.map(([clientX, clientY]) => ({ clientX, clientY })),
  });
  Object.defineProperty(event, "timeStamp", { value: timeStamp });
  target.dispatchEvent(event);
  return event;
}

describe("useScrubScrollLock", () => {
  it("blocks page scroll for the rest of a gesture that starts sideways", () => {
    const target = render(<Target />).getByTestId("target");
    touch(target, "touchstart", [[100, 100]]);
    expect(touch(target, "touchmove", [[110, 102]], 10).defaultPrevented).toBe(true);
    expect(touch(target, "touchmove", [[112, 160]], 20).defaultPrevented).toBe(true);
  });

  it("lets a vertical swipe scroll the page", () => {
    const target = render(<Target />).getByTestId("target");
    touch(target, "touchstart", [[100, 100]]);
    expect(touch(target, "touchmove", [[102, 112]], 10).defaultPrevented).toBe(false);
    expect(touch(target, "touchmove", [[140, 114]], 20).defaultPrevented).toBe(false);
  });

  it("treats a press-and-hold as a scrub whatever direction follows", () => {
    const target = render(<Target />).getByTestId("target");
    touch(target, "touchstart", [[100, 100]], 0);
    expect(touch(target, "touchmove", [[101, 120]], 400).defaultPrevented).toBe(true);
  });

  it("decides afresh on the next touch and leaves pinches alone", () => {
    const target = render(<Target />).getByTestId("target");
    touch(target, "touchstart", [[100, 100]]);
    touch(target, "touchmove", [[120, 100]], 10);
    touch(target, "touchend", []);
    touch(target, "touchstart", [[100, 100]]);
    expect(touch(target, "touchmove", [[100, 130]], 10).defaultPrevented).toBe(false);
    touch(target, "touchend", []);
    touch(target, "touchstart", [
      [100, 100],
      [200, 100],
    ]);
    expect(
      touch(
        target,
        "touchmove",
        [
          [90, 100],
          [210, 100],
        ],
        10,
      ).defaultPrevented,
    ).toBe(false);
  });
});
