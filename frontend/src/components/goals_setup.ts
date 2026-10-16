import { priorityPayload } from "@/components/savings_priorities_panel";
import type { StorageAdapter } from "@/storage/adapter";
import { isSaveConflict } from "@/api/save_error";
import type {
  AccountCreate,
  AccountType,
  CashFlowPriority,
  CashFlowPriorityCreate,
  ExpenseCreate,
  IncomeCreate,
  MilestoneUpdate,
  PlanData,
} from "@/types/plan";

// ---------------------------------------------------------------------------
// The writes behind the setup Goals step, mirroring the iOS quick start
// (`QuickStartPayload`). Each answer becomes an ordinary plan item through the
// existing routes; nothing here computes a financial figure.
// ---------------------------------------------------------------------------

export const RETIREMENT = "Retirement";
export const PARTNER_RETIREMENT = "Partner retirement";
export const LIVING_EXPENSES = "Living expenses";

export type Owner = "self" | "spouse";
export type RetirementTiming = "age" | "independence" | "stopped";
export type LeftoverTarget = "" | "brokerage" | "cash";

/** Retirement reached when liquid net worth covers 25× a year of spending; the engine checks it. */
export const INDEPENDENCE_TRIGGER: MilestoneUpdate = {
  trigger_type: "expense_multiple",
  expense_multiple: 25,
  metric: "liquid_net_worth",
  trigger_value: null,
  trigger_date: null,
  relative_to_id: null,
  offset_years: 0,
};

const SETUP_ACCOUNTS: { id: string; name: string; type: AccountType; perPerson: boolean }[] = [
  { id: "cash", name: "Cash", type: "savings", perPerson: false },
  { id: "brokerage", name: "Brokerage", type: "taxable_brokerage", perPerson: false },
  { id: "401k", name: "401(k)", type: "traditional_401k", perPerson: true },
  { id: "ira", name: "Traditional IRA", type: "traditional_ira", perPerson: true },
  { id: "roth", name: "Roth IRA", type: "roth_ira", perPerson: true },
  { id: "hsa", name: "HSA", type: "hsa", perPerson: true },
];

export interface AccountSlot {
  key: string;
  name: string;
  type: AccountType;
  owner: "self" | "spouse" | "joint";
}

/** One balance per account type; retirement accounts once per person. Shared types are joint with a partner. */
export function accountSlots(hasPartner: boolean): AccountSlot[] {
  return SETUP_ACCOUNTS.flatMap((account) => {
    const owner = account.perPerson ? "self" : hasPartner ? "joint" : "self";
    const own: AccountSlot = {
      key: `${account.id}:${owner}`,
      name: account.name,
      type: account.type,
      owner,
    };
    if (!hasPartner || !account.perPerson) return [own];
    return [
      own,
      {
        key: `${account.id}:spouse`,
        name: `Partner's ${account.name}`,
        type: account.type,
        owner: "spouse",
      },
    ];
  });
}

export const leftoverSlot = (
  target: Exclude<LeftoverTarget, "">,
  hasPartner: boolean,
): AccountSlot => accountSlots(hasPartner).find((slot) => slot.key.startsWith(`${target}:`))!;

export const accountPayload = (slot: AccountSlot, balance: number): AccountCreate => ({
  name: slot.name,
  account_type: slot.type,
  balance,
  owner: slot.owner,
});

/** Benefits already being received: the claiming age is the current age, within 62–70. */
export function socialSecurityIncome(
  annual: number,
  owner: Owner,
  currentAge: number,
): IncomeCreate {
  return {
    name: owner === "spouse" ? "Partner Social Security" : "Social Security",
    annual_amount: annual,
    owner,
    is_active: true,
    is_social_security: true,
    claiming_age: Math.min(70, Math.max(62, currentAge)),
    is_earned_income: false,
    is_self_employed: false,
    tax_category: "social_security",
    growth_cap_inflation_linked: false,
  };
}

