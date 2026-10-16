import { afterEach, describe, expect, it } from "vitest";
import {
  compactCurrency,
  displayCurrency,
  dollarsOr,
  fullCurrency,
  intlCompactCurrency,
  localDay,
  moneyLabel,
  setDisplayCurrency,
  signedCompactCurrency,
  withCurrency,
} from "./format";

describe("compactCurrency", () => {
  it("keeps the familiar tiers", () => {
    expect(compactCurrency(850)).toBe("$850");
    expect(compactCurrency(291_000)).toBe("$291k");
    expect(compactCurrency(11_300_000)).toBe("$11.3M");
    expect(compactCurrency(-4_000)).toBe("-$4k");
  });
  it("adds billions and trillions instead of thousands of millions", () => {
    expect(compactCurrency(2_400_000_000)).toBe("$2.4B");
    expect(compactCurrency(1.1e12)).toBe("$1.1T");
  });
  it("never prints a 60-digit string for a runaway balance", () => {
    expect(compactCurrency(-1.618791771632335e57)).toBe("-$1.6e+57");
    expect(compactCurrency(Number.NaN)).toBe("—");
    expect(fullCurrency(-1.618791771632335e57)).toBe("-$1.6e+57");
    expect(fullCurrency(290_512)).toBe("$290,512");
  });
});

describe("display currency", () => {
  afterEach(() => setDisplayCurrency(null));

  it("keeps USD output byte-identical by default and after a reset", () => {
    setDisplayCurrency("EUR");
    setDisplayCurrency(null);
    expect(displayCurrency()).toBe("USD");
    expect(fullCurrency(290_512.4)).toBe("$290,512");
    expect(compactCurrency(-4_000)).toBe("-$4k");
    expect(intlCompactCurrency(1_234_567)).toBe("$1.2M");
    expect(withCurrency("-4k")).toBe("$-4k");
    expect(moneyLabel("Balance ($)")).toBe("Balance ($)");
  });

  it("prints EUR, GBP and CAD whole amounts with their own symbols", () => {
    setDisplayCurrency("EUR");
    expect(fullCurrency(290_512.6)).toBe("€290,513");
    expect(compactCurrency(291_000)).toBe("€291k");
    expect(compactCurrency(-11_300_000)).toBe("-€11.3M");
    expect(moneyLabel("Balance ($)")).toBe("Balance (€)");
    setDisplayCurrency("gbp");
    expect(displayCurrency()).toBe("GBP");
    expect(fullCurrency(1_234.5)).toBe("£1,235");
    expect(signedCompactCurrency(25_000)).toBe("+£25k");
    setDisplayCurrency("CAD");
    expect(fullCurrency(-1_234.5)).toBe("-$1,235");
  });

  it("rounds JPY, which has no minor unit, to whole yen", () => {
    setDisplayCurrency("JPY");
    expect(fullCurrency(1_234_567.5)).toBe("¥1,234,568");
    expect(compactCurrency(850.4)).toBe("¥850");
  });

  it("puts a trailing symbol after the amount", () => {
    setDisplayCurrency("NOK");
    expect(compactCurrency(12_000)).toBe("12k kr");
    expect(withCurrency("12k")).toBe("12k kr");
  });

  it("keeps US basis wording in USD and uses currency-neutral wording otherwise", () => {
    expect(dollarsOr("Future dollars", "Future (nominal) amounts")).toBe("Future dollars");
    setDisplayCurrency("NZD");
    expect(dollarsOr("Future dollars", "Future (nominal) amounts")).toBe(
      "Future (nominal) amounts",
    );
    setDisplayCurrency("USD");
    expect(dollarsOr("Today's $", "Today's money")).toBe("Today's $");
  });

  it("makes field labels and help text currency-neutral outside USD", () => {
    const labels = [
      "Annual rent ($, today's dollars)",
      "Growth cap ($ per year, optional)",
      "Travel ($/yr, today's dollars)",
      "$ per year (today's dollars)",
      "Amount (today's $)",
      "Today's dollars (rises with inflation)",
      "Nominal dollars",
      "Annual employer cap ($, today’s dollars; optional)",
      "Spend in today's dollarsworth",
    ];
    expect(labels.map(moneyLabel)).toEqual(labels);
    setDisplayCurrency("EUR");
    expect(labels.map(moneyLabel)).toEqual([
      "Annual rent (€, today's money)",
      "Growth cap (€ per year, optional)",
      "Travel (€/yr, today's money)",
      "€ per year (today's money)",
      "Amount (today's money)",
      "Today's money (rises with inflation)",
      "Nominal amounts",
      "Annual employer cap (€, today’s money; optional)",
      "Spend in today's dollarsworth",
    ]);
    setDisplayCurrency("NOK");
    expect(moneyLabel("Balance ($)")).toBe("Balance (kr)");
  });

  it("falls back to USD for an unknown or malformed code", () => {
    setDisplayCurrency("dollars");
    expect(displayCurrency()).toBe("USD");
    setDisplayCurrency("");
    expect(fullCurrency(5)).toBe("$5");
  });
});

describe("localDay", () => {
  it("reads a timestamp without an offset as UTC, not local time", () => {
    expect(localDay("2026-10-13T00:05:00")).toBe(localDay("2026-10-13T00:05:00Z"));
    expect(localDay("2026-10-13T00:05:00+00:00")).toBe(localDay("2026-10-13T00:05:00Z"));
    expect(localDay(null)).toBeNull();
    expect(localDay("not a date")).toBeNull();
  });
});
