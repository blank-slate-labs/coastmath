import { useEffect } from "react";

import { setDisplayCurrency } from "@/utils/format";

/**
 * Prints money in the open plan's currency while the planner is mounted.
 * Set during render, so the first paint of every child already uses it;
 * unmounting restores USD for the pages outside the planner.
 */
export function usePlanDisplayCurrency(code: string | null | undefined): void {
  setDisplayCurrency(code);
  useEffect(() => () => setDisplayCurrency(null), []);
}