export function pensionIncome(annual: number, owner: Owner): IncomeCreate {
  return {
    name: owner === "spouse" ? "Partner pension" : "Pension",
    annual_amount: annual,
    owner,
    is_active: true,
    is_social_security: false,
    is_earned_income: false,
    is_self_employed: false,
    tax_category: "qualified_pension",
    growth_cap_inflation_linked: false,
  };
}

/** Today's spending; it ends where separate retirement spending starts. */
export function livingExpenses(monthly: number, endMilestoneId: string | null): ExpenseCreate {
  return {
    name: LIVING_EXPENSES,
    annual_amount: monthly * 12,
    amount_frequency: "monthly",
    category: "essential",
    inflation_linked: true,
    is_payroll_deduction: false,
    recurrence_growth_rate: 0,
    growth_cap_inflation_linked: false,
    end_milestone_id: endMilestoneId,
  };
}

/**
 * Partner retirement as Add milestone saves it: an age milestone on the plan
 * owner's age, shifted by the birth-year gap so it fires the year the partner
 * reaches `partnerAge`.
 */
export function partnerRetirement(
  partnerAge: number,
  birthYear: number,
  spouseBirthYear: number,
): MilestoneUpdate {
  return {
    name: PARTNER_RETIREMENT,
    trigger_type: "age",
    trigger_value: partnerAge + (spouseBirthYear - birthYear),
    trigger_date: null,
    metric: null,
    expense_multiple: null,
    relative_to_id: null,
    offset_years: 0,
  };
}

/** The saved rules plus one sending leftover income to `targetId`; null when a rule already does. */
export function withSurplusRule(
  priorities: CashFlowPriority[],
  targetId: string,
): CashFlowPriorityCreate[] | null {
  const isSurplus = (rule: CashFlowPriority) =>
    !rule.priority_type || rule.priority_type === "contribution";
  if (priorities.some((rule) => isSurplus(rule) && rule.target_account_id === targetId))
    return null;
  const items = priorityPayload(priorities);
  return [
    ...items,
    {
      priority_rank: items.length + 1,
      priority_type: "contribution",
      target_account_id: targetId,
      allocation_mode: "remaining",
      allocation_value: null,
    },
  ];
}

// ---------------------------------------------------------------------------
// Running the writes
// ---------------------------------------------------------------------------

export type SetupAdapter = Pick<
  StorageAdapter,
  | "submitPlanIntake"
  | "createMilestone"
  | "updateMilestone"
  | "createIncome"
  | "updateIncome"
  | "createExpense"
  | "updateExpense"
  | "createAccount"
  | "updateAccount"
  | "listAccounts"
  | "fetchPlan"
  | "updatePriorities"
>;

export interface SetupContext {
  adapter: SetupAdapter;
  plan: PlanData;
  /** The Retirement milestone, once one exists. */
  retirementId: string | null;
  /** Accounts created or matched by this setup, by slot key. */
  accountIds: Record<string, string>;
}

export interface SetupStep {
  key: string;
  /** What the person entered, named for a failure list. */
  label: string;
  /** The request this step would send; an unchanged step that already saved is not sent again. */
  signature: string;
  /** Later steps depend on it, so a failure stops the run. */
  blocking?: boolean;
  /** Creates the item, or updates `savedId` when an earlier attempt created it. Resolves to its ID. */
  run: (ctx: SetupContext, savedId: string | undefined) => Promise<string | undefined>;
  /** Puts a skipped step's saved ID back into the context. */
  restore?: (ctx: SetupContext, id: string) => void;
}

export interface SetupFailure {
  key: string;
  label: string;
  message: string;
}

/** The allocation changed since it was read. It needs review, never a silent retry. */
export class AllocationConflict extends Error {}

export type SavedSteps = Map<string, { id?: string; signature: string }>;

export interface SetupOutcome {
  failures: SetupFailure[];
  conflict: boolean;
  /** Whether anything was written, and whether that included accounts. */
  wrote: boolean;
  wroteAccounts: boolean;
}

const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : "Not saved.";

