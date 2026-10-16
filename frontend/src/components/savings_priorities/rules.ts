import { fullCurrency } from "@/utils/format";
import type {
  Account,
  CashFlowPriority,
  CashFlowPriorityCreate,
  Income,
  Liability,
} from "@/types/plan";
import {
  EMPLOYER_ONLY_PLAN_TYPES,
  EMPLOYER_PLAN_TYPES,
  ELECTIVE_DEFERRAL_TYPES,
  PAYROLL_TARGET_TYPES,
  ROTH_TYPES,
  TRADITIONAL_RETIREMENT_TYPES,
  employerPlanFamily,
  hasRothMatchDestination,
} from "@/domain/account_types";
import type { UsCoverage } from "@/domain/intl_plan";

export function priorityPayload(items: CashFlowPriority[]): CashFlowPriorityCreate[] {
  return items.map(({ id: _id, plan_id: _planId, ...fields }, i) => ({
    ...fields,
    priority_rank: i + 1,
  }));
}
/** Saved rules in rank order, as the editor lists them. */
export const rankedPayload = (priorities: CashFlowPriority[]) =>
  priorityPayload([...priorities].sort((a, b) => a.priority_rank - b.priority_rank));
export const isDebt = (p: CashFlowPriorityCreate) => p.priority_type === "debt_payment";
/** Rules funded from the year's leftover surplus: account contributions and loan payments. */
export const isSurplus = (p: CashFlowPriorityCreate) =>
  !p.priority_type || p.priority_type === "contribution" || isDebt(p);
export const workplaceTypes = [...EMPLOYER_PLAN_TYPES];
/** A collapsed surplus rule's amount: "$7,500 a year", "20% of surplus" or "remaining surplus". */
export function allocationSummary(p: CashFlowPriorityCreate) {
  if (p.allocation_mode === "amount") return `${fullCurrency(p.allocation_value ?? 0)} a year`;
  if (p.allocation_mode === "percentage") return `${p.allocation_value ?? 0}% of surplus`;
  return "remaining surplus";
}
export const isPayroll = (p: CashFlowPriorityCreate) =>
  ["income_percent", "pre_tax_contribution", "after_tax_401k"].includes(p.priority_type ?? "");
export const isAfterTax = (p: CashFlowPriorityCreate) => p.priority_type === "after_tax_401k";
/** Rules that can withdraw when the surplus is short; conversions, harvests and transfers move money from their own source. */
export const canWithdrawIfShort = (p: CashFlowPriorityCreate) => isSurplus(p) || isPayroll(p);
/** Rules swap places only within their group; withdraw-if-short surplus rules stay above the others. */
export const moveGroup = (p: CashFlowPriorityCreate) =>
  isSurplus(p) ? (p.withdraw_if_short ? "withdraws" : "surplus") : "other";
/** Rules that fill a US federal bracket; the projection rejects them when no year is a US year. */
export const fillsUsBracket = (p: CashFlowPriorityCreate) =>
  (p.priority_type === "roth_conversion" && p.conversion_mode === "fill_bracket") ||
  (p.priority_type === "gain_harvest" && !p.use_plan_tax_target);
export const usBracketRuleName = (p: CashFlowPriorityCreate) =>
  p.priority_type === "gain_harvest"
    ? "gain harvesting to a federal capital gains bracket"
    : "a Roth conversion that fills a federal bracket";
/** Rules whose contributions a lower plan limit can cap. */
export const takesCustomLimit = (p: CashFlowPriorityCreate) =>
  (isSurplus(p) && !isDebt(p)) ||
  p.priority_type === "income_percent" ||
  p.priority_type === "pre_tax_contribution";
/** Short description of a rule's employer contribution for the review list. */
export function employerSummary(p: CashFlowPriorityCreate) {
  const match = p.employer_match;
  if (!match) return `employer ${p.employer_match_rate ?? 0}%`;
  const tiers = match.tiers
    .map((t) => `${t.match_percent}% of ${t.up_to_percent_of_pay}%`)
    .join(" + ");
  return `employer match ${tiers || "none"}${match.nonelective_percent ? ` + ${match.nonelective_percent}% of pay` : ""}${match.cap_amount != null ? ` up to ${fullCurrency(match.cap_amount)}` : ""}${match.roth ? " (Roth)" : ""}`;
}
/** Account types a payroll rule may fund. Mega backdoor money converts in-plan to a Roth 401(k). */
export const payrollTargets = (p: CashFlowPriorityCreate) =>
  isAfterTax(p) ? ["roth_401k"] : [...PAYROLL_TARGET_TYPES];
