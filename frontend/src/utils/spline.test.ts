import { describe, it, expect } from "vitest";
import { catmullRomInterpolate, generateCurve, catmullRom, type ControlPoint } from "./spline";

describe("catmullRomInterpolate", () => {
  it("returns 0 for empty array", () => {
    expect(catmullRomInterpolate([], 50)).toBe(0);
  });

  it("returns constant value for single point", () => {
    const points: ControlPoint[] = [{ age: 30, value: 50000 }];
    expect(catmullRomInterpolate(points, 20)).toBe(50000);
    expect(catmullRomInterpolate(points, 30)).toBe(50000);
    expect(catmullRomInterpolate(points, 40)).toBe(50000);
  });

  it("interpolates linearly between two points", () => {
    const points: ControlPoint[] = [
      { age: 30, value: 0 },
      { age: 40, value: 100 },
    ];
    // With only two points mirrored, Catmull-Rom reduces to linear
    expect(catmullRomInterpolate(points, 35)).toBeCloseTo(50, 5);
  });

  it("flat-extrapolates before first point", () => {
    const points: ControlPoint[] = [
      { age: 30, value: 100 },
      { age: 40, value: 200 },
    ];
    expect(catmullRomInterpolate(points, 20)).toBe(100);
  });

  it("flat-extrapolates after last point", () => {
    const points: ControlPoint[] = [
      { age: 30, value: 100 },
      { age: 40, value: 200 },
    ];
    expect(catmullRomInterpolate(points, 50)).toBe(200);
  });

  it("returns exact values at control points", () => {
    const points: ControlPoint[] = [
      { age: 25, value: 50000 },
      { age: 35, value: 80000 },
      { age: 45, value: 100000 },
      { age: 55, value: 70000 },
    ];
    for (const p of points) {
      expect(catmullRomInterpolate(points, p.age)).toBeCloseTo(p.value, 5);
    }
  });

  it("produces smooth interpolation between points", () => {
    const points: ControlPoint[] = [
      { age: 20, value: 0 },
      { age: 40, value: 100 },
      { age: 60, value: 0 },
    ];
    const mid = catmullRomInterpolate(points, 40);
    expect(mid).toBeCloseTo(100, 5);
    // Value at 30 should be between 0 and 100
    const v30 = catmullRomInterpolate(points, 30);
    expect(v30).toBeGreaterThan(0);
    expect(v30).toBeLessThan(100);
  });

  it("handles unsorted input", () => {
    const points: ControlPoint[] = [
      { age: 40, value: 200 },
      { age: 30, value: 100 },
      { age: 50, value: 300 },
    ];
    expect(catmullRomInterpolate(points, 30)).toBeCloseTo(100, 5);
    expect(catmullRomInterpolate(points, 50)).toBeCloseTo(300, 5);
  });
});

describe("generateCurve", () => {
  it("returns empty array for empty input", () => {
    expect(generateCurve([], 20, 60)).toEqual([]);
  });

  it("generates points at specified step intervals", () => {
    const points: ControlPoint[] = [
      { age: 20, value: 100 },
      { age: 40, value: 200 },
    ];
    const curve = generateCurve(points, 20, 40, 10);
    // Should have age 20, 30, 40
    expect(curve.length).toBe(3);
    expect(curve[0].age).toBe(20);
    expect(curve[1].age).toBe(30);
    expect(curve[2].age).toBe(40);
  });

  it("includes endAge even if step does not land on it", () => {
    const points: ControlPoint[] = [
      { age: 20, value: 100 },
      { age: 40, value: 200 },
    ];
    const curve = generateCurve(points, 20, 45, 10);
    const lastPoint = curve[curve.length - 1];
    expect(lastPoint.age).toBe(45);
  });

  it("defaults to step of 0.5", () => {
    const points: ControlPoint[] = [
      { age: 30, value: 100 },
      { age: 32, value: 200 },
    ];
    const curve = generateCurve(points, 30, 32);
    // 30, 30.5, 31, 31.5, 32 = 5 points
    expect(curve.length).toBe(5);
  });
});

describe("catmullRom (legacy wrapper)", () => {
  it("returns [0,0] for empty array", () => {
    expect(catmullRom([], 0.5)).toEqual([0, 0]);
  });

  it("returns the single point for length-1 array", () => {
    expect(catmullRom([[30, 100]], 0.5)).toEqual([30, 100]);
  });

  it("interpolates using t parameter mapped to age range", () => {
    const points: [number, number][] = [
      [20, 0],
      [40, 100],
    ];
    const [age, value] = catmullRom(points, 0.5);
    expect(age).toBeCloseTo(30, 5);
    expect(value).toBeCloseTo(50, 5);
  });
});
