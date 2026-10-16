import { describe, expect, it } from "vitest";
import type {
  Account,
  AccountType,
  CashFlowPriority,
  CashFlowPriorityCreate,
  Income,
} from "@/types/plan";
import {
  allocationProblem,
  neighbor,
  priorityPayload,
  ruleNumbering,
  ruleSignature,
  transferProblem,
} from "./rules";

const account = (id: string, account_type: AccountType, extra: Partial<Account> = {}): Account => ({
  id,
  user_id: "u",
  name: id,
  account_type,
  balance: 0,
  owner: "self",
  ...extra,
});

describe("transferProblem", () => {
  it("sends cash into a retirement account through an allocation rule", () => {
    expect(transferProblem(account("cash", "savings"), account("ira", "traditional_ira"))).toBe(
      "Cash or brokerage money enters a retirement, HSA or 529 account as a contribution, not a transfer. Use an allocation rule so the annual limits apply.",
    );
  });

  it("allows a sale from a taxable account into cash", () => {
    expect(
      transferProblem(account("brokerage", "taxable_brokerage"), account("cash", "checking")),
    ).toBeNull();
  });

  it("rejects a missing or repeated source", () => {
    const cash = account("cash", "checking");
    expect(transferProblem(undefined, cash)).toBe("Transfers need two different accounts.");
    expect(transferProblem(cash, cash)).toBe("Transfers need two different accounts.");
  });

  it("keeps rollovers with one owner and away from inherited accounts", () => {
    const own = account("own", "traditional_401k");
    expect(transferProblem(own, account("ira", "traditional_ira"))).toBeNull();
    expect(transferProblem(own, account("ira", "traditional_ira", { owner: "spouse" }))).toBe(
      "A rollover must stay with the same owner.",
    );
    expect(transferProblem(own, account("ira", "traditional_ira", { inherited_year: 2020 }))).toBe(
      "An inherited account cannot be rolled over.",
    );
  });
});

describe("ruleSignature", () => {
  it("ignores the rank and unset fields", () => {
    const rule: CashFlowPriorityCreate = {
      priority_rank: 1,
      priority_type: "contribution",
      target_account_id: "a",
      allocation_mode: "remaining",
    };
    expect(ruleSignature({ ...rule, priority_rank: 7, target_balance: undefined })).toBe(
      ruleSignature(rule),
    );
    expect(ruleSignature({ ...rule, target_account_id: "b" })).not.toBe(ruleSignature(rule));
  });
});

describe("rule order", () => {
  const items: CashFlowPriorityCreate[] = [
    { priority_rank: 1, priority_type: "contribution", target_account_id: "a" },
    { priority_rank: 2, priority_type: "income_percent", target_account_id: "k" },
    { priority_rank: 3, priority_type: "contribution", target_account_id: "b", withdraw_if_short: true },
    { priority_rank: 4, priority_type: "contribution", target_account_id: "c" },
  ];

  it("numbers each list on its own, withdraw-if-short rules first", () => {
    const { surplusOrder, ruleNumber, ruleName } = ruleNumbering(items);
    expect(surplusOrder).toEqual([2, 0, 3]);
    expect([0, 1, 2, 3].map(ruleNumber)).toEqual([2, 1, 1, 3]);
    expect(ruleName(1)).toBe("Payroll or transfer rule 1");
    expect(ruleName(3)).toBe("Rule 3");
  });

  it("moves a rule only within its group", () => {
    expect(neighbor(items, 0, 1)).toBe(3);
    expect(neighbor(items, 2, 1)).toBe(-1);
    expect(neighbor(items, 1, -1)).toBe(-1);
  });
});

describe("allocationProblem", () => {
  const salary = { id: "salary", name: "Salary", is_earned_income: true } as Income;
  const context = {
    accounts: [account("cash", "savings"), account("k", "traditional_401k")],
    liabilities: [],
    incomes: [salary],
    coverage: "us" as const,
  };

  it("accepts a valid draft and names the first invalid rule", () => {
    const valid: CashFlowPriorityCreate[] = [
      { priority_rank: 1, priority_type: "contribution", target_account_id: "cash" },
      {
        priority_rank: 2,
        priority_type: "income_percent",
        target_account_id: "k",
        source_income_id: "salary",
      },
    ];
    expect(allocationProblem(valid, [], context)).toBeNull();
    expect(
      allocationProblem(
        [...valid, { priority_rank: 3, priority_type: "debt_payment" }],
        [],
        context,
      ),
    ).toBe("Rule 2: choose the loan this payment pays down.");
  });

  it("keeps a saved workplace surplus rule but rejects a changed one", () => {
    const legacy = {
      id: "1",
      plan_id: "p",
      priority_rank: 1,
      priority_type: "contribution",
      target_account_id: "k",
    } as CashFlowPriority;
    const draft = priorityPayload([legacy]);
    expect(allocationProblem(draft, [legacy], context)).toBeNull();
    expect(
      allocationProblem([{ ...draft[0], max_annual_amount: 1000 }], [legacy], context),
    ).toMatch(/^Rule 1 \(k\): changes to 401\(k\) contributions must come from payroll/);
  });

  it("rejects a federal bracket fill in a plan taxed outside the US", () => {
    expect(
      allocationProblem(
        [{ priority_rank: 1, priority_type: "roth_conversion", conversion_mode: "fill_bracket" }],
        [],
        { ...context, coverage: "non_us" },
      ),
    ).toMatch(/^Payroll or transfer rule 1: a Roth conversion that fills a federal bracket/);
  });
});
