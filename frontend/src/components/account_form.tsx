import { moneyLabel } from "@/utils/format";
import { useState } from "react";
import AccountTaxFields from "./account_tax_fields";
import MoneyInput from "./money_input";
import { MAX_ANNUAL_AMOUNT } from "@/utils/amount_frequency";
import AccountDistributionFields, {
  cleanDistributionSettings,
} from "./account_distribution_fields";
import BondGlideFields, { glideError, glidePoints, glideRowsFrom } from "./bond_glide_fields";
import {
  ACCOUNT_TYPE_GROUPS,
  ACCOUNT_TYPE_LABELS,
  ACCOUNT_TYPE_OPTIONS,
  EARLY_WITHDRAWAL_PENALTY_TYPES,
  INDIVIDUAL_ONLY_ACCOUNT_TYPES,
  RETIREMENT_ACCOUNT_TYPES,
  TRADITIONAL_RETIREMENT_TYPES,
} from "@/domain/account_types";
import type {
  Account,
  AccountCreate,
  AccountType,
  CurveType,
  Milestone,
  PlanData,
  WithdrawalLock,
  AccountDistributionSettings,
  TaxRegimeAccountKind,
  TaxRegimeCountry,
} from "@/types/plan";
import {
  COUNTRY_NEUTRAL_ACCOUNT_TYPES,
  INTL_KIND_ACCOUNT_TYPE,
  accountKindsFor,
  findAccountKind,
  intlCategoryLabel,
  type UsCoverage,
} from "@/domain/intl_plan";
import { FormFooter } from "./form_footer";
import { formStyle } from "./form_styles";

/** The plan assumptions an account inherits when it has no fixed settings. */
export type PlanAssumptions = Pick<PlanData, "assumption_curves" | "assumption_defaults">;

interface AccountFormProps {
  independent?: boolean;
  planAssumptions?: PlanAssumptions | null;
  initial?: Account;
  connectedBalance?: number;
  /** The plan's milestones, offered as withdrawal-lock unlock events. */
  milestones?: Pick<Milestone, "id" | "name">[];
  /** Tax regime registry; its account kinds are offered for the plan's countries. */
  regimeCountries?: TaxRegimeCountry[] | null;
  /** Countries the plan lives in (see `planCountries`). */
  planCountryCodes?: string[];
  /** "non_us" hides US account types, except an account's saved type. */
  usCoverage?: UsCoverage;
  /** Overrides the submit label; prefilled new records pass "Add Account". */
  submitLabel?: string;
  onSubmit: (data: AccountCreate) => void;
  onCancel: () => void;
}

export const accountTypes: { value: AccountType; label: string }[] = ACCOUNT_TYPE_OPTIONS;

const STATE_TAXED_BASIS_TOOLTIP =
  "Pennsylvania, New Jersey and Massachusetts tax some retirement contributions when made. Enter the total your current state already taxed; withdrawals there recover it tax free.";

const INTL_PREFIX = "intl:";

/** A kind's key rules in one line: the registry's summary when it has one. */
function kindHelp(kind: TaxRegimeAccountKind): string {
  const rules = kind.rules?.length
    ? kind.rules.join(" ")
    : (kind.description ??
      "Contribution limits, deductibility, access age and withdrawal rules follow the country's rules for this account.");
  return `${intlCategoryLabel(kind.category)}. ${rules}`;
}

const percentInputValue = (value: number | null | undefined) =>
  value == null ? "" : String(value * 100);

/** A saved fixed rate, else the engine default; "curve" when it varies by age. */
function inheritedRate(
  plan: PlanAssumptions | null | undefined,
  type: CurveType,
): number | "curve" | null {
  const curve = plan?.assumption_curves?.find((c) => c.curve_type === type);
  if (curve?.mode === "curve") return "curve";
  return curve?.fixed_rate ?? plan?.assumption_defaults?.[type] ?? null;
}

const INHERITED_FIELDS: { type: CurveType; label: string }[] = [
  { type: "market_return", label: "Stock price growth" },
  { type: "dividend_yield", label: "Dividend yield" },
  { type: "bond_allocation", label: "Bond allocation" },
];

type AccountInvestmentSettings = NonNullable<AccountCreate["investment_settings"]>;
type BondIncomeKey = "treasury" | "municipal" | "other";
const BOND_INCOME_KEYS: BondIncomeKey[] = ["treasury", "municipal", "other"];
const BOND_INCOME_LABELS: Record<BondIncomeKey, string> = {
  treasury: "Treasury",
  municipal: "Municipal",
  other: "Other",
};
/** The server accepts a mix within 1e-6 of 1 (0.0001 percentage points). */
const MIX_TOLERANCE_PERCENT = 1e-4;

/** A 0-1 fraction as percent input text, without float noise (0.035 -> "3.5"). */
const percentText = (value: number | null | undefined) =>
  value == null ? "" : String(Number((value * 100).toFixed(6)));
