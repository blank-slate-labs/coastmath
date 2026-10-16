import { contentViolations, helpContent } from "./help_content_rules";
import { formatTick, formatValue } from "./help_format";
import { search, tokens } from "./help_search";

const top = (query: string) =>
  search(query)
    .slice(0, 3)
    .map((a) => a.slug);

describe("help search", () => {
  it.each([
    ["tax bill the year after I retire", "tax-payments-and-settlement"],
    ["why am I seeing withdrawals", "unexpected-withdrawals"],
    ["money left over", "savings-rules"],
    ["RMD", "required-minimum-distributions"],
    ["today’s dollars", "todays-and-future-dollars"],
    ["IRMAA", "medicare-and-irmaa"],
    ["stale projection", "saves-and-refresh"],
    ["sankey", "cash-flow-view"],
    ["monte carlo", "chance-of-success"],
  ])("finds %s", (query, slug) => {
    expect(top(query)).toContain(slug);
  });

  it("requires most meaningful words to match and ignores stop words", () => {
    expect(tokens("How do I pay the tax?")).toEqual(["pay", "tax"]);
    expect(search("zzzz qqqq")).toEqual([]);
    expect(search("   ")).toEqual([]);
  });

  it("uses body words once the index loads", () => {
    const bodies = new Map([
      [
        "expenses",
        { slug: "expenses", headings: ["Quinquennial purchases"], text: "quinquennial" },
      ],
    ]);
    expect(search("quinquennial", bodies).map((a) => a.slug)).toEqual(["expenses"]);
  });
});

describe("help formatting", () => {
  it("formats full values and ticks deterministically", () => {
    expect(formatValue(21097.4)).toBe("$21,097");
    expect(formatValue(-1500)).toBe("−$1,500");
    expect(formatValue(0.0425, "pct")).toBe("4.3%");
    expect(formatValue(0.0425, "pct", 2)).toBe("4.25%");
    expect(formatValue(26.5, "num", 1)).toBe("26.5");
    expect(formatTick(1_250_000)).toBe("$1.3M");
    expect(formatTick(250_000)).toBe("$250K");
    expect(formatTick(0.12, "pct")).toBe("12%");
  });
});

describe("help content rules", () => {
  it.each([
    "See https://www.irs.gov/publications/p590b for the table.",
    "Under 26 U.S.C. 401(a)(9)",
    "per IRC 72(t)",
    "IRS Publication 590-B lists",
    "Treas. Reg. 1.401(a)(9)-9",
    "§ 408A",
    "Rev. Proc. 2025-32 sets",
    "computed in simulator.py",
    "calls apply_growth()",
  ])("rejects %s", (text) => expect(contentViolations(`<p>${text}</p>`)).not.toEqual([]));

  it.each([
    "Required distributions start at 73 for people born 1951 through 1959.",
    "Premium tax credits are reconciled on your return.",
    'Open <a href="/help/roth-conversions">Roth conversions</a>.',
  ])("allows %s", (text) => expect(contentViolations(`<p>${text}</p>`)).toEqual([]));

  it("checks the page main, not the footer chrome", () => {
    const footer = '<footer><a href="https://example.com/download">Download</a></footer>';
    expect(
      contentViolations(helpContent(`<main id="help_main"><p>Clean.</p></main>${footer}`)),
    ).toEqual([]);
    expect(
      contentViolations(
        helpContent(`<main id="help_main"><a href="https://irs.gov">x</a></main>${footer}`),
      ),
    ).not.toEqual([]);
    expect(() => helpContent(`<p>No main.</p>${footer}`)).toThrow(/found 0/);
  });
});
