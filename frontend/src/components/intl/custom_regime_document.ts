// The custom ("Other") country's tax rules as an editable draft, and the
// regime document saved in `intl_settings.custom_regime`. The server validates
// the document against the same schema as the built-in country packs; this
// module is the one place that knows the document's keys.
import type { IntlRegimeDocument } from "@/types/plan";

export type CapitalGainsMode = "ordinary_inclusion" | "flat" | "exempt";
export type IncomeMode = "ordinary" | "capital_gains_rates" | "flat" | "exempt";
export type FilingUnit = "individual" | "joint";
export type TradeSide = "buy" | "sell" | "both";

/** Every amount and rate as input text; rates in percent. */
export interface CustomRegimeDraft {
  filingUnit: FilingUnit;
  indexed: boolean;
  allowance: string;
  brackets: { from: string; rate: string }[];
  capitalGains: { mode: CapitalGainsMode; inclusion: string; rate: string };
  dividends: { mode: IncomeMode; rate: string };
  interest: { mode: Exclude<IncomeMode, "capital_gains_rates">; rate: string };
  wealth: {
    enabled: boolean;
    base: "net_worth" | "liquid_net_worth";
    per: "person" | "household";
    allowance: string;
    rate: string;
  };
  transaction: { enabled: boolean; rate: string; side: TradeSide };
}

export const EMPTY_CUSTOM_REGIME: CustomRegimeDraft = {
  filingUnit: "individual",
  indexed: true,
  allowance: "",
  brackets: [{ from: "0", rate: "" }],
  capitalGains: { mode: "ordinary_inclusion", inclusion: "100", rate: "" },
  dividends: { mode: "ordinary", rate: "" },
  interest: { mode: "ordinary", rate: "" },
  wealth: { enabled: false, base: "net_worth", per: "person", allowance: "", rate: "" },
  transaction: { enabled: false, rate: "", side: "buy" },
};

/** The national income layer this editor writes; other layers in a saved document are replaced. */
const NATIONAL_LAYER_ID = "income_tax";

type Doc = Record<string, unknown>;
const isDoc = (v: unknown): v is Doc => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): string => (typeof v === "number" && Number.isFinite(v) ? String(v) : "");
const percent = (v: unknown): string =>
  typeof v === "number" && Number.isFinite(v) ? String(Number((v * 100).toFixed(6))) : "";
const INCOME_MODES = ["ordinary", "capital_gains_rates", "flat", "exempt"] as const;

/** The draft for a saved regime document. The editor owns the whole document: saving rewrites it. */
export function draftFromDocument(doc: IntlRegimeDocument | null | undefined): CustomRegimeDraft {
  if (!isDoc(doc)) return structuredClone(EMPTY_CUSTOM_REGIME);
  const meta = isDoc(doc.meta) ? doc.meta : {};
  const layers = Array.isArray(doc.national) ? doc.national.filter(isDoc) : [];
  const national = layers[0] ?? {};
  const brackets = Array.isArray(national.brackets) ? national.brackets.filter(isDoc) : [];
  const allowance = isDoc(national.allowance) ? national.allowance.amount : undefined;
  const cg = isDoc(doc.capital_gains) ? doc.capital_gains : {};
  const dividends = isDoc(doc.dividends) ? doc.dividends : {};
  const div = isDoc(dividends.qualified) ? dividends.qualified : {};
  const int = isDoc(doc.interest) ? doc.interest : {};
  const wealth = isDoc(doc.wealth_tax) && doc.wealth_tax.enabled !== false ? doc.wealth_tax : null;
  const trade =
    isDoc(doc.transaction_tax) && doc.transaction_tax.enabled !== false
      ? doc.transaction_tax
      : null;
  const cgMode =
    (["ordinary_inclusion", "flat", "exempt"] as const).find((m) => m === cg.mode) ??
    "ordinary_inclusion";
  const intMode =
    (["ordinary", "flat", "exempt"] as const).find((m) => m === int.mode) ?? "ordinary";
  return {
    filingUnit: meta.filing_unit === "joint" ? "joint" : "individual",
    indexed: meta.default_indexing !== "none",
    allowance: text(allowance),
    brackets: brackets.length
      ? brackets.map((b) => ({ from: text(b.lower), rate: percent(b.rate) }))
      : [{ from: "0", rate: "" }],
    capitalGains: {
      mode: cgMode,
      inclusion: cg.inclusion_rate == null ? "100" : percent(cg.inclusion_rate),
      rate: percent(cg.rate),
    },
    dividends: {
      mode: INCOME_MODES.find((m) => m === div.mode) ?? "ordinary",
      rate: percent(div.rate),
    },
    interest: { mode: intMode, rate: percent(int.rate) },
    wealth: wealth
      ? {
          enabled: true,
          base: wealth.base === "liquid_net_worth" ? "liquid_net_worth" : "net_worth",
          per: wealth.unit === "household" ? "household" : "person",
          allowance: text(wealth.allowance),
          rate: percent(wealth.rate),
        }
      : { ...EMPTY_CUSTOM_REGIME.wealth },
    transaction: trade
      ? {
          enabled: true,
          rate: percent(trade.rate),
          side: (["buy", "sell", "both"] as const).find((s) => s === trade.applies_to) ?? "both",
        }
      : { ...EMPTY_CUSTOM_REGIME.transaction },
  };
}

