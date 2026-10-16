import { format } from "d3-format";

// Built once: d3's `format(specifier)` parses the specifier on every call.
const oneDecimal = format(",.1f");
const wholeNumber = format(",.0f");

// --- Display currency -------------------------------------------------------
// A plan is single-currency; its ISO 4217 code only changes how amounts print.
// The planner sets the open plan's code (`setDisplayCurrency`) and restores USD
// when it closes, so marketing pages and US plans keep the exact USD output.

const DEFAULT_CURRENCY = "USD";
let activeCurrency = DEFAULT_CURRENCY;

/** An English locale of a country that uses the currency, so symbols and grouping read locally. */
const CURRENCY_LOCALES: Readonly<Record<string, string>> = {
  USD: "en-US",
  CAD: "en-CA",
  GBP: "en-GB",
  EUR: "en-IE",
  AUD: "en-AU",
  NZD: "en-NZ",
  HKD: "en-HK",
  SGD: "en-SG",
  ILS: "en-IL",
  CHF: "en-CH",
  INR: "en-IN",
  ZAR: "en-ZA",
  NOK: "en-NO",
  SEK: "en-SE",
  DKK: "en-DK",
  JPY: "en-JP",
  CNY: "en-CN",
  BRL: "en-BR",
  MXN: "en-MX",
};

function normalizeCurrency(code: string | null | undefined): string {
  const upper = (code ?? "").trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(upper)) return DEFAULT_CURRENCY;
  try {
    new Intl.NumberFormat("en-US", { style: "currency", currency: upper });
    return upper;
  } catch {
    return DEFAULT_CURRENCY;
  }
}

/** Sets the currency every shared money formatter uses; an invalid or missing code means USD. */
export function setDisplayCurrency(code: string | null | undefined): void {
  activeCurrency = normalizeCurrency(code);
}

/** The ISO 4217 code money currently prints in. */
export function displayCurrency(): string {
  return activeCurrency;
}

/** The locale used to print a currency. */
export function currencyLocale(code: string = activeCurrency): string {
  return CURRENCY_LOCALES[code] ?? "en-US";
}

interface CurrencyParts {
  symbol: string;
  prefix: boolean;
  spaced: boolean;
  full: Intl.NumberFormat;
}
const partsCache = new Map<string, CurrencyParts>();

