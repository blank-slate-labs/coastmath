// Account-type names and families, mirroring backend/coastmath/engine/account_types.py.
// The backend owns the tax rules; these sets only decide which fields and
// choices the web offers.
import type { AccountType } from "@/types/plan";

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  checking: "Checking",
  savings: "Savings",
  traditional_401k: "Traditional 401(k)",
  roth_401k: "Roth 401(k)",
  traditional_403b: "Traditional 403(b)",
  roth_403b: "Roth 403(b)",
  traditional_457b: "Traditional 457(b)",
  roth_457b: "Roth 457(b)",
  traditional_401a: "401(a)",
  traditional_ira: "Traditional IRA",
  roth_ira: "Roth IRA",
  taxable_brokerage: "Taxable Brokerage",
  hsa: "HSA",
  five_twenty_nine: "529 Plan",
  other: "Other",
};

/** Account-type choices by category, in display order. */
export const ACCOUNT_TYPE_GROUPS: { label: string; types: AccountType[] }[] = [
  {
    label: "Employer plans",
    types: [
      "traditional_401k",
      "roth_401k",
      "traditional_403b",
      "roth_403b",
      "traditional_457b",
      "roth_457b",
      "traditional_401a",
    ],
  },
  { label: "IRAs", types: ["traditional_ira", "roth_ira"] },
  { label: "Taxable and cash", types: ["checking", "savings", "taxable_brokerage"] },
  { label: "Other", types: ["hsa", "five_twenty_nine", "other"] },
];

export const ACCOUNT_TYPE_OPTIONS: { value: AccountType; label: string }[] =
  ACCOUNT_TYPE_GROUPS.flatMap((group) =>
    group.types.map((value) => ({ value, label: ACCOUNT_TYPE_LABELS[value] })),
  );

/** A saved type's name, or ``fallback`` (the raw value by default) for an unknown one. */
export const accountTypeLabel = (type: string, fallback: string = type): string =>
  ACCOUNT_TYPE_LABELS[type as AccountType] ?? fallback;

const TRADITIONAL_EMPLOYER: AccountType[] = [
  "traditional_401k",
  "traditional_403b",
  "traditional_457b",
  "traditional_401a",
];
const ROTH_EMPLOYER: AccountType[] = ["roth_401k", "roth_403b", "roth_457b"];
const set = (...types: AccountType[]): ReadonlySet<string> => new Set<string>(types);

export const ROTH_EMPLOYER_PLAN_TYPES = set(...ROTH_EMPLOYER);
export const EMPLOYER_PLAN_TYPES = set(...TRADITIONAL_EMPLOYER, ...ROTH_EMPLOYER);
/** Employer contributions only: no employee deferrals. */
export const EMPLOYER_ONLY_PLAN_TYPES = set("traditional_401a");
/** Plans that take employee deferrals (the 402(g) or 457(b) limit). */
export const ELECTIVE_DEFERRAL_TYPES = set(
  ...TRADITIONAL_EMPLOYER.filter((t) => t !== "traditional_401a"),
  ...ROTH_EMPLOYER,
);
export const TRADITIONAL_RETIREMENT_TYPES = set(...TRADITIONAL_EMPLOYER, "traditional_ira");
export const ROTH_TYPES = set(...ROTH_EMPLOYER, "roth_ira");
/** Accounts that can be inherited and hold Roth or beneficiary history. */
export const RETIREMENT_ACCOUNT_TYPES = set(
  ...TRADITIONAL_EMPLOYER,
  ...ROTH_EMPLOYER,
  "traditional_ira",
  "roth_ira",
);
/** Withdrawals before 59½ carry the 10% additional tax; a governmental 457(b) carries none. */
export const EARLY_WITHDRAWAL_PENALTY_TYPES = set(
  "traditional_401k",
  "roth_401k",
  "traditional_403b",
  "roth_403b",
  "traditional_401a",
  "traditional_ira",
  "roth_ira",
);
/** A 72(t) series matters only where the 10% applies. */
/** Workplace plans where a separation from the employer can lift the 10% tax from age 55 (never IRAs, never 457(b)). */
export const RULE_OF_55_TYPES: ReadonlySet<string> = new Set(
  [...EMPLOYER_PLAN_TYPES].filter((t) => !t.endsWith("457b")),
);
export const SEPP_ELIGIBLE_TYPES = set(
  "traditional_ira",
  "traditional_401k",
  "traditional_403b",
  "traditional_401a",
);
/** One person owns these by law; the backend rejects a joint owner. */
export const INDIVIDUAL_ONLY_ACCOUNT_TYPES = set(
  ...TRADITIONAL_EMPLOYER,
  ...ROTH_EMPLOYER,
  "traditional_ira",
  "roth_ira",
  "hsa",
);
/** Destinations a payroll rule may fund. */
export const PAYROLL_TARGET_TYPES = set(...TRADITIONAL_EMPLOYER, ...ROTH_EMPLOYER, "hsa");

const FAMILY: Partial<Record<AccountType, string>> = {
  traditional_401k: "401(k)",
  roth_401k: "401(k)",
  traditional_403b: "403(b)",
  roth_403b: "403(b)",
  traditional_457b: "457(b)",
  roth_457b: "457(b)",
  traditional_401a: "401(a)",
};

/** "401(k)", "403(b)", "457(b)" or "401(a)" for an employer plan, else null. */
export const employerPlanFamily = (type: string | null | undefined): string | null =>
  FAMILY[type as AccountType] ?? null;

/** The designated Roth account type in the same plan as a traditional one; a 401(a) has none. */
export const ROTH_PLAN_COUNTERPART: Readonly<Record<string, AccountType>> = {
  traditional_401k: "roth_401k",
  traditional_403b: "roth_403b",
  traditional_457b: "roth_457b",
};

/** Whether a Roth employer match on ``target`` has a same-owner Roth account of its plan type to land in. */
export function hasRothMatchDestination(
  target: { account_type: string; owner?: string | null },
  accounts: { account_type: string; owner?: string | null; inherited_year?: number | null }[],
): boolean {
  if (ROTH_EMPLOYER_PLAN_TYPES.has(target.account_type)) return true;
  const roth = ROTH_PLAN_COUNTERPART[target.account_type];
  return (
    !!roth &&
    accounts.some(
      (a) =>
        a.account_type === roth &&
        (a.owner ?? "self") === (target.owner ?? "self") &&
        a.inherited_year == null,
    )
  );
}
