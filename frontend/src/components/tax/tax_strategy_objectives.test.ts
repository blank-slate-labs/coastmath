import { describe, expect, it } from "vitest";
import { objectiveOption, STRATEGY_OBJECTIVES } from "./tax_strategy_objectives";

describe("strategy objectives", () => {
  it("lists end-of-plan wealth, taxes, health coverage, then RMDs, as on iOS", () => {
    expect(STRATEGY_OBJECTIVES.map((o) => o.value)).toEqual([
      "final_net_worth",
      "net_legacy",
      "lifetime_taxes",
      "lifetime_effective_tax_rate",
      "lifetime_taxes_and_healthcare",
      "total_irmaa_surcharge",
      "total_aca_subsidies",
      "total_rmd_distributions",
    ]);
  });

  it("falls back to net estate for an unknown objective", () => {
    expect(objectiveOption("unknown" as never).value).toBe("net_legacy");
  });
});
