// Which countries' tax rules a plan uses, and what that hides or shows in the
// web. The server owns the rules (GET /tax-regimes and the engine); these
// helpers only decide which controls and labels the web offers.
import type {
  AccountType,
  IntlAccountCategory,
  PlanData,
  ResidencyPeriod,
  TaxRegimeAccountKind,
  TaxRegimeBenefitRule,
  TaxRegimeCountry,
} from "@/types/plan";

export const US_COUNTRY = "US";
/** The user-defined ("Other") country, taxed by the plan's own regime document. */
export const CUSTOM_COUNTRY = "XX";

type CountryPlan = Pick<PlanData, "tax_country" | "tax_region" | "residency_periods">;

/** The plan's starting tax country; plans saved before countries existed are US plans. */
export function planTaxCountry(plan: Pick<PlanData, "tax_country"> | null | undefined): string {
  return plan?.tax_country || US_COUNTRY;
}

/** A residency period's country; null means the plan's own country. */
export function periodCountry(
  period: Pick<ResidencyPeriod, "country">,
  plan: Pick<PlanData, "tax_country">,
): string {
  return period.country || planTaxCountry(plan);
}

/**
 * Every country the plan lives in. The plan's own country counts unless a
 * residency period replaces it from the plan's start (no start milestone or year).
 */
export function planCountries(plan: CountryPlan | null | undefined): string[] {
  if (!plan) return [US_COUNTRY];
  const periods = plan.residency_periods ?? [];
  const countries = new Set<string>();
  const replacedAtStart = periods.some((p) => p.start_milestone_id == null && p.start_year == null);
  if (!replacedAtStart) countries.add(planTaxCountry(plan));
  for (const period of periods) countries.add(periodCountry(period, plan));
  return [...countries];
}

/** "us": every year is a US year; "non_us": none is; "mixed": the plan moves between them. */
export type UsCoverage = "us" | "mixed" | "non_us";

export function usCoverage(plan: CountryPlan | null | undefined): UsCoverage {
  const countries = planCountries(plan);
  const hasUs = countries.includes(US_COUNTRY);
  if (!hasUs) return "non_us";
  return countries.length > 1 ? "mixed" : "us";
}

let displayNames: Intl.DisplayNames | null | undefined;

/** "France" for "FR"; the registry's name wins when it is known. */
export function countryName(
  code: string | null | undefined,
  countries?: readonly TaxRegimeCountry[] | null,
): string {
  if (!code) return "";
  if (code === US_COUNTRY) return "United States";
  if (code === CUSTOM_COUNTRY)
    return countries?.find((c) => c.code === code)?.name ?? "Other (custom rules)";
  const known = countries?.find((c) => c.code === code)?.name;
  if (known) return known;
  if (displayNames === undefined) {
    try {
      displayNames = new Intl.DisplayNames(["en"], { type: "region" });
    } catch {
      displayNames = null;
    }
  }
  return displayNames?.of(code) ?? code;
}

/** Currencies offered in the picker, most likely first; the plan's saved code is always kept. */
export const CURRENCY_CHOICES: readonly string[] = [
  "USD",
  "CAD",
  "GBP",
  "EUR",
  "AUD",
  "NZD",
  "HKD",
  "SGD",
  "CHF",
  "ILS",
  "JPY",
  "CNY",
  "INR",
  "NOK",
  "SEK",
  "DKK",
  "BRL",
  "MXN",
  "ZAR",
];

export function currencyChoices(
  saved: string | null | undefined,
  suggested?: string | null,
): string[] {
  const list = [...CURRENCY_CHOICES];
  for (const code of [suggested, saved]) if (code && !list.includes(code)) list.unshift(code);
  return list;
}

/** The region a plan or move starts in when it enters a country; null without regions. */
export function defaultRegion(country: TaxRegimeCountry | null | undefined): string | null {
  if (!country?.regions.length) return null;
  return country.regions.some((r) => r.code === country.default_region)
    ? (country.default_region ?? null)
    : country.regions[0].code;
}

/** Plan settings that apply only in US years, named in the country-switch confirmation. */
export const US_ONLY_SETTINGS: readonly string[] = [
  "Federal, state and local income tax, and the state and locality on this page",
  "FICA payroll tax and Social Security benefit taxation",
  "Marketplace (ACA) coverage, Medicare and IRMAA",
  "US tax targets, Roth conversions and 72(t) early withdrawals",
  "US estate tax and estimated tax payments",
];

/**
 * The account type an international account kind is saved with, matching the
 * server's mapping (it overrides a mismatch). The kind's own rules replace the
 * type's US rules; the type keeps the record readable for older clients.
 */
export const INTL_KIND_ACCOUNT_TYPE: Readonly<Record<IntlAccountCategory, AccountType>> = {
  cash: "savings",
  taxable: "taxable_brokerage",
  tax_deferred: "other",
  tax_free: "other",
};

/** US account types with no US-only tax rules, offered in every plan. */
export const COUNTRY_NEUTRAL_ACCOUNT_TYPES: ReadonlySet<AccountType> = new Set<AccountType>([
  "checking",
  "savings",
  "taxable_brokerage",
  "other",
]);

function registryCountries(
  countries: readonly TaxRegimeCountry[] | null | undefined,
  codes: readonly string[],
): TaxRegimeCountry[] {
  return codes.flatMap((code) => countries?.find((c) => c.code === code) ?? []);
}

/** Registry account kinds of the plan's countries, grouped by country. */
export function accountKindsFor(
  countries: readonly TaxRegimeCountry[] | null | undefined,
  codes: readonly string[],
): { country: TaxRegimeCountry; kinds: TaxRegimeAccountKind[] }[] {
  return registryCountries(countries, codes)
    .filter((country) => country.account_kinds.length > 0)
    .map((country) => ({ country, kinds: country.account_kinds }));
}

/** Every registry account kind by id, from any country (a saved kind may be from a country the plan left). */
export function findAccountKind(
  countries: readonly TaxRegimeCountry[] | null | undefined,
  id: string | null | undefined,
): TaxRegimeAccountKind | null {
  if (!id || !countries) return null;
  for (const country of countries) {
    const kind = country.account_kinds.find((k) => k.id === id);
    if (kind) return kind;
  }
  return null;
}

/** Account kinds of the plan's countries whose unused contribution room carries forward. */
export function roomKindsFor(
  countries: readonly TaxRegimeCountry[] | null | undefined,
  codes: readonly string[],
): TaxRegimeAccountKind[] {
  return registryCountries(countries, codes).flatMap((country) =>
    country.account_kinds.filter((kind) => kind.carries_room),
  );
}

/** Benefit rules of the plan's countries. */
export function benefitRulesFor(
  countries: readonly TaxRegimeCountry[] | null | undefined,
  codes: readonly string[],
): TaxRegimeBenefitRule[] {
  return registryCountries(countries, codes).flatMap((country) => country.benefit_rules);
}

const CATEGORY_LABELS: Readonly<Record<IntlAccountCategory, string>> = {
  cash: "Cash",
  taxable: "Taxable",
  tax_deferred: "Tax-deferred",
  tax_free: "Tax-free",
};

export const intlCategoryLabel = (category: IntlAccountCategory): string =>
  CATEGORY_LABELS[category] ?? category;

/** True when a year was taxed under another country's rules. */
export const isIntlYear = (taxCountry: string | null | undefined): boolean =>
  !!taxCountry && taxCountry !== US_COUNTRY;