export type DraftErrors = Partial<Record<string, string>>;

function amount(
  value: string,
  label: string,
  errors: DraftErrors,
  key: string,
  required = false,
): number | null {
  const t = value.trim();
  if (!t) {
    if (required) errors[key] = `Enter ${label}.`;
    return null;
  }
  const n = Number(t);
  if (!Number.isFinite(n) || n < 0) {
    errors[key] = `${label[0].toUpperCase()}${label.slice(1)} must be 0 or more.`;
    return null;
  }
  return n;
}

function rate(value: string, label: string, errors: DraftErrors, key: string): number | null {
  const t = value.trim();
  const n = Number(t);
  if (!t || !Number.isFinite(n) || n < 0 || n > 100) {
    errors[key] = `Enter ${label} from 0 to 100%.`;
    return null;
  }
  return Number((n / 100).toFixed(10));
}

/**
 * The regime document for a draft, or the input errors keyed by field. The
 * base year is the plan's first year; thresholds grow with plan inflation
 * from there unless indexing is off.
 */
export function documentFromDraft(
  draft: CustomRegimeDraft,
  context: { baseYear: number; currency: string },
): { document: IntlRegimeDocument } | { errors: DraftErrors } {
  const errors: DraftErrors = {};
  const rows = draft.brackets.map((b, i) => ({
    lower: amount(b.from, "a starting income", errors, `bracket_${i}_from`, true),
    rate: rate(b.rate, "a rate", errors, `bracket_${i}_rate`),
  }));
  if (rows.length === 0) errors.brackets = "Add at least one bracket.";
  else if (rows[0].lower !== 0 && errors.bracket_0_from === undefined)
    errors.bracket_0_from = "The first bracket starts at 0.";
  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1].lower;
    const cur = rows[i].lower;
    if (prev != null && cur != null && cur <= prev)
      errors[`bracket_${i}_from`] = "Each bracket starts above the one before.";
  }
  const allowance = amount(draft.allowance, "an allowance", errors, "allowance");
  const capitalGains: Doc = { mode: draft.capitalGains.mode };
  if (draft.capitalGains.mode === "ordinary_inclusion")
    capitalGains.inclusion_rate = rate(
      draft.capitalGains.inclusion,
      "an inclusion rate",
      errors,
      "cg_inclusion",
    );
  if (draft.capitalGains.mode === "flat")
    capitalGains.rate = rate(draft.capitalGains.rate, "a capital gains rate", errors, "cg_rate");
  const dividend: Doc = { mode: draft.dividends.mode };
  if (draft.dividends.mode === "flat")
    dividend.rate = rate(draft.dividends.rate, "a dividend rate", errors, "dividend_rate");
  const interest: Doc = { mode: draft.interest.mode };
  if (draft.interest.mode === "flat")
    interest.rate = rate(draft.interest.rate, "an interest rate", errors, "interest_rate");
  let wealth: Doc | null = null;
  if (draft.wealth.enabled) {
    wealth = {
      unit: draft.wealth.per,
      base: draft.wealth.base,
      allowance:
        amount(draft.wealth.allowance, "a wealth tax allowance", errors, "wealth_allowance") ?? 0,
      rate: rate(draft.wealth.rate, "a wealth tax rate", errors, "wealth_rate"),
    };
  }
  let trade: Doc | null = null;
  if (draft.transaction.enabled) {
    trade = {
      rate: rate(draft.transaction.rate, "a transaction tax rate", errors, "transaction_rate"),
      applies_to: draft.transaction.side,
      account_categories: ["taxable"],
    };
  }
  if (Object.keys(errors).length) return { errors };
  // Contiguous brackets: each ends where the next starts; the last is open-ended.
  const brackets = rows.map((row, i) => ({
    lower: row.lower,
    upper: i + 1 < rows.length ? rows[i + 1].lower : null,
    rate: row.rate,
  }));
  const national: Doc = {
    id: NATIONAL_LAYER_ID,
    label: "Income tax",
    category: "income_national",
    brackets,
  };
  if (allowance != null && allowance > 0) national.allowance = { amount: allowance };
  const document: Doc = {
    meta: {
      country: "XX",
      name: "Custom",
      base_year: context.baseYear,
      currency: context.currency,
      filing_unit: draft.filingUnit,
      default_indexing: draft.indexed ? "inflation" : "none",
    },
    national: [national],
    capital_gains: capitalGains,
    dividends: { qualified: dividend, other: { ...dividend } },
    interest,
  };
  if (wealth) document.wealth_tax = wealth;
  if (trade) document.transaction_tax = trade;
  return { document };
}