export const CASH_TARGETS = ["checking", "savings", "taxable_brokerage"];
export const SALE_SOURCES = ["checking", "savings", "taxable_brokerage", "cryptocurrency"];
/**
 * Mirrors the server's transfer matrix so a bad pairing is explained before saving; the
 * server stays authoritative. Sales and distributions land in cash or brokerage, and a
 * traditional retirement account can roll over to another one of the same owner.
 */
export function transferProblem(source?: Account, target?: Account): string | null {
  if (!source || !target || source.id === target.id)
    return "Transfers need two different accounts.";
  const from = source.account_type;
  const to = target.account_type;
  const retirementSource = TRADITIONAL_RETIREMENT_TYPES.has(from) || ROTH_TYPES.has(from);
  if (CASH_TARGETS.includes(to) && (SALE_SOURCES.includes(from) || retirementSource)) return null;
  if (TRADITIONAL_RETIREMENT_TYPES.has(from) && TRADITIONAL_RETIREMENT_TYPES.has(to)) {
    if (source.inherited_year != null || target.inherited_year != null)
      return "An inherited account cannot be rolled over.";
    if (source.owner !== target.owner) return "A rollover must stay with the same owner.";
    return null;
  }
  if (TRADITIONAL_RETIREMENT_TYPES.has(from) && ROTH_TYPES.has(to))
    return "Use a Roth conversion to move money from a traditional to a Roth account.";
  if (ROTH_TYPES.has(from))
    return "A Roth account can distribute to cash or brokerage only; Roth rollovers are not modeled.";
  if (
    ROTH_TYPES.has(to) ||
    TRADITIONAL_RETIREMENT_TYPES.has(to) ||
    to === "hsa" ||
    to === "five_twenty_nine"
  )
    return "Cash or brokerage money enters a retirement, HSA or 529 account as a contribution, not a transfer. Use an allocation rule so the annual limits apply.";
  return "Transfers move checking, savings, brokerage or retirement money into cash or brokerage, or roll one traditional account into another.";
}
export const ruleSignature = ({ priority_rank: _rank, ...fields }: CashFlowPriorityCreate) =>
  JSON.stringify(
    Object.entries(fields)
      .filter(([, value]) => value !== undefined)
      .sort(([a], [b]) => a.localeCompare(b)),
  );

/** Where each rule is listed and the number it shows there. */
export function ruleNumbering(items: CashFlowPriorityCreate[]) {
  // Withdraw-if-short rules are listed first, where they run; each keeps its own rank.
  const surplusOrder = [...items.keys()]
    .filter((i) => isSurplus(items[i]))
    .sort((a, b) => Number(!!items[b].withdraw_if_short) - Number(!!items[a].withdraw_if_short) || a - b);
  // Shown numbers count within each list (after spending; payroll and transfers), so a rule in one
  // list never leaves a gap in the other. Element ids keep the saved rank that links point at.
  const otherOrder = [...items.keys()].filter((i) => !isSurplus(items[i]));
  const ruleNumber = (i: number) =>
    (isSurplus(items[i]) ? surplusOrder.indexOf(i) : otherOrder.indexOf(i)) + 1;
  const ruleName = (i: number) =>
    isSurplus(items[i]) ? `Rule ${ruleNumber(i)}` : `Payroll or transfer rule ${ruleNumber(i)}`;
  return { surplusOrder, ruleNumber, ruleName };
}

/** The nearest rule in the same move group, or -1 at the group's edge. */
export function neighbor(items: CashFlowPriorityCreate[], i: number, direction: number) {
  for (let j = i + direction; j >= 0 && j < items.length; j += direction) {
    if (moveGroup(items[j]) === moveGroup(items[i])) return j;
  }
  return -1;
}

/** Earned income that can fund a payroll rule: the destination owner's, wages only for mega backdoor. */
export function payrollIncomes(p: CashFlowPriorityCreate, accounts: Account[], incomes: Income[]) {
  const target = accounts.find((a) => a.id === p.target_account_id);
  return incomes.filter(
    (inc) =>
      inc.is_earned_income &&
      !inc.is_social_security &&
      !(isAfterTax(p) && inc.is_self_employed) &&
      (!target || (inc.owner ?? "self") === (target.owner ?? "self")),
  );
}

