import type {
  LedgerAccount,
  LedgerCategory,
  LedgerMonth,
  LedgerRule,
  LedgerTransaction,
} from "@/api/ledger";

export const CATEGORIES: LedgerCategory[] = [
  { id: "groceries", role: "spending", bucket: "essential", kind: null, label: "Groceries" },
  { id: "dining", role: "spending", bucket: "discretionary", kind: null, label: "Dining" },
  { id: "uncategorized", role: "unclear", bucket: null, kind: null, label: "Uncategorized" },
];

export function account(overrides: Partial<LedgerAccount> = {}): LedgerAccount {
  return {
    id: "a1",
    provider: "file",
    institution_name: "Synthetic bank",
    name: "Synthetic card",
    mask: "0001",
    account_type: "CREDIT",
    subtype: "CREDIT_CARD",
    currency: "USD",
    status: "ACTIVE",
    spending_eligible: true,
    include_in_spending: null,
    counts_toward_spending: true,
    coverage: [],
    last_read_at: null,
    transaction_count: 3,
    editable: true,
    ...overrides,
  };
}

export function month(overrides: Partial<LedgerMonth> = {}): LedgerMonth {
  return {
    month: "2026-08",
    complete: true,
    reasons: [],
    essential: 2000,
    discretionary: 500,
    income: 4000,
    income_wages: 4000,
    by_category: {},
    income_by_category: {},
    excluded: {},
    one_time: 0,
    one_time_count: 0,
    uncategorized_outflow: 0,
    transaction_count: 10,
    pending_count: 0,
    ...overrides,
  };
}

export function txn(overrides: Partial<LedgerTransaction> = {}): LedgerTransaction {
  return {
    id: "t1",
    source_id: "a1",
    source_name: "Synthetic card",
    provider: "file",
    date: "2026-08-10",
    posted_date: null,
    description: "SYNTHETIC GROCER",
    merchant_name: null,
    amount: 80,
    currency: "USD",
    status: "POSTED",
    provider_category: null,
    category: "groceries",
    category_source: "provider",
    rule_id: null,
    category_override: null,
    kind: "spending",
    bucket: "essential",
    excluded: false,
    one_time: false,
    recurring: false,
    ...overrides,
  };
}

export function rule(overrides: Partial<LedgerRule> = {}): LedgerRule {
  return {
    id: "r1",
    match_field: "merchant",
    match_type: "equals",
    pattern: "synthetic grocer",
    source_id: null,
    direction: "any",
    category: "groceries",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    match_count: 4,
    ...overrides,
  };
}
