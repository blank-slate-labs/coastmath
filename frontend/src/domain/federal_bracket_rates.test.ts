import { describe, expect, it } from "vitest";
import type { TaxSettings } from "@/types/plan";
import { TOP_BRACKET_BOUND, fillableBracketRates, planBracketRates } from "./federal_bracket_rates";

const settings = (value: Partial<TaxSettings>) => value as TaxSettings;

describe("fillableBracketRates", () => {
  it("leaves out the built-in top bracket", () => {
    expect(fillableBracketRates(null)).toEqual([0.1, 0.12, 0.22, 0.24, 0.32, 0.35]);
    expect(planBracketRates(null)).toEqual([0.1, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37]);
  });

  it("leaves out a custom bracket left open but keeps a custom top that has a bound", () => {
    expect(
      fillableBracketRates(
        settings({
          federal_brackets: [
            [50000, 0.1],
            [TOP_BRACKET_BOUND, 0.2],
          ],
        }),
      ),
    ).toEqual([0.1]);
    expect(
      fillableBracketRates(
        settings({
          federal_brackets: [
            [50000, 0.1],
            [400000, 0.2],
          ],
        }),
      ),
    ).toEqual([0.1, 0.2]);
    expect(
      planBracketRates(
        settings({
          federal_brackets: [
            [50000, 0.1],
            [TOP_BRACKET_BOUND, 0.2],
          ],
        }),
      ),
    ).toEqual([0.1, 0.2]);
  });

  it("offers a rate that has a top in any schedule the plan installs", () => {
    const scheduled = settings({
      federal_brackets: [
        [50000, 0.1],
        [TOP_BRACKET_BOUND, 0.2],
      ],
      scheduled_changes: [
        { year: 2030, settings: { federal_brackets: [] } },
        {
          year: 2034,
          settings: {
            federal_brackets: [
              [80000, 0.2],
              [TOP_BRACKET_BOUND, 0.4],
            ],
          },
        },
      ],
    } as Partial<TaxSettings>);
    expect(fillableBracketRates(scheduled)).toEqual([0.1, 0.12, 0.2, 0.22, 0.24, 0.32, 0.35]);
  });
});
