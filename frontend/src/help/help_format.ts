/** Deterministic number formatting: prerendered HTML and the hydrated page must print identical text. */

export type ValueFormat = "usd" | "usd_cents" | "pct" | "num" | "year" | "age";

const group = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

function fixed(value: number, decimals: number) {
  const [whole, fraction] = Math.abs(value).toFixed(decimals).split(".");
  return group(whole) + (fraction ? `.${fraction}` : "");
}

const minus = (value: number, text: string) =>
  value < 0 && Number(text.replace(/[^0-9.]/g, "")) !== 0 ? `−${text}` : text;

/** Full-precision display, e.g. $21,097 or 4.5%. `digits` sets decimals for pct/num. */
export function formatValue(value: number, format: ValueFormat = "usd", digits?: number): string {
  switch (format) {
    case "usd":
      return minus(value, `$${fixed(value, 0)}`);
    case "usd_cents":
      return minus(value, `$${fixed(value, 2)}`);
    case "pct":
      return minus(value, `${fixed(value * 100, digits ?? 1)}%`);
    case "num":
      return minus(value, fixed(value, digits ?? 0));
    case "year":
      return String(Math.round(value));
    case "age":
      return String(Math.round(value));
  }
}

/** Short axis-tick form: $250K, $1.2M, 12%. */
export function formatTick(value: number, format: ValueFormat = "usd"): string {
  if (format === "usd" || format === "usd_cents") {
    const abs = Math.abs(value);
    const short =
      abs >= 1e6 ? `${trim(abs / 1e6)}M` : abs >= 1e3 ? `${trim(abs / 1e3)}K` : trim(abs);
    return minus(value, `$${short}`);
  }
  if (format === "pct") return minus(value, `${trim(Math.abs(value) * 100)}%`);
  return formatValue(value, format);
}

function trim(value: number) {
  const rounded = value >= 100 ? Math.round(value) : Math.round(value * 10) / 10;
  return group(String(rounded));
}
