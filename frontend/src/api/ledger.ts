import { api } from "./client";

/** Provider-neutral ledger (backend `app/routers/ledger.py`). Amounts are positive when money leaves the account. */
export type CategoryRole = "spending" | "income" | "excluded" | "unclear";
export interface LedgerCategory {
  id: string;
  role: CategoryRole;
  bucket: string | null;
  kind: string | null;
  label: string;
}
export interface DateRange {
  start: string;
  end: string;
}

export interface LedgerAccount {
  id: string;
  provider: string;
  institution_name: string;
  name: string;
  mask: string | null;
  account_type: string;
  subtype: string | null;
  currency: string | null;
  status: string;
  spending_eligible: boolean;
  include_in_spending: boolean | null;
  counts_toward_spending: boolean;
  coverage: DateRange[];
  last_read_at: string | null;
  transaction_count: number;
  editable: boolean;
}
/** Omitted fields stay unchanged; `include_in_spending: null` restores the default. */
export interface LedgerAccountUpdate {
  include_in_spending?: boolean | null;
  name?: string;
  account_type?: string;
  subtype?: string | null;
}

export type CategorySource = "override" | "rule" | "llm" | "provider" | "none";
export interface LedgerTransaction {
  id: string;
  source_id: string;
  source_name: string;
  provider: string;
  date: string;
  posted_date: string | null;
  description: string;
  merchant_name: string | null;
  amount: number;
  currency: string | null;
  status: string;
  provider_category: string | null;
  category: string;
  category_source: CategorySource;
  rule_id: string | null;
  category_override: string | null;
  kind: string;
  bucket: string | null;
  excluded: boolean;
  one_time: boolean;
  recurring: boolean;
}
export interface TransactionFilters {
  source_id?: string;
  month?: string;
  category?: string;
  kind?: string;
  text?: string;
  uncategorized?: boolean;
  limit?: number;
  offset?: number;
}
/** Omitted fields stay unchanged; `category: null` restores the automatic category. */
export interface TransactionChanges {
  category?: string | null;
  excluded?: boolean;
  one_time?: boolean;
}

export type MatchField = "description" | "merchant" | "provider_category";
export type MatchType = "contains" | "equals" | "starts_with";
export type Direction = "any" | "outflow" | "inflow";
export interface LedgerRule {
  id: string;
  match_field: MatchField;
  match_type: MatchType;
  pattern: string;
  source_id: string | null;
  direction: Direction;
  category: string;
  created_at: string;
  updated_at: string;
  match_count: number;
}
export interface RuleInput {
  match_field: MatchField;
  match_type?: MatchType;
  pattern: string;
  source_id?: string | null;
  direction?: Direction;
  category: string;
}

export interface MonthReason {
  code: string;
  source_ids: string[];
}
export interface LedgerMonth {
  month: string;
  complete: boolean;
  reasons: MonthReason[];
  essential: number;
  discretionary: number;
  income: number;
  income_wages: number;
  by_category: Record<string, number>;
  income_by_category: Record<string, number>;
  excluded: Record<string, number>;
  one_time: number;
  one_time_count: number;
  uncategorized_outflow: number;
  transaction_count: number;
  pending_count: number;
}
export interface MonthSource {
  id: string;
  provider: string;
  name: string;
  coverage: DateRange[];
  settled: DateRange[];
  waiting: boolean;
}
export interface DuplicateWarning {
  source_ids: string[];
  matched: number;
  compared: number;
}
export interface LedgerMonths {
  currency: string;
  months: LedgerMonth[];
  sources: MonthSource[];
  duplicates: DuplicateWarning[];
}

const path = "/ledger";
export const ledger = {
  categories: (): Promise<LedgerCategory[]> => api.get(`${path}/categories`).then((r) => r.data),
  accounts: (): Promise<LedgerAccount[]> => api.get(`${path}/accounts`).then((r) => r.data),
  updateAccount: (id: string, body: LedgerAccountUpdate): Promise<LedgerAccount> =>
    api.patch(`${path}/accounts/${id}`, body).then((r) => r.data),
  transactions: (
    params: TransactionFilters = {},
  ): Promise<{ transactions: LedgerTransaction[]; total: number }> =>
    api.get(`${path}/transactions`, { params }).then((r) => r.data),
  updateTransaction: (
    id: string,
    body: TransactionChanges & { apply_to_similar?: boolean },
  ): Promise<{ transaction: LedgerTransaction; rule: LedgerRule | null }> =>
    api.patch(`${path}/transactions/${id}`, body).then((r) => r.data),
  bulkUpdate: (
    ids: string[],
    body: TransactionChanges,
  ): Promise<{ transactions: LedgerTransaction[] }> =>
    api.post(`${path}/transactions/bulk`, { ...body, ids }).then((r) => r.data),
  /** Every retained transaction as CSV text, with the category it counts under. */
  exportTransactions: (): Promise<string> =>
    api.get(`${path}/transactions/export`, { responseType: "text" }).then((r) => r.data),
  rules: (): Promise<LedgerRule[]> => api.get(`${path}/rules`).then((r) => r.data),
  createRule: (body: RuleInput): Promise<LedgerRule> =>
    api.post(`${path}/rules`, body).then((r) => r.data),
  updateRule: (id: string, body: Partial<RuleInput>): Promise<LedgerRule> =>
    api.patch(`${path}/rules/${id}`, body).then((r) => r.data),
  deleteRule: (id: string): Promise<void> =>
    api.delete(`${path}/rules/${id}`).then(() => undefined),
  /** Without `source_ids`, a plan's feed accounts (or every account that counts toward spending). */
  months: (params: { plan_id?: string; source_ids?: string[] } = {}): Promise<LedgerMonths> =>
    api.get(`${path}/months`, { params, paramsSerializer: { indexes: null } }).then((r) => r.data),
};