const percentToFraction = (text: string) => (text.trim() === "" ? null : Number(text) / 100);

type LockKind = "any" | WithdrawalLock["unlock"];

/** The full wire shape, so an unchanged lock compares equal to the saved one. */
function buildLock(kind: LockKind, value: string): WithdrawalLock | null {
  if (kind === "any") return null;
  return {
    unlock: kind,
    age: kind === "age" ? Number(value) : null,
    milestone_id: kind === "milestone" ? value : null,
    year: kind === "year" ? Number(value) : null,
  };
}

/** The age a "From age…" lock starts at: 59½ where the 10% additional tax applies, else blank. */
const defaultUnlockAge = (type: AccountType, intl: boolean) =>
  !intl && EARLY_WITHDRAWAL_PENALTY_TYPES.has(type) ? "59.5" : "";

function lockValueError(kind: LockKind, value: string): string | null {
  if (kind === "any") return null;
  if (value.trim() === "")
    return kind === "milestone"
      ? "Choose the milestone that makes withdrawals available."
      : `Enter the ${kind} withdrawals become available.`;
  if (kind === "age" && !(Number(value) >= 0 && Number(value) <= 120))
    return "Enter an age from 0 to 120.";
  if (
    kind === "year" &&
    !(Number.isInteger(Number(value)) && Number(value) >= 1900 && Number(value) <= 2200)
  )
    return "Enter a year from 1900 to 2200.";
  return null;
}

