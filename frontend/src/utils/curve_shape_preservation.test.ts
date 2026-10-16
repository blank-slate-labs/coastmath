import { describe, expect, it } from "vitest";
import { catmullRomInterpolate } from "./spline";
import { buildDeflators } from "./currency";
import type { AssumptionCurve } from "@/types/plan";

describe("Shape-preserving curves", () => {
  it("keeps uneven plateaus exact in display and currency conversion", () => {
    const points = [
      { age: 25, value: 0.1 },
      { age: 30, value: 0.1 },
      { age: 31, value: 0.02 },
      { age: 90, value: 0.02 },
    ];
    for (let age = 31; age <= 90; age++)
      expect(catmullRomInterpolate(points, age)).toBeCloseTo(0.02, 14);
    const curve = {
      mode: "curve",
      control_points: points.map((p) => ({ x: p.age, y: p.value })),
    } as AssumptionCurve;
    expect(buildDeflators(curve, 0, 2031, 59, 2000)[59]).toBeCloseTo(1.02 ** 59, 10);
  });
  it("matches independent endpoint cubic and two-point linear answers", () => {
    expect(
      catmullRomInterpolate(
        [
          { age: 0, value: 0 },
          { age: 1, value: 1 },
          { age: 2, value: 1 },
        ],
        0.5,
      ),
    ).toBeCloseTo(0.6875, 14);
    expect(
      catmullRomInterpolate(
        [
          { age: 0, value: 0 },
          { age: 2, value: 1 },
        ],
        0.5,
      ),
    ).toBeCloseTo(0.25, 14);
  });
});
