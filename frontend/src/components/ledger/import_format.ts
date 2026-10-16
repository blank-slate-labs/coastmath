import type { CsvDetails, CsvMapping } from "@/api/ledger_imports";

/** "2026-08-03" as "Aug 3, 2026" (calendar dates, never shifted by time zone). */
export function dayLabel(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Amount with cents, for checking signs on sample rows. */
export function exact(value: number, currency: string | null): string {
  const code = currency && /^[A-Z]{3}$/.test(currency) ? currency : "USD";
  return new Intl.NumberFormat(undefined, { style: "currency", currency: code }).format(value);
}

export function rangeLabel(start: string, end: string): string {
  return start === end ? dayLabel(start) : `${dayLabel(start)} – ${dayLabel(end)}`;
}

/** New-account kinds offered for an import target, as `financial_sources` type and subtype. */
export const ACCOUNT_KINDS = [
  { id: "credit_card", label: "Credit card", account_type: "CREDIT", subtype: "CREDIT_CARD" },
  { id: "checking", label: "Checking", account_type: "DEPOSITORY", subtype: "CHECKING" },
  { id: "savings", label: "Savings", account_type: "DEPOSITORY", subtype: "SAVINGS" },
  { id: "other", label: "Other", account_type: "OTHER", subtype: null },
] as const;
export type AccountKind = (typeof ACCOUNT_KINDS)[number]["id"];

export function kindFor(accountType: string, subtype: string | null): AccountKind {
  return (
    ACCOUNT_KINDS.find((k) => k.account_type === accountType && k.subtype === subtype)?.id ??
    (accountType === "CREDIT" ? "credit_card" : accountType === "DEPOSITORY" ? "checking" : "other")
  );
}

export const COLUMN_ROLES = [
  { id: "ignored", label: "Ignore" },
  { id: "date", label: "Date" },
  { id: "posted_date", label: "Posted date" },
  { id: "description", label: "Description" },
  { id: "merchant", label: "Merchant" },
  { id: "amount", label: "Amount" },
  { id: "debit", label: "Money out" },
  { id: "credit", label: "Money in" },
  { id: "type", label: "Debit/credit type" },
  { id: "category", label: "Category" },
  { id: "currency", label: "Currency" },
  { id: "status", label: "Status" },
] as const;
export type ColumnRole = (typeof COLUMN_ROLES)[number]["id"];

type SingleField =
  | "date_column"
  | "posted_date_column"
  | "merchant_column"
  | "amount_column"
  | "debit_column"
  | "credit_column"
  | "type_column"
  | "category_column"
  | "currency_column"
  | "status_column";
const ROLE_FIELDS: Record<Exclude<ColumnRole, "ignored" | "description">, SingleField> = {
  date: "date_column",
  posted_date: "posted_date_column",
  merchant: "merchant_column",
  amount: "amount_column",
  debit: "debit_column",
  credit: "credit_column",
  type: "type_column",
  category: "category_column",
  currency: "currency_column",
  status: "status_column",
};

export function roleOf(mapping: CsvMapping, index: number): ColumnRole {
  if (mapping.description_columns.includes(index)) return "description";
  const found = (Object.entries(ROLE_FIELDS) as [ColumnRole, SingleField][]).find(
    ([, f]) => mapping[f] === index,
  );
  return found ? found[0] : "ignored";
}

/** Give one column a role. A single-column role moves off whichever column held it. */
export function withRole(mapping: CsvMapping, index: number, role: ColumnRole): CsvMapping {
  const next: CsvMapping = {
    ...mapping,
    description_columns: mapping.description_columns.filter((c) => c !== index),
  };
  for (const field of Object.values(ROLE_FIELDS)) if (next[field] === index) next[field] = null;
  if (role === "description")
    next.description_columns = [...next.description_columns, index].sort((a, b) => a - b);
  else if (role !== "ignored") next[ROLE_FIELDS[role]] = index;
  if (role === "debit" || role === "credit") next.amount_strategy = "split";
  if (role === "amount" && next.amount_strategy === "split") next.amount_strategy = "signed";
  if (role === "type" && next.amount_strategy === "signed") next.amount_strategy = "indicator";
  return next;
}

/** "debit, withdrawal" as ["debit", "withdrawal"]. */
export function valueList(text: string): string[] {
  return text
    .split(",")
    .map((v) => v.trim().toLowerCase())
    .filter(Boolean);
}

/** A starting mapping from the preview's column roles when it could not suggest a complete one. */
export function mappingFromColumns(details: CsvDetails): CsvMapping {
  let mapping: CsvMapping = {
    delimiter: details.delimiter,
    data_start: details.data_start,
    date_column: null,
    date_format: null,
    description_columns: [],
    amount_strategy: "signed",
    amount_column: null,
    sign_convention: "inflows_positive",
    debit_column: null,
    credit_column: null,
    type_column: null,
    debit_values: [],
    credit_values: [],
    posted_date_column: null,
    merchant_column: null,
    category_column: null,
    currency_column: null,
    status_column: null,
    decimal_separator: details.decimal_separator === "," ? "," : ".",
    default_currency: null,
    header_row: details.header_row,
  };
  for (const column of details.columns) {
    const wanted = column.suggested_role === "memo" ? "description" : column.suggested_role;
    const role = COLUMN_ROLES.find((r) => r.id === wanted)?.id ?? "ignored";
    mapping = withRole(mapping, column.index, role);
  }
  return mapping;
}
