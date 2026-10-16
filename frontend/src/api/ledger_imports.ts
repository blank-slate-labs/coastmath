import { api } from "./client";
import type { DateRange, LedgerAccount } from "./ledger";

/** File imports into the ledger (backend `app/routers/ledger_imports.py`). Amounts are positive when money leaves the account. */
export type AmountStrategy = "signed" | "split" | "indicator";
export type SignConvention = "inflows_positive" | "inflows_negative";

/** Mirrors `CsvMapping` in `app/ledger/importers/csv_parser.py`. Column indexes are 0-based. */
export interface CsvMapping {
  delimiter: string;
  data_start: number;
  date_column: number | null;
  date_format: string | null;
  description_columns: number[];
  amount_strategy: AmountStrategy;
  amount_column: number | null;
  sign_convention: SignConvention;
  debit_column: number | null;
  credit_column: number | null;
  type_column: number | null;
  debit_values: string[];
  credit_values: string[];
  posted_date_column: number | null;
  merchant_column: number | null;
  category_column: number | null;
  currency_column: number | null;
  status_column: number | null;
  decimal_separator: "." | ",";
  default_currency: string | null;
  header_row: number | null;
}

export interface PreviewRow {
  date: string;
  amount: number;
  description: string;
  merchant_name: string | null;
  category: string | null;
  status: string;
  currency: string | null;
}
export interface CsvColumn {
  index: number;
  name: string;
  suggested_role: string;
}
export interface DateFormatCandidate {
  format: string;
  label: string;
  matches: number;
  date_from: string;
  date_to: string;
}
export interface CsvDetails {
  encoding: string;
  delimiter: string;
  header_row: number | null;
  data_start: number;
  row_count: number;
  columns: CsvColumn[];
  date_formats: DateFormatCandidate[];
  date_ambiguous: boolean;
  decimal_separator: string;
  negative_styles: string[];
  currency_symbols: string[];
  sign: { convention: SignConvention; confidence: "high" | "medium" | "low"; basis: string } | null;
  suggested_mapping: CsvMapping | null;
  sample_rows: string[][];
}
export interface ParsedFile {
  rows: PreviewRow[];
  transaction_count: number;
  row_count: number;
  issue_count: number;
  issues: { row: number; reason: string }[];
  repeated_in_file: number;
  date_from: string;
  date_to: string;
  currencies: string[];
  existing_count: number | null;
  /** Rows dated before the preview's `retention_start`; an import skips them. */
  before_retention?: number;
}
export interface CategoryValue {
  value: string;
  count: number;
  suggested: string | null;
  suggested_source: "rule" | "alias" | null;
}
export interface PeriodBounds {
  suggested: DateRange;
  earliest: string;
  latest: string;
}
export interface OfxStatement {
  index: number;
  kind: "bank" | "credit_card";
  name: string;
  account_type: string;
  subtype: string | null;
  mask: string | null;
  currency: string | null;
  institution_name: string | null;
  period: DateRange | null;
  transaction_count: number;
  issue_count: number;
  corrections: number;
  date_from: string | null;
  date_to: string | null;
  matched_source_id: string | null;
  existing_count: number | null;
  rows: PreviewRow[];
  /** Rows dated before the preview's `retention_start`; an import skips them. */
  before_retention?: number;
}
export interface ImportPreview {
  format: "csv" | "ofx";
  file_sha256: string;
  previous_import_id: string | null;
  csv: CsvDetails | null;
  mapping: CsvMapping | null;
  parsed: ParsedFile | null;
  parse_error: { code: string; message: string; field: string | null } | null;
  categories: CategoryValue[];
  period: PeriodBounds | null;
  statements: OfxStatement[];
  /** The first transaction date an import keeps. */
  retention_start?: string | null;
}

export interface ImportFileBody {
  filename: string;
  content_base64: string;
}
export interface NewFileAccount {
  name: string;
  account_type: string;
  subtype?: string | null;
  currency?: string | null;
  institution_name?: string | null;
}
/** Exactly one of `source_id` and `new_account`. CSV needs `mapping` and `period`; OFX may need `statement_index`. */
export interface ImportCommitBody extends ImportFileBody {
  source_id?: string;
  new_account?: NewFileAccount;
  mapping?: CsvMapping;
  period?: DateRange;
  statement_index?: number;
  categories?: { value: string; category: string }[];
}

export interface LedgerImport {
  id: string;
  source_id: string;
  source_name: string;
  filename: string;
  format: string;
  date_from: string;
  date_to: string;
  row_count: number;
  imported_count: number;
  duplicate_count: number;
  skipped_count: number;
  status: "committed" | "reverted";
  created_at: string;
  reverted_at: string | null;
  transaction_count: number;
  /** The import created its account and nothing else is stored there; `revert(id, { removeAccount: true })` removes it too. */
  revert_removes_account?: boolean;
}
export interface ImportCommitResult {
  import: LedgerImport;
  account: LedgerAccount;
  created_account: boolean;
  inserted: number;
  existing: number;
  skipped: number;
  removed: number;
  rules_saved: number;
  /** Rows dated before `retention_start`, included in `skipped`. */
  before_retention?: number;
  retention_start?: string | null;
}
export interface ImportRevertResult {
  import: LedgerImport;
  removed: number;
  reassigned: number;
  /** The revert also removed the account the import created. */
  account_removed?: boolean;
}

const path = "/ledger";
export const ledgerImports = {
  preview: (
    body: ImportFileBody & { source_id?: string; mapping?: CsvMapping },
  ): Promise<ImportPreview> => api.post(`${path}/imports/preview`, body).then((r) => r.data),
  commit: (body: ImportCommitBody): Promise<ImportCommitResult> =>
    api.post(`${path}/imports`, body).then((r) => r.data),
  list: (sourceId?: string): Promise<LedgerImport[]> =>
    api
      .get(`${path}/imports`, { params: sourceId ? { source_id: sourceId } : {} })
      .then((r) => r.data),
  revert: (id: string, options: { removeAccount?: boolean } = {}): Promise<ImportRevertResult> =>
    api
      .delete(`${path}/imports/${id}`, {
        params: options.removeAccount ? { remove_account: true } : {},
      })
      .then((r) => r.data),
  /** Removes an imported account with its imports and transactions. */
  deleteAccount: (id: string): Promise<void> =>
    api.delete(`${path}/accounts/${id}`).then(() => undefined),
};

/** File bytes as base64, the form the import routes accept. */
export function fileToBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).replace(/^data:[^,]*,/, ""));
    reader.onerror = () => reject(new Error("The file could not be read."));
    reader.readAsDataURL(file);
  });
}
