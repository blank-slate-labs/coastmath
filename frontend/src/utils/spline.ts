export interface ControlPoint {
  age: number;
  value: number;
}

/** Shape-preserving PCHIP. The exported name is retained for compatibility.
 * Matches backend/coastmath/engine/assumption_curves.py, including duplicate ages.
 */
export function catmullRomInterpolate(points: ControlPoint[], targetAge: number): number {
  const values = new Map(points.map((p) => [p.age, p.value]));
  const x = [...values.keys()].sort((a, b) => a - b);
  const y = x.map((age) => values.get(age)!);
  const n = x.length;
  if (!n) return 0;
  if (targetAge <= x[0]) return y[0];
  if (targetAge >= x[n - 1]) return y[n - 1];
  const h = x.slice(1).map((age, i) => age - x[i]);
  const d = h.map((width, i) => (y[i + 1] - y[i]) / width);
  const m = new Array<number>(n).fill(d[0]);
  if (n > 2) {
    const endpoint = (h0: number, h1: number, d0: number, d1: number) => {
      const slope = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1);
      if (slope * d0 <= 0) return 0;
      if (d0 * d1 <= 0 && Math.abs(slope) > Math.abs(3 * d0)) return 3 * d0;
      return slope;
    };
    m[0] = endpoint(h[0], h[1], d[0], d[1]);
    m[n - 1] = endpoint(h[n - 2], h[n - 3], d[n - 2], d[n - 3]);
    for (let i = 1; i < n - 1; i++) {
      if (d[i - 1] * d[i] <= 0) m[i] = 0;
      else {
        const w1 = 2 * h[i] + h[i - 1],
          w2 = h[i] + 2 * h[i - 1];
        m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i]);
      }
    }
  }
  const i = x.findIndex((age, j) => j > 0 && targetAge <= age) - 1;
  const t = (targetAge - x[i]) / h[i];
  const value =
    (2 * t ** 3 - 3 * t ** 2 + 1) * y[i] +
    (t ** 3 - 2 * t ** 2 + t) * h[i] * m[i] +
    (-2 * t ** 3 + 3 * t ** 2) * y[i + 1] +
    (t ** 3 - t ** 2) * h[i] * m[i + 1];
  return Math.min(Math.max(y[i], y[i + 1]), Math.max(Math.min(y[i], y[i + 1]), value));
}

/**
 * Generate a dense array of interpolated points for curve rendering.
 */
export function generateCurve(
  points: ControlPoint[],
  startAge: number,
  endAge: number,
  step: number = 0.5,
): ControlPoint[] {
  if (points.length === 0) return [];

  const result: ControlPoint[] = [];
  for (let age = startAge; age <= endAge; age += step) {
    result.push({ age, value: catmullRomInterpolate(points, age) });
  }

  // Ensure we include the exact endAge if the step didn't land on it
  const last = result[result.length - 1];
  if (last && Math.abs(last.age - endAge) > 1e-9) {
    result.push({ age: endAge, value: catmullRomInterpolate(points, endAge) });
  }

  return result;
}

/**
 * Legacy wrapper — preserves the old stub signature for backward compatibility.
 */
export function catmullRom(points: [number, number][], t: number): [number, number] {
  const controlPoints = points.map(([age, value]) => ({ age, value }));
  if (controlPoints.length === 0) return [0, 0];
  if (controlPoints.length === 1) return points[0];

  // Map t (0..1) to the age range
  const sorted = [...controlPoints].sort((a, b) => a.age - b.age);
  const minAge = sorted[0].age;
  const maxAge = sorted[sorted.length - 1].age;
  const targetAge = minAge + t * (maxAge - minAge);

  const value = catmullRomInterpolate(controlPoints, targetAge);
  return [targetAge, value];
}