/** The owner's largest active earned income, which funds a "Max 401(k)" (403(b), 457(b)) rule. */
export function maxFundingIncome(account: Account, incomes: Income[]) {
  return incomes
    .filter(
      (inc) =>
        inc.is_active !== false &&
        inc.is_earned_income &&
        !inc.is_social_security &&
        (inc.owner ?? "self") === (account.owner ?? "self"),
    )
    .sort((a, b) => b.annual_amount - a.annual_amount)[0];
}

/** Workplace plans that can take a "Max" rule: funded by earned income and not maxed already. */
export function maxableAccounts(
  accounts: Account[],
  items: CashFlowPriorityCreate[],
  incomes: Income[],
) {
  // No annual maximum: the engine fills the remaining legal limit, catch-up included.
  return accounts.filter(
    (a) =>
      ELECTIVE_DEFERRAL_TYPES.has(a.account_type) &&
      maxFundingIncome(a, incomes) &&
      !items.some(
        (p) =>
          p.priority_type === "pre_tax_contribution" &&
          p.target_account_id === a.id &&
          p.max_annual_amount == null,
      ),
  );
}

export interface RuleContext {
  accounts: Account[];
  liabilities: Liability[];
  incomes: Income[];
  coverage: UsCoverage;
}

/** Why the first invalid rule in a draft cannot be saved, or null when the draft can be saved. */
export function allocationProblem(
  items: CashFlowPriorityCreate[],
  baseline: CashFlowPriority[],
  { accounts, liabilities, incomes, coverage }: RuleContext,
): string | null {
  const { ruleName } = ruleNumbering(items);
  const preserved = priorityPayload(baseline).map(ruleSignature);
  for (const [i, p] of items.entries()) {
    const source = accounts.find((a) => a.id === p.source_account_id);
    const target = accounts.find((a) => a.id === p.target_account_id);
    if (isDebt(p)) {
      if (!liabilities.some((l) => l.id === p.target_liability_id))
        return `${ruleName(i)}: choose the loan this payment pays down.`;
      continue;
    }
    if (coverage === "non_us" && fillsUsBracket(p))
      return `${ruleName(i)}: ${usBracketRuleName(p)} can't apply, because this plan is taxed outside the US in every year. Remove the rule or add a US residency period.`;
    if (p.priority_type !== "gain_harvest" && !target)
      return "Choose a destination for every allocation.";
    if (isSurplus(p) && target && workplaceTypes.includes(target.account_type)) {
      const match = preserved.indexOf(ruleSignature(p));
      const family = employerPlanFamily(target.account_type);
      if (match < 0)
        return `${ruleName(i)} (${target.name}): changes to ${family} contributions must come from payroll. Use “Use payroll for this ${family}” and choose the income that funds it.`;
      preserved.splice(match, 1);
    }
    if (isPayroll(p)) {
      const income = incomes.find((inc) => inc.id === p.source_income_id);
      if (
        isAfterTax(p) &&
        (!target ||
          target.account_type !== "roth_401k" ||
          !income?.is_earned_income ||
          income.is_social_security ||
          income.is_self_employed ||
          (income.owner ?? "self") !== (target.owner ?? "self"))
      )
        return `${ruleName(i)}: choose a Roth 401(k) and W-2 wages belonging to the same person.`;
      if (
        !target ||
        !PAYROLL_TARGET_TYPES.has(target.account_type) ||
        !income?.is_earned_income ||
        income.is_social_security ||
        (income.owner ?? "self") !== (target.owner ?? "self")
      )
        return `${ruleName(i)}: choose a workplace plan or HSA destination and earned income belonging to the same person.`;
      if (
        EMPLOYER_ONLY_PLAN_TYPES.has(target.account_type) &&
        (p.priority_type === "pre_tax_contribution" || (p.employee_rate ?? 0) > 0)
      )
        return `${ruleName(i)} (${target.name}): a 401(a) takes employer contributions only. Set an employer rate and no employee rate.`;
      if (p.employer_match?.roth && !hasRothMatchDestination(target, accounts)) {
        const family = employerPlanFamily(target.account_type) ?? "workplace plan";
        return `${ruleName(i)} (${target.name}): add a Roth ${family} for the same person to receive Roth employer contributions, or clear the Roth option.`;
      }
    }
    if (p.priority_type === "transfer") {
      const problem = transferProblem(source, target);
      if (problem) return problem;
    }
    if (
      p.priority_type === "roth_conversion" &&
      (!source ||
        !target ||
        !TRADITIONAL_RETIREMENT_TYPES.has(source.account_type) ||
        !ROTH_TYPES.has(target.account_type) ||
        source.owner !== target.owner)
    )
      return "Roth conversions need a traditional source and Roth destination with the same owner.";
  }
  return null;
}
