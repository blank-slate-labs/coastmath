/** English month names, January first. Index with `month - 1` for a 1-based month. */
export const MONTH_NAMES = Array.from({ length: 12 }, (_, i) =>
  new Date(2000, i, 1).toLocaleString("en-US", { month: "long" }),
);
