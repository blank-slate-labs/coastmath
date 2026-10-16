import { bisector } from "d3-array";
import type { YearSnapshot } from "@/types/plan";

/** Index of the projection year nearest a (fractional) year, for chart hover and scrubbing. */
export const yearBisector = bisector<YearSnapshot, number>((snapshot) => snapshot.year).center;

/** The same over a plain, ascending list of years. */
export const yearValueBisector = bisector<number, number>((year) => year).center;