/**
 * Sends each step in order, skipping steps an earlier attempt already saved
 * unchanged. A failed step is reported and the rest continue, unless it blocks.
 */
export async function runSetupSteps(
  steps: SetupStep[],
  saved: SavedSteps,
  ctx: SetupContext,
): Promise<SetupOutcome> {
  const outcome: SetupOutcome = {
    failures: [],
    conflict: false,
    wrote: false,
    wroteAccounts: false,
  };
  for (const step of steps) {
    const previous = saved.get(step.key);
    if (previous && previous.signature === step.signature) {
      if (previous.id) step.restore?.(ctx, previous.id);
      continue;
    }
    try {
      const id = (await step.run(ctx, previous?.id)) ?? previous?.id;
      saved.set(step.key, { id, signature: step.signature });
      if (id) step.restore?.(ctx, id);
      outcome.wrote = true;
      if (step.key.startsWith("account:") || step.key === "leftover") outcome.wroteAccounts = true;
    } catch (error) {
      if (error instanceof AllocationConflict) {
        outcome.conflict = true;
        continue;
      }
      outcome.failures.push({ key: step.key, label: step.label, message: errorText(error) });
      if (step.blocking) break;
    }
  }
  return outcome;
}

// ---------------------------------------------------------------------------
// From the Goals form to steps
// ---------------------------------------------------------------------------

export const GOAL_FIELDS = [
  "retirement_spending",
  "travel_budget",
  "travel_until_age",
  "charitable_giving",
  "legacy_target",
] as const;
export type GoalField = (typeof GOAL_FIELDS)[number];

export interface GoalsDraft {
  timing: RetirementTiming;
  retirementAge: string;
  /** When already stopped: benefits received now. */
  socialSecurityMonthly: string;
  pension: string;
  partnerRetirementAge: string;
  partnerStopped: boolean;
  partnerSocialSecurityMonthly: string;
  partnerPension: string;
  monthlySpending: string;
  goals: Record<GoalField, string>;
  /** Opening balances by account slot key. */
  balances: Record<string, string>;
  leftover: LeftoverTarget;
}

const filled = (text: string) => text.trim() !== "";
const amount = (text: string) => Number(text.trim());

/** The partner's birth year, when the plan has a partner to plan for. */
export const partnerBirthYear = (plan: PlanData): number | null => plan.spouse?.birth_year ?? null;

/** A message for the first answer the service would refuse or the form cannot use, or null. */
export function validateGoals(
  plan: PlanData,
  draft: GoalsDraft,
  currentYear: number,
): string | null {
  const money = [
    draft.socialSecurityMonthly,
    draft.pension,
    draft.partnerSocialSecurityMonthly,
    draft.partnerPension,
    draft.monthlySpending,
    ...Object.values(draft.balances),
  ];
  if (money.some((text) => filled(text) && !(Number.isFinite(amount(text)) && amount(text) >= 0)))
    return "Enter amounts of $0 or more.";
  const goalAmounts = GOAL_FIELDS.filter((field) => field !== "travel_until_age").map(
    (field) => draft.goals[field],
  );
  if (
    goalAmounts.some((text) => filled(text) && !(Number.isFinite(amount(text)) && amount(text) > 0))
  )
    return "Enter goal amounts above $0, or leave them blank.";
  const travelUntil = draft.goals.travel_until_age;
  if (
    filled(travelUntil) &&
    !(
      Number.isInteger(amount(travelUntil)) &&
      amount(travelUntil) >= 18 &&
      amount(travelUntil) <= 120
    )
  )
    return "Enter a travel end age from 18 to 120.";
  const ageError = (text: string, birthYear: number, who: "your" | "your partner's") => {
    const age = amount(text);
    if (!Number.isInteger(age) || age < 18 || age > 120)
      return "Enter a retirement age from 18 to 120.";
    return age > currentYear - birthYear
      ? null
      : `Choose an age after ${who} current age, or mark that ${who === "your" ? "you've" : "they've"} already stopped working.`;
  };
  if (draft.timing === "age" && filled(draft.retirementAge)) {
    const error = ageError(draft.retirementAge, plan.birth_year, "your");
    if (error) return error;
  }
  const spouseBirth = partnerBirthYear(plan);
  if (spouseBirth != null && !draft.partnerStopped && filled(draft.partnerRetirementAge)) {
    const error = ageError(draft.partnerRetirementAge, spouseBirth, "your partner's");
    if (error) return error;
  }
  return null;
}