function currencyParts(code: string): CurrencyParts {
  const cached = partsCache.get(code);
  if (cached) return cached;
  const locale = currencyLocale(code);
  const full = new Intl.NumberFormat(locale, {
    style: "currency",
    currency: code,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
  const parts = new Intl.NumberFormat(locale, { style: "currency", currency: code }).formatToParts(
    1,
  );
  const symbolIndex = parts.findIndex((part) => part.type === "currency");
  const numberIndex = parts.findIndex((part) => part.type === "integer");
  const prefix = symbolIndex < numberIndex;
  const between = prefix
    ? parts.slice(symbolIndex + 1, numberIndex)
    : parts.slice(numberIndex + 1, symbolIndex);
  const spaced = between.some((part) => part.type === "literal" && /\s/.test(part.value));
  const result = { symbol: parts[symbolIndex]?.value ?? code, prefix, spaced, full };
  partsCache.set(code, result);
  return result;
}

/** "$", "€", "£", "CHF"… for the display currency; "$" for USD. */
export function currencySymbol(code: string = activeCurrency): string {
  return code === DEFAULT_CURRENCY ? "$" : currencyParts(code).symbol;
}

/**
 * Currency-neutral wording for a field label or help text in non-USD plans:
 * a "$" unit ("($)", "($ per year", "($/yr", a leading "$ per year") becomes
 * the display currency's symbol, "today's dollars"/"today's $" becomes
 * "today's money" and "nominal dollars" becomes "nominal amounts". USD plans
 * get the label back unchanged.
 */
export function moneyLabel(label: string): string {
  if (activeCurrency === DEFAULT_CURRENCY) return label;
  const symbol = currencySymbol();
  return label
    .replace(/\b([Tt]oday[’']s) (?:dollars\b|\$)/g, (_, today: string) => `${today} money`)
    .replace(/\b([Nn])ominal dollars\b/g, (_, n: string) => `${n}ominal amounts`)
    .replace(/\(\$/g, () => `(${symbol}`)
    .replace(/^\$(?=[ /])/, () => symbol);
}

/**
 * Wording for an amount's basis: the US wording ("Future dollars", "Today's $")
 * in USD plans, currency-neutral wording ("Future (nominal) amounts",
 * "Today's money") in plans in any other currency.
 */
export function dollarsOr(usd: string, other: string): string {
  return activeCurrency === DEFAULT_CURRENCY ? usd : other;
}

/** Attaches the currency symbol to an already formatted number, in the currency's own order. */
function withSymbol(sign: string, body: string, code: string): string {
  if (code === DEFAULT_CURRENCY) return `${sign}$${body}`;
  const { symbol, prefix, spaced } = currencyParts(code);
  const gap = spaced ? "\u00a0" : "";
  return prefix ? `${sign}${symbol}${gap}${body}` : `${sign}${body}${gap}${symbol}`;
}

/** $291k / $11.3M / $2.4B / $1.1T / $850 — sign-aware compact currency for axes, labels, and tiles.
 * Values past a quadrillion (or non-finite) are numerically meaningless and print in exponent form so
 * they never produce a 60-digit string that breaks a layout. */
export const compactCurrency = (value: number): string => {
  if (!Number.isFinite(value)) return "—";
  const code = activeCurrency;
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1e15) return withSymbol(sign, abs.toExponential(1), code);
  if (abs >= 1e12) return withSymbol(sign, `${oneDecimal(abs / 1e12)}T`, code);
  if (abs >= 1e9) return withSymbol(sign, `${oneDecimal(abs / 1e9)}B`, code);
  if (abs >= 1_000_000) return withSymbol(sign, `${oneDecimal(abs / 1_000_000)}M`, code);
  if (abs >= 1_000) return withSymbol(sign, `${wholeNumber(abs / 1_000)}k`, code);
  return withSymbol(sign, wholeNumber(abs), code);
};

/** Puts the display currency's symbol on a formatted amount: "$12k" in USD, "12k kr" in NOK. */
export const withCurrency = (body: string): string => withSymbol("", body, activeCurrency);

const intlCompactFormatters = new Map<string, Intl.NumberFormat>();

/** Intl compact notation in the display currency ("$1.2M", "$250K" in USD). */
export const intlCompactCurrency = (value: number): string => {
  const code = activeCurrency;
  let formatter = intlCompactFormatters.get(code);
  if (!formatter) {
    formatter = new Intl.NumberFormat(currencyLocale(code), {
      style: "currency",
      currency: code,
      notation: "compact",
      maximumFractionDigits: 1,
    });
    intlCompactFormatters.set(code, formatter);
  }
  return formatter.format(value);
};

/** Explicit sign for deltas and cash flow: +$25k / -$4k. */
export const signedCompactCurrency = (value: number): string =>
  value > 0 ? `+${compactCurrency(value)}` : compactCurrency(value);

const fullCurrencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

/** $290,512 — for tooltips and tables. Implausible magnitudes fall back to the compact exponent form. */
export const fullCurrency = (value: number): string => {
  if (!Number.isFinite(value) || Math.abs(value) >= 1e15) return compactCurrency(value);
  return activeCurrency === DEFAULT_CURRENCY
    ? fullCurrencyFormatter.format(value)
    : currencyParts(activeCurrency).full.format(value);
};

/** A whole amount in the display currency with no symbol (table cells under a labelled header). */
export const plainAmount = (value: number): string =>
  value.toLocaleString(currencyLocale(), { maximumFractionDigits: 0 });

/** 0.1023 → 10.2% */
export const pct = (ratio: number, digits = 1): string => `${(ratio * 100).toFixed(digits)}%`;

/** A rate with no trailing decimals for whole percents: 0.24 → "24%", 0.225 → "22.5%". */
export const ratePct = (ratio: number): string => `${Number((ratio * 100).toFixed(2))}%`;
/** Format an ISO calendar date without shifting it through the local timezone. */
export function calendarDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * A server timestamp as a date in the viewer's own zone, e.g. "Oct 12, 2026". Every stored time is
 * UTC, and a timestamp read back without an offset (SQLite) is UTC too, never local time.
 */
export function localDay(value: string | null | undefined): string | null {
  if (!value) return null;
  const zoned = /[zZ]|[+-]\d\d:?\d\d$/.test(value) || !value.includes("T") ? value : `${value}Z`;
  const date = new Date(zoned);
  return Number.isNaN(date.getTime())
    ? null
    : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
