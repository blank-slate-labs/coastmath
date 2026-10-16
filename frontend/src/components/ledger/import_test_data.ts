import type {
  CsvDetails,
  CsvMapping,
  ImportPreview,
  LedgerImport,
  OfxStatement,
} from "@/api/ledger_imports";

export function csvMapping(overrides: Partial<CsvMapping> = {}): CsvMapping {
  return {
    delimiter: ",",
    data_start: 1,
    date_column: 0,
    date_format: "%Y-%m-%d",
    description_columns: [1],
    amount_strategy: "signed",
    amount_column: 2,
    sign_convention: "inflows_positive",
    debit_column: null,
    credit_column: null,
    type_column: null,
    debit_values: [],
    credit_values: [],
    posted_date_column: null,
    merchant_column: null,
    category_column: 3,
    currency_column: null,
    status_column: null,
    decimal_separator: ".",
    default_currency: null,
    header_row: 0,
    ...overrides,
  };
}

export function csvDetails(overrides: Partial<CsvDetails> = {}): CsvDetails {
  return {
    encoding: "utf-8",
    delimiter: ",",
    header_row: 0,
    data_start: 1,
    row_count: 2,
    columns: [
      { index: 0, name: "Date", suggested_role: "date" },
      { index: 1, name: "Description", suggested_role: "description" },
      { index: 2, name: "Amount", suggested_role: "amount" },
      { index: 3, name: "Category", suggested_role: "category" },
    ],
    date_formats: [
      {
        format: "%Y-%m-%d",
        label: "YYYY-MM-DD",
        matches: 2,
        date_from: "2026-08-02",
        date_to: "2026-08-25",
      },
    ],
    date_ambiguous: false,
    decimal_separator: ".",
    negative_styles: ["minus"],
    currency_symbols: [],
    sign: { convention: "inflows_positive", confidence: "medium", basis: "majority" },
    suggested_mapping: csvMapping(),
    sample_rows: [["2026-08-02", "SYNTHETIC GROCER", "-80.00", "Groceries"]],
    ...overrides,
  };
}

export function csvPreview(overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    format: "csv",
    file_sha256: "a".repeat(64),
    previous_import_id: null,
    csv: csvDetails(),
    mapping: csvMapping(),
    parsed: {
      rows: [
        {
          date: "2026-08-02",
          amount: 80,
          description: "SYNTHETIC GROCER",
          merchant_name: null,
          category: "Groceries",
          status: "POSTED",
          currency: "USD",
        },
        {
          date: "2026-08-25",
          amount: -2000,
          description: "PAYROLL",
          merchant_name: null,
          category: "Pay",
          status: "PENDING",
          currency: "USD",
        },
      ],
      transaction_count: 2,
      row_count: 2,
      issue_count: 1,
      issues: [{ row: 4, reason: "invalid_amount" }],
      repeated_in_file: 0,
      date_from: "2026-08-02",
      date_to: "2026-08-25",
      currencies: ["USD"],
      existing_count: null,
    },
    parse_error: null,
    categories: [
      { value: "Groceries", count: 1, suggested: "groceries", suggested_source: "alias" },
      { value: "Pay", count: 1, suggested: null, suggested_source: null },
    ],
    period: {
      suggested: { start: "2026-08-02", end: "2026-08-25" },
      earliest: "2026-08-01",
      latest: "2026-08-31",
    },
    statements: [],
    ...overrides,
  };
}

export function statement(overrides: Partial<OfxStatement> = {}): OfxStatement {
  return {
    index: 0,
    kind: "bank",
    name: "Checking ··5678",
    account_type: "DEPOSITORY",
    subtype: "CHECKING",
    mask: "5678",
    currency: "USD",
    institution_name: "Example Credit Union",
    period: { start: "2026-08-01", end: "2026-08-31" },
    transaction_count: 2,
    issue_count: 0,
    corrections: 0,
    date_from: "2026-08-03",
    date_to: "2026-08-15",
    matched_source_id: null,
    existing_count: null,
    rows: [
      {
        date: "2026-08-03",
        amount: 42,
        description: "SYNTHETIC SHOP",
        merchant_name: null,
        category: null,
        status: "POSTED",
        currency: "USD",
      },
    ],
    ...overrides,
  };
}

export function ofxPreview(statements: OfxStatement[]): ImportPreview {
  return {
    format: "ofx",
    file_sha256: "b".repeat(64),
    previous_import_id: null,
    csv: null,
    mapping: null,
    parsed: null,
    parse_error: null,
    categories: [],
    period: null,
    statements,
  };
}

export function ledgerImport(overrides: Partial<LedgerImport> = {}): LedgerImport {
  return {
    id: "i1",
    source_id: "a1",
    source_name: "Synthetic card",
    filename: "august.csv",
    format: "csv",
    date_from: "2026-08-01",
    date_to: "2026-08-31",
    row_count: 6,
    imported_count: 6,
    duplicate_count: 0,
    skipped_count: 0,
    status: "committed",
    created_at: "2026-09-02T00:00:00Z",
    reverted_at: null,
    transaction_count: 6,
    ...overrides,
  };
}