export function buildSetupSteps(
  plan: PlanData,
  draft: GoalsDraft,
  currentYear: number,
): SetupStep[] {
  const steps: SetupStep[] = [];
  const currentAge = currentYear - plan.birth_year;
  const spouseBirth = partnerBirthYear(plan);
  const setRetirement = (ctx: SetupContext, id: string) => {
    ctx.retirementId = id;
  };

  // Retirement and the goals: one step, since the goals start at Retirement.
  const answers: Record<string, number> = {};
  for (const field of GOAL_FIELDS)
    if (filled(draft.goals[field])) answers[field] = amount(draft.goals[field]);
  if (draft.timing === "stopped") answers.retirement_age = currentAge;
  else if (draft.timing === "age" && filled(draft.retirementAge))
    answers.retirement_age = amount(draft.retirementAge);
  if (draft.timing === "independence" || Object.keys(answers).length > 0) {
    steps.push({
      key: "goals",
      label: "Goals",
      blocking: true,
      restore: setRetirement,
      signature: JSON.stringify({ timing: draft.timing, answers }),
      run: async (ctx) => {
        if (draft.timing === "independence") {
          const milestone = ctx.retirementId
            ? await ctx.adapter.updateMilestone(plan.id, ctx.retirementId, INDEPENDENCE_TRIGGER)
            : await ctx.adapter.createMilestone(plan.id, {
                name: RETIREMENT,
                ...INDEPENDENCE_TRIGGER,
                trigger_type: "expense_multiple",
              });
          ctx.retirementId = milestone.id;
        }
        if (Object.keys(answers).length === 0) return ctx.retirementId ?? undefined;
        const updated = await ctx.adapter.submitPlanIntake(plan.id, answers);
        return (
          updated.milestones.find((milestone) => milestone.name === RETIREMENT)?.id ??
          ctx.retirementId ??
          undefined
        );
      },
    });
  }

  if (spouseBirth != null && (draft.partnerStopped || filled(draft.partnerRetirementAge))) {
    const partnerAge = draft.partnerStopped
      ? currentYear - spouseBirth
      : amount(draft.partnerRetirementAge);
    const existing = plan.milestones.find((milestone) => milestone.name === PARTNER_RETIREMENT)?.id;
    const payload = partnerRetirement(partnerAge, plan.birth_year, spouseBirth);
    steps.push({
      key: "partner_retirement",
      label: "Partner retirement",
      blocking: true,
      signature: String(partnerAge),
      run: async (ctx, savedId) => {
        const id = savedId ?? existing;
        const milestone = id
          ? await ctx.adapter.updateMilestone(plan.id, id, payload)
          : await ctx.adapter.createMilestone(plan.id, {
              ...payload,
              name: PARTNER_RETIREMENT,
              trigger_type: "age",
            });
        return milestone.id;
      },
    });
  }

  const income = (key: string, label: string, data: IncomeCreate): SetupStep => ({
    key,
    label,
    signature: String(data.annual_amount),
    run: async (ctx, savedId) =>
      (savedId
        ? await ctx.adapter.updateIncome(plan.id, savedId, data)
        : await ctx.adapter.createIncome(plan.id, data)
      ).id,
  });
  const retiredIncomes = (owner: Owner, monthly: string, pension: string, age: number) => {
    const prefix = owner === "spouse" ? "Partner " : "";
    // Each income reopens in the unit its question asked for.
    if (filled(monthly) && amount(monthly) > 0) {
      steps.push(
        income(`income:social_security:${owner}`, `${prefix}Social Security`, {
          ...socialSecurityIncome(amount(monthly) * 12, owner, age),
          amount_frequency: "monthly",
        }),
      );
    }
    if (filled(pension) && amount(pension) > 0) {
      steps.push(
        income(`income:pension:${owner}`, owner === "spouse" ? "Partner pension" : "Pension", {
          ...pensionIncome(amount(pension), owner),
          amount_frequency: "annual",
        }),
      );
    }
  };
  if (draft.timing === "stopped")
    retiredIncomes("self", draft.socialSecurityMonthly, draft.pension, currentAge);
  if (spouseBirth != null && draft.partnerStopped) {
    retiredIncomes(
      "spouse",
      draft.partnerSocialSecurityMonthly,
      draft.partnerPension,
      currentYear - spouseBirth,
    );
  }

  if (filled(draft.monthlySpending) && amount(draft.monthlySpending) > 0) {
    const monthly = amount(draft.monthlySpending);
    const endsAtRetirement = filled(draft.goals.retirement_spending);
    steps.push({
      key: "living_expenses",
      label: LIVING_EXPENSES,
      signature: JSON.stringify({ monthly, endsAtRetirement }),
      run: async (ctx, savedId) => {
        const data = livingExpenses(monthly, endsAtRetirement ? ctx.retirementId : null);
        return (
          savedId
            ? await ctx.adapter.updateExpense(plan.id, savedId, {
                annual_amount: data.annual_amount,
                end_milestone_id: data.end_milestone_id,
              })
            : await ctx.adapter.createExpense(plan.id, data)
        ).id;
      },
    });
  }

  const hasPartner = plan.spouse != null;
  const withBalance = new Set<string>();
  for (const slot of accountSlots(hasPartner)) {
    const text = draft.balances[slot.key] ?? "";
    if (!filled(text)) continue;
    withBalance.add(slot.key);
    const balance = amount(text);
    steps.push({
      key: `account:${slot.key}`,
      label: slot.name,
      signature: String(balance),
      restore: (ctx, id) => {
        ctx.accountIds[slot.key] = id;
      },
      run: async (ctx, savedId) =>
        (savedId
          ? await ctx.adapter.updateAccount(savedId, { balance }, plan.id)
          : await ctx.adapter.createAccount(accountPayload(slot, balance), plan.id)
        ).id,
    });
  }

  if (draft.leftover) {
    const slot = leftoverSlot(draft.leftover, hasPartner);
    steps.push({
      key: "leftover",
      label: "Leftover income",
      signature: slot.key,
      run: async (ctx) => {
        let targetId = ctx.accountIds[slot.key];
        if (!targetId) {
          // Its balance did not save this time; a blank stand-in could duplicate it.
          if (withBalance.has(slot.key)) throw new Error(`Save the ${slot.name} balance first.`);
          const accounts = await ctx.adapter.listAccounts(plan.id);
          const match = accounts.find(
            (account) =>
              account.account_type === slot.type && (account.owner ?? "self") === slot.owner,
          );
          // A blank account is still a destination for the rule.
          targetId =
            match?.id ?? (await ctx.adapter.createAccount(accountPayload(slot, 0), plan.id)).id;
          ctx.accountIds[slot.key] = targetId;
        }
        // The latest rules and revision: the rule is added to them, never written over them.
        const latest = await ctx.adapter.fetchPlan(plan.id);
        const items = withSurplusRule(latest.priorities ?? [], targetId);
        if (!items) return targetId;
        try {
          await ctx.adapter.updatePriorities(plan.id, items, latest.priorities_revision ?? 0);
        } catch (error) {
          if (isSaveConflict(error)) throw new AllocationConflict();
          throw error;
        }
        return targetId;
      },
    });
  }
  return steps;
}

/** Whether a salary still needs entering after setup: someone working and no earned income yet. */
export const needsSalary = (plan: PlanData, draft: GoalsDraft): boolean =>
  draft.timing !== "stopped" &&
  !(plan.income_streams ?? []).some(
    (stream) => stream.is_earned_income && !stream.is_social_security,
  );