export default function AccountForm({
  initial,
  connectedBalance,
  independent = false,
  planAssumptions,
  milestones = [],
  regimeCountries = null,
  planCountryCodes = [],
  usCoverage = "us",
  submitLabel,
  onSubmit,
  onCancel,
}: AccountFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [accountType, setAccountType] = useState<AccountType>(initial?.account_type ?? "checking");
  // A country's account kind replaces the US type's rules; the type is only its carrier.
  const [intlKind, setIntlKind] = useState<string | null>(initial?.intl_account_kind ?? null);
  // Liquid net worth override: "" keeps the default (liquid unless withdrawal-locked).
  const [liquidChoice, setLiquidChoice] = useState<"" | "include" | "exclude">(
    initial?.include_in_liquid == null ? "" : initial.include_in_liquid ? "include" : "exclude",
  );
  const kindGroups = accountKindsFor(regimeCountries, planCountryCodes);
  const selectedKind = findAccountKind(regimeCountries, intlKind);
  const isIntl = intlKind !== null;
  // All-non-US plans offer only types without US tax rules, plus the saved type.
  const typeGroups =
    usCoverage === "non_us"
      ? ACCOUNT_TYPE_GROUPS.map((group) => ({
          ...group,
          types: group.types.filter(
            (t) =>
              COUNTRY_NEUTRAL_ACCOUNT_TYPES.has(t) ||
              (t === initial?.account_type && !initial?.intl_account_kind),
          ),
        })).filter((group) => group.types.length > 0)
      : ACCOUNT_TYPE_GROUPS;
  const [balance, setBalance] = useState((connectedBalance ?? initial?.balance)?.toString() ?? "0");
  const [owner, setOwner] = useState(initial?.owner ?? "self");
  const [taxHistory, setTaxHistory] = useState<
    Pick<
      AccountCreate,
      "inherited_year" | "beneficiary_type" | "inheritance_settings" | "roth_settings"
    >
  >({
    inherited_year: initial?.inherited_year ?? null,
    beneficiary_type: initial?.beneficiary_type ?? "non_edb",
    inheritance_settings: initial?.inheritance_settings ?? null,
    roth_settings: initial?.roth_settings ?? null,
  });
  const [distribution, setDistribution] = useState<AccountDistributionSettings | null>(
    initial?.distribution_settings ?? null,
  );
  const initialLock = initial?.withdrawal_lock ?? null;
  const [lockKind, setLockKind] = useState<LockKind>(initialLock?.unlock ?? "any");
  // The Advanced group opens on load when the saved account already uses one of its settings.
  const advancedSet =
    initial?.inherited_year != null ||
    initial?.roth_settings != null ||
    initial?.distribution_settings != null ||
    initialLock != null ||
    initial?.include_in_liquid != null;
  const initialLockValue =
    initialLock == null
      ? ""
      : String(
          (initialLock.unlock === "age"
            ? initialLock.age
            : initialLock.unlock === "year"
              ? initialLock.year
              : initialLock.milestone_id) ?? "",
        );
  const [lockValue, setLockValue] = useState(initialLockValue);
  // A household account's lock may name another plan's milestone; keep it selectable.
  const foreignMilestoneId =
    initialLock?.unlock === "milestone" &&
    initialLock.milestone_id &&
    !milestones.some((milestone) => milestone.id === initialLock.milestone_id)
      ? initialLock.milestone_id
      : null;
  const [costBasis, setCostBasis] = useState(
    initial?.cost_basis != null ? initial.cost_basis.toString() : "",
  );
  const [stateTaxedBasis, setStateTaxedBasis] = useState(
    initial?.state_taxed_basis != null ? initial.state_taxed_basis.toString() : "",
  );
  const [useInvestmentSettings, setUseInvestmentSettings] = useState(
    initial?.investment_settings != null,
  );
  const [stockGrowthRate, setStockGrowthRate] = useState(
    percentInputValue(initial?.investment_settings?.stock_growth_rate),
  );
  const [dividendYield, setDividendYield] = useState(
    percentInputValue(initial?.investment_settings?.dividend_yield),
  );
  const [bondAllocation, setBondAllocation] = useState(
    percentInputValue(initial?.investment_settings?.bond_allocation),
  );
  const initialGlide = initial?.investment_settings?.bond_allocation_glide;
  const [glide, setGlide] = useState(() => glideRowsFrom(initialGlide));
  // Expense ratio plus advisory fee, charged yearly on the opening balance.
  const [annualFeeRate, setAnnualFeeRate] = useState(
    percentText(initial?.investment_settings?.annual_fee_rate),
  );
  // Flat yearly fee in today's dollars and a share of each year's gains.
  const [annualFeeAmount, setAnnualFeeAmount] = useState(
    initial?.investment_settings?.annual_fee_amount != null
      ? String(initial.investment_settings.annual_fee_amount)
      : "",
  );
  const [earningsFeeRate, setEarningsFeeRate] = useState(
    percentText(initial?.investment_settings?.fee_percent_of_earnings),
  );
  // Taxable brokerage only: dividends and interest paid to cash when false.
  const [reinvestIncome, setReinvestIncome] = useState(
    initial?.investment_settings?.reinvest_income !== false,
  );
  // Tax character of investment income (taxable accounts). Wire values are
  // 0-1 fractions; the inputs are percents.
  const initialMix = initial?.investment_settings?.bond_income_mix;
  // Open the advanced section when the saved account already uses it.
  const incomeCompositionSaved = [
    initial?.investment_settings?.qualified_dividend_ratio,
    initial?.investment_settings?.bond_income_yield,
    initialMix,
    initial?.investment_settings?.municipal_state_exempt,
  ].some((value) => value != null);
  const [qualifiedRatio, setQualifiedRatio] = useState(
    percentText(initial?.investment_settings?.qualified_dividend_ratio),
  );
  const [bondIncomeYield, setBondIncomeYield] = useState(
    percentText(initial?.investment_settings?.bond_income_yield),
  );
  const [bondMix, setBondMix] = useState<Record<BondIncomeKey, string>>({
    treasury: percentText(initialMix?.treasury),
    municipal: percentText(initialMix?.municipal),
    other: percentText(initialMix?.other),
  });
  const [municipalStateExempt, setMunicipalStateExempt] = useState(
    initial?.investment_settings?.municipal_state_exempt === true,
  );

  const inherited = INHERITED_FIELDS.map((field) => ({
    ...field,
    rate: inheritedRate(planAssumptions, field.type),
  }));
  const placeholder = (type: CurveType) => {
    const rate = inherited.find((field) => field.type === type)?.rate;
    return rate === "curve"
      ? "Plan curve"
      : rate == null
        ? "Plan setting"
        : (rate * 100).toFixed(1);
  };

  const isBrokerage = accountType === "taxable_brokerage";
  const isEducation = !isIntl && accountType === "five_twenty_nine";
  const isTraditionalRetirement = !isIntl && TRADITIONAL_RETIREMENT_TYPES.has(accountType);
  const isCash = accountType === "checking" || accountType === "savings";
  // IRAs, workplace plans and HSAs have one owner; the backend rejects a joint one.
  const individualOnly = (type: AccountType) => INDIVIDUAL_ONLY_ACCOUNT_TYPES.has(type);
  // A country's retirement kinds belong to one person; cash and taxable kinds may be joint.
  const jointAllowed = isIntl
    ? accountType === "savings" || accountType === "taxable_brokerage"
    : !individualOnly(accountType);
  // An unlock age still at the old type's default follows the new type's.
  function followDefaultUnlockAge(type: AccountType, intl: boolean) {
    if (lockKind === "age" && lockValue === defaultUnlockAge(accountType, isIntl))
      setLockValue(defaultUnlockAge(type, intl));
  }
  function changeAccountType(value: string) {
    if (value.startsWith(INTL_PREFIX)) {
      const id = value.slice(INTL_PREFIX.length);
      const kind = findAccountKind(regimeCountries, id);
      const carrier = kind ? INTL_KIND_ACCOUNT_TYPE[kind.category] : accountType;
      setIntlKind(id);
      setAccountType(carrier);
      followDefaultUnlockAge(carrier, true);
      if (owner === "joint" && !(carrier === "savings" || carrier === "taxable_brokerage"))
        setOwner("self");
      return;
    }
    const next = value as AccountType;
    setIntlKind(null);
    setAccountType(next);
    followDefaultUnlockAge(next, false);
    if (owner === "joint" && individualOnly(next)) setOwner("self");
  }
  // The projection's tax assumption for account types without their own rules.
  const accountTypeNote = isIntl
    ? selectedKind
      ? kindHelp(selectedKind)
      : "This account kind's country is no longer offered; its saved kind is kept."
    : accountType === "five_twenty_nine"
      ? "Withdrawals are tax free up to the year’s qualified education expenses; beyond them, earnings are taxed plus 10%."
      : accountType === "other"
        ? "Growth and withdrawals are treated as untaxed."
        : accountType === "traditional_457b" || accountType === "roth_457b"
          ? "Treated as a governmental 457(b): its own contribution limit and no 10% early-withdrawal tax."
          : accountType === "traditional_401a"
            ? "Employer contributions only; no employee deferrals."
            : null;

  const lockError = lockValueError(lockKind, lockValue);
  function changeLockKind(next: LockKind) {
    setLockKind(next);
    setLockValue(
      next === initialLock?.unlock
        ? initialLockValue
        : next === "age"
          ? defaultUnlockAge(accountType, isIntl)
          : "",
    );
  }
  const penaltyBeforeUnlockAge = defaultUnlockAge(accountType, isIntl) !== "";

  const balanceError =
    Number(balance) < 0
      ? "Balances cannot be negative. Model money you owe under Property and debt instead."
      : null;
  const showIncomeComposition = isBrokerage && useInvestmentSettings;
  const glideProblem =
    !isCash && useInvestmentSettings ? glideError(glide.basis, glide.rows) : null;
  const mixEntered = BOND_INCOME_KEYS.some((key) => bondMix[key].trim() !== "");
  const mixTotal = BOND_INCOME_KEYS.reduce((total, key) => total + (Number(bondMix[key]) || 0), 0);
  const mixError =
    showIncomeComposition && mixEntered && Math.abs(mixTotal - 100) > MIX_TOLERANCE_PERCENT
      ? `Treasury, municipal and other must add up to 100% (now ${Number(mixTotal.toFixed(4))}%).`
      : null;
  // Null keeps the legacy treatment: all dividends qualified, no separate bond income.
  const incomeComposition: Pick<
    AccountInvestmentSettings,
    "qualified_dividend_ratio" | "bond_income_yield" | "bond_income_mix" | "municipal_state_exempt"
  > = isBrokerage
    ? {
        qualified_dividend_ratio: percentToFraction(qualifiedRatio),
        bond_income_yield: percentToFraction(bondIncomeYield),
        bond_income_mix: mixEntered
          ? {
              treasury: percentToFraction(bondMix.treasury) ?? 0,
              municipal: percentToFraction(bondMix.municipal) ?? 0,
              other: percentToFraction(bondMix.other) ?? 0,
            }
          : null,
        municipal_state_exempt: municipalStateExempt ? true : null,
      }
    : {
        qualified_dividend_ratio: null,
        bond_income_yield: null,
        bond_income_mix: null,
        municipal_state_exempt: null,
      };
  // Newer settings join the payload only when set or already saved, so an
  // older record's unchanged settings still compare equal and stay unsent.
  const savedSettings = initial?.investment_settings ?? {};
  const optionalSettings = Object.fromEntries(
    (
      [
        ["annual_fee_amount", annualFeeAmount.trim() === "" ? null : Number(annualFeeAmount)],
        ["fee_percent_of_earnings", percentToFraction(earningsFeeRate)],
        ["reinvest_income", isBrokerage && !reinvestIncome ? false : null],
      ] as const
    ).filter(([key, value]) => value !== null || key in savedSettings),
  ) as Pick<
    AccountInvestmentSettings,
    "annual_fee_amount" | "fee_percent_of_earnings" | "reinvest_income"
  >;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (balanceError || mixError || lockError || glideProblem) return;
    const data: AccountCreate = {
      name,
      account_type: accountType,
      balance: Number(balance),
      owner: owner || "self",
      withdrawal_lock: buildLock(lockKind, lockValue),
      ...taxHistory,
      inherited_year:
        !isIntl && RETIREMENT_ACCOUNT_TYPES.has(accountType) ? taxHistory.inherited_year : null,
      inheritance_settings:
        !isIntl && RETIREMENT_ACCOUNT_TYPES.has(accountType) && taxHistory.inherited_year != null
          ? taxHistory.inheritance_settings
          : null,
      roth_settings: !isIntl && accountType.startsWith("roth") ? taxHistory.roth_settings : null,
      investment_settings:
        !isCash && useInvestmentSettings
          ? {
              stock_growth_rate:
                stockGrowthRate.trim() === "" ? null : Number(stockGrowthRate) / 100,
              dividend_yield: dividendYield.trim() === "" ? null : Number(dividendYield) / 100,
              bond_allocation: bondAllocation.trim() === "" ? null : Number(bondAllocation) / 100,
              ...incomeComposition,
              // Last, matching the server's key order for the unchanged-settings check.
              annual_fee_rate: percentToFraction(annualFeeRate),
              // Sent when set, or as [] to clear a saved path.
              ...(glide.rows.length || initialGlide != null
                ? { bond_allocation_glide: glidePoints(glide.basis, glide.rows) }
                : {}),
              ...optionalSettings,
            }
          : null,
    };
    // Sent only when set or already saved, so US accounts keep their payload.
    if (intlKind !== null || initial?.intl_account_kind) data.intl_account_kind = intlKind;
    const includeInLiquid = liquidChoice === "" ? null : liquidChoice === "include";
    if (includeInLiquid !== null || initial?.include_in_liquid != null)
      data.include_in_liquid = includeInLiquid;
    // Sent only when set or already saved, so older payloads stay unchanged.
    const cleanedDistribution = cleanDistributionSettings(
      accountType,
      owner || "self",
      RETIREMENT_ACCOUNT_TYPES.has(accountType) && taxHistory.inherited_year != null,
      distribution,
    );
    if (cleanedDistribution || initial?.distribution_settings)
      data.distribution_settings = cleanedDistribution;
    if (isBrokerage || isEducation) {
      const basis = costBasis.trim() === "" ? null : Number(costBasis);
      // Older 529 records never sent a basis; send it only when set or changed.
      if (isBrokerage || basis !== (initial?.cost_basis ?? null)) data.cost_basis = basis;
    }
    const stateBasis =
      isTraditionalRetirement && stateTaxedBasis.trim() !== "" ? Number(stateTaxedBasis) : null;
    // Older records lack the field; send it only when it was set or changed.
    if (stateBasis !== (initial?.state_taxed_basis ?? null)) data.state_taxed_basis = stateBasis;
    if (initial && accountType === initial.account_type) {
      // Optional fields absent from older records are display defaults, not
      // user edits. Never send them over a separately saved history change.
      for (const key of [
        "inherited_year",
        "beneficiary_type",
        "inheritance_settings",
        "roth_settings",
        "investment_settings",
        "withdrawal_lock",
        "distribution_settings",
      ] as const) {
        const fallback = key === "beneficiary_type" ? "non_edb" : null;
        if (JSON.stringify(data[key] ?? fallback) === JSON.stringify(initial[key] ?? fallback))
          delete data[key];
      }
    }
    onSubmit(data);
  }

  return (
    <form onSubmit={handleSubmit} style={formStyle}>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>

      <label>
        Account Type
        <select
          value={isIntl ? `${INTL_PREFIX}${intlKind}` : accountType}
          onChange={(e) => changeAccountType(e.target.value)}
          aria-describedby={accountTypeNote ? "account_type_note" : undefined}
        >
          {kindGroups.map(({ country, kinds }) => (
            <optgroup key={country.code} label={`${country.name} accounts`}>
              {kinds.map((kind) => (
                <option key={kind.id} value={`${INTL_PREFIX}${kind.id}`}>
                  {kind.label}
                </option>
              ))}
            </optgroup>
          ))}
          {isIntl && !kindGroups.some(({ kinds }) => kinds.some((k) => k.id === intlKind)) && (
            <option value={`${INTL_PREFIX}${intlKind}`}>{selectedKind?.label ?? intlKind}</option>
          )}
          {typeGroups.map((group) => (
            <optgroup
              key={group.label}
              label={
                usCoverage !== "us" &&
                group.types.some((t) => !COUNTRY_NEUTRAL_ACCOUNT_TYPES.has(t))
                  ? `${group.label} (US rules)`
                  : group.label
              }
            >
              {group.types.map((type) => (
                <option key={type} value={type}>
                  {ACCOUNT_TYPE_LABELS[type]}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {accountTypeNote && (
          <span
            id="account_type_note"
            style={{ display: "block", fontSize: 12, color: "var(--gray-600)" }}
          >
            {accountTypeNote}
          </span>
        )}
      </label>

      <p id="shared_account_scope" style={{ gridColumn: "1 / -1", margin: 0 }}>
        {independent ? (
          <strong>Account · this plan.</strong>
        ) : (
          <>
            <strong>Household account.</strong> Shared across plans; edits affect all of them.
          </>
        )}
      </p>
      <label>
        {moneyLabel("Balance ($)")}
        <MoneyInput
          required
          min="0"
          max={MAX_ANNUAL_AMOUNT}
          step="0.01"
          readOnly={connectedBalance !== undefined}
          aria-describedby="shared_account_scope"
          value={balance}
          onValueChange={setBalance}
          aria-invalid={balanceError ? true : undefined}
        />
        {balanceError && (
          <span
            role="alert"
            style={{ display: "block", fontSize: 12, color: "var(--color-danger)" }}
          >
            {balanceError}
          </span>
        )}
      </label>

      <label>
        Owner
        <select value={owner} onChange={(e) => setOwner(e.target.value)} required>
          <option value="self">Primary person</option>
          <option value="spouse">Partner</option>
          {jointAllowed && <option value="joint">Joint</option>}
          {!["self", "spouse", ...(jointAllowed ? ["joint"] : [])].includes(owner) && (
            <option value={owner}>{owner || "Unspecified"} (existing value — review owner)</option>
          )}
        </select>
      </label>

      {isBrokerage && (
        <label style={{ gridColumn: "1 / -1" }}>
          Cost basis (blank = balance)
          <MoneyInput
            min="0"
            max={MAX_ANNUAL_AMOUNT}
            step="0.01"
            value={costBasis}
            onValueChange={setCostBasis}
            aria-label="Cost basis"
          />
        </label>
      )}

      {isEducation && (
        <label style={{ gridColumn: "1 / -1" }}>
          Total contributions (optional — leave blank if the balance is all contributions)
          <MoneyInput
            min="0"
            step="0.01"
            value={costBasis}
            onValueChange={setCostBasis}
            placeholder="Leave blank if the balance is all contributions"
            aria-label="529 contributions"
          />
          <span style={{ display: "block", fontSize: 12 }}>
            The rest is earnings, taxed with a 10% additional tax if withdrawn for anything other
            than qualified education.
          </span>
        </label>
      )}

      {isTraditionalRetirement && (
        <label style={{ gridColumn: "1 / -1" }} title={STATE_TAXED_BASIS_TOOLTIP}>
          Contributions your state already taxed (optional)
          <MoneyInput
            min="0"
            step="0.01"
            value={stateTaxedBasis}
            onValueChange={setStateTaxedBasis}
            placeholder="Leave blank if none"
            aria-label="Contributions your state already taxed"
          />
        </label>
      )}

      {!isCash && (
        <fieldset
          style={{
            gridColumn: "1 / -1",
            border: "1px solid var(--gray-200)",
            borderRadius: "var(--radius-md)",
            padding: 12,
          }}
        >
          <legend>Investment assumptions (optional)</legend>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={useInvestmentSettings}
              onChange={(e) => setUseInvestmentSettings(e.target.checked)}
            />
            Use fixed settings for this account
          </label>
          {!useInvestmentSettings && inherited.some((field) => field.rate != null) && (
            <dl
              aria-label="Plan investment assumptions"
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "4px 16px",
                margin: "8px 0 0",
                fontSize: 12,
                color: "var(--gray-600)",
              }}
            >
              {inherited
                .filter((field) => field.rate != null)
                .map((field) => (
                  <div key={field.type} style={{ display: "flex", gap: 4 }}>
                    <dt>{field.label}</dt>
                    <dd
                      style={{
                        margin: 0,
                        fontVariantNumeric: "tabular-nums",
                        color: "var(--gray-900)",
                      }}
                    >
                      {field.rate === "curve"
                        ? "Curve"
                        : `${((field.rate as number) * 100).toFixed(1)}%`}
                    </dd>
                  </div>
                ))}
            </dl>
          )}
          {useInvestmentSettings && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(180px, 100%), 1fr))",
                gap: 10,
                marginTop: 10,
              }}
            >
              <label title="Fixed stock price growth; blank inherits the plan setting.">
                Stock price growth (%)
                <input
                  type="number"
                  min="-99"
                  max="100"
                  step="0.1"
                  value={stockGrowthRate}
                  onChange={(e) => setStockGrowthRate(e.target.value)}
                  placeholder={placeholder("market_return")}
                  aria-label="Stock price growth (%)"
                />
              </label>
              <label title="Fixed stock dividend yield; blank inherits the plan setting.">
                Stock dividend yield (%)
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={dividendYield}
                  onChange={(e) => setDividendYield(e.target.value)}
                  placeholder={placeholder("dividend_yield")}
                  aria-label="Stock dividend yield (%)"
                />
              </label>
              <label title="Fund expense ratio plus any advisory (AUM) fee, charged each year on the starting balance. Not tax-deductible. Blank: no fee.">
                Annual fee (%)
                <input
                  type="number"
                  min="0"
                  max="5"
                  step="0.01"
                  value={annualFeeRate}
                  onChange={(e) => setAnnualFeeRate(e.target.value)}
                  placeholder="0"
                  aria-label="Annual fee (%)"
                />
              </label>
              <label
                title={moneyLabel(
                  "A flat yearly account or advisory fee in today's dollars, rising with inflation. Not tax-deductible. Blank: none.",
                )}
              >
                {moneyLabel("Annual fee ($)")}
                <MoneyInput
                  min="0"
                  step="1"
                  value={annualFeeAmount}
                  onValueChange={setAnnualFeeAmount}
                  placeholder="0"
                  aria-label={moneyLabel("Annual fee ($)")}
                />
              </label>
              <label title="A performance fee taken as a share of each year's investment gains. No fee in a year with a loss. Not tax-deductible. Blank: none.">
                Fee on gains (%)
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={earningsFeeRate}
                  onChange={(e) => setEarningsFeeRate(e.target.value)}
                  placeholder="0"
                  aria-label="Fee on gains (%)"
                />
              </label>
              <label title="Fixed bond share; blank inherits the plan setting. The plan bond return still applies.">
                Bond allocation (%)
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={bondAllocation}
                  onChange={(e) => setBondAllocation(e.target.value)}
                  placeholder={placeholder("bond_allocation")}
                  aria-label="Bond allocation (%)"
                />
              </label>
              <p
                style={{ gridColumn: "1 / -1", margin: 0, fontSize: 12, color: "var(--gray-600)" }}
              >
                Blank inherits plan assumptions; a blank fee means none. Stock growth excludes
                bonds.
              </p>
              <BondGlideFields
                basis={glide.basis}
                rows={glide.rows}
                error={glideProblem}
                onChange={(basis, rows) => setGlide({ basis, rows })}
              />
              {isBrokerage && (
                <label
                  style={{ gridColumn: "1 / -1", display: "flex", gap: 8, alignItems: "center" }}
                  title="Unchecked: dividends and interest are paid to your cash flow each year instead of buying more shares. They are taxed either way."
                >
                  <input
                    type="checkbox"
                    checked={reinvestIncome}
                    onChange={(e) => setReinvestIncome(e.target.checked)}
                    aria-label="Reinvest dividends and interest"
                  />
                  Reinvest dividends and interest
                </label>
              )}
              {showIncomeComposition && (
                <details
                  open={incomeCompositionSaved || mixError !== null}
                  style={{ gridColumn: "1 / -1" }}
                >
                  <summary>Advanced: how dividends and bond income are taxed</summary>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(min(180px, 100%), 1fr))",
                      gap: 10,
                      marginTop: 10,
                    }}
                  >
                    <label title="Share of stock dividends taxed at capital-gains rates. The rest (REITs, money-market funds, short holding periods) is ordinary income. Blank: all qualified.">
                      Qualified dividends (%)
                      <input
                        type="number"
                        min="0"
                        max="100"
                        step="0.1"
                        value={qualifiedRatio}
                        onChange={(e) => setQualifiedRatio(e.target.value)}
                        placeholder="100"
                        aria-label="Qualified dividends (%)"
                      />
                    </label>
                    <label title="Yearly bond interest as a share of the bond holdings. It is part of the bond return, not added to it, and is taxed each year. Blank: none.">
                      Bond income yield (%)
                      <input
                        type="number"
                        min="0"
                        max="100"
                        step="0.1"
                        value={bondIncomeYield}
                        onChange={(e) => setBondIncomeYield(e.target.value)}
                        placeholder="0"
                        aria-label="Bond income yield (%)"
                      />
                    </label>
                    <fieldset
                      style={{ gridColumn: "1 / -1", border: 0, padding: 0, margin: 0 }}
                      aria-describedby={mixError ? "bond_income_mix_error" : undefined}
                    >
                      <legend style={{ fontSize: 13 }}>
                        Bond income mix (%) — blank: all other
                      </legend>
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(min(120px, 100%), 1fr))",
                          gap: 10,
                        }}
                      >
                        {BOND_INCOME_KEYS.map((key) => (
                          <label key={key}>
                            {BOND_INCOME_LABELS[key]}
                            <input
                              type="number"
                              min="0"
                              max="100"
                              step="0.1"
                              value={bondMix[key]}
                              onChange={(e) =>
                                setBondMix((mix) => ({ ...mix, [key]: e.target.value }))
                              }
                              aria-label={`${BOND_INCOME_LABELS[key]} bond income (%)`}
                              aria-invalid={mixError ? true : undefined}
                            />
                          </label>
                        ))}
                      </div>
                      {mixError && (
                        <span
                          id="bond_income_mix_error"
                          role="alert"
                          style={{ display: "block", fontSize: 12, color: "var(--color-danger)" }}
                        >
                          {mixError}
                        </span>
                      )}
                    </fieldset>
                    <label
                      style={{
                        gridColumn: "1 / -1",
                        display: "flex",
                        gap: 8,
                        alignItems: "center",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={municipalStateExempt}
                        onChange={(e) => setMunicipalStateExempt(e.target.checked)}
                      />
                      In-state municipal bonds (municipal interest is also exempt from state tax)
                    </label>
                    <p
                      style={{
                        gridColumn: "1 / -1",
                        margin: 0,
                        fontSize: 12,
                        color: "var(--gray-600)",
                      }}
                    >
                      Treasury interest: no state tax. Municipal interest: no federal tax, but
                      included in the income that sets Social Security taxation, ACA credits and
                      IRMAA. Other interest: fully taxed.
                    </p>
                  </div>
                </details>
              )}
            </div>
          )}
        </fieldset>
      )}

      {/* Rarely needed settings stay collapsed unless one of them is already set. */}
      <details
        className="form-advanced"
        style={{ gridColumn: "1 / -1" }}
        open={advancedSet || undefined}
      >
        <summary>Advanced</summary>
        <div style={{ display: "grid", gap: 12, marginTop: 10 }}>
          {!isIntl && (
            <AccountTaxFields type={accountType} value={taxHistory} onChange={setTaxHistory} />
          )}
          {!isIntl && (
            <AccountDistributionFields
              type={accountType}
              owner={owner || "self"}
              inherited={taxHistory.inherited_year != null}
              value={distribution}
              onChange={setDistribution}
            />
          )}

          <fieldset
            style={{
              gridColumn: "1 / -1",
              border: "1px solid var(--gray-200)",
              borderRadius: "var(--radius-md)",
              padding: 12,
            }}
          >
            <legend>Withdrawals available</legend>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(180px, 100%), 1fr))",
                gap: 10,
              }}
            >
              <label>
                Available
                <select
                  value={lockKind}
                  onChange={(e) => changeLockKind(e.target.value as LockKind)}
                  aria-label="Withdrawals available"
                >
                  <option value="any">Any time</option>
                  <option value="age">From age…</option>
                  <option
                    value="milestone"
                    disabled={milestones.length === 0 && foreignMilestoneId === null}
                  >
                    From milestone…
                  </option>
                  <option value="year">From year…</option>
                </select>
              </label>
              {lockKind === "age" && (
                <label>
                  {owner === "spouse" ? "Partner's age" : "Primary person's age"}
                  <input
                    type="number"
                    min="0"
                    max="120"
                    step="0.5"
                    value={lockValue}
                    onChange={(e) => setLockValue(e.target.value)}
                    aria-label="Unlock age"
                    aria-invalid={lockError ? true : undefined}
                  />
                </label>
              )}
              {lockKind === "milestone" && (
                <label>
                  Milestone
                  <select
                    value={lockValue}
                    onChange={(e) => setLockValue(e.target.value)}
                    aria-label="Unlock milestone"
                    aria-invalid={lockError ? true : undefined}
                  >
                    <option value="">Choose a milestone</option>
                    {milestones.map((milestone) => (
                      <option key={milestone.id} value={milestone.id}>
                        {milestone.name}
                      </option>
                    ))}
                    {foreignMilestoneId && (
                      <option value={foreignMilestoneId}>A milestone in another plan</option>
                    )}
                  </select>
                </label>
              )}
              {lockKind === "year" && (
                <label>
                  Year
                  <input
                    type="number"
                    min="1900"
                    max="2200"
                    step="1"
                    value={lockValue}
                    onChange={(e) => setLockValue(e.target.value)}
                    aria-label="Unlock year"
                    aria-invalid={lockError ? true : undefined}
                  />
                </label>
              )}
            </div>
            {lockKind !== "any" && lockError && (
              <span
                role="alert"
                style={{ display: "block", fontSize: 12, color: "var(--color-danger)" }}
              >
                {lockError}
              </span>
            )}
            <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--gray-600)" }}>
              {lockKind === "any" && penaltyBeforeUnlockAge
                ? "The 10% additional tax before 59½ applies without a lock; a lock also blocks conversions."
                : lockKind === "any"
                  ? "Use a later date for deferred compensation, a plan with no in-service withdrawals, a trust or a CD."
                  : "Until then the account isn't drawn, converted or transferred and doesn't count as liquid. Required minimum distributions still come out."}
            </p>
          </fieldset>

          <label style={{ gridColumn: "1 / -1" }}>
            Liquid net worth
            <select
              value={liquidChoice}
              onChange={(e) => setLiquidChoice(e.target.value as "" | "include" | "exclude")}
              aria-label="Liquid net worth"
            >
              <option value="">Default: count it unless withdrawals are locked</option>
              <option value="include">Always count it as liquid</option>
              <option value="exclude">Never count it as liquid</option>
            </select>
            <span style={{ display: "block", fontSize: 12, color: "var(--gray-600)" }}>
              Used by liquid-net-worth milestones, the FI estimate and the Monte Carlo liquid-assets
              test.
            </span>
          </label>
        </div>
      </details>

      <FormFooter
        onCancel={onCancel}
        submitLabel={submitLabel ?? `${initial ? "Update" : "Add"} Account`}
      />
    </form>
  );
}
