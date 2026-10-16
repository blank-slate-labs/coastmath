import { useState } from "react";
import type { AmountStrategy, CsvDetails, CsvMapping, SignConvention } from "@/api/ledger_imports";
import { muted, row, stack } from "./ledger_format";
import { COLUMN_ROLES, roleOf, valueList, withRole, type ColumnRole } from "./import_format";

const STRATEGIES: { id: AmountStrategy; label: string }[] = [
  { id: "signed", label: "One signed column" },
  { id: "split", label: "Money out and money in columns" },
  { id: "indicator", label: "Amount with a debit/credit column" },
];

/** How to read a CSV: column roles, amounts, sign and date format. */
export default function ImportCsvMapping({
  details,
  mapping,
  busy,
  onChange,
}: {
  details: CsvDetails;
  mapping: CsvMapping;
  busy: boolean;
  onChange: (mapping: CsvMapping) => void;
}) {
  const [debits, setDebits] = useState(mapping.debit_values.join(", "));
  const [credits, setCredits] = useState(mapping.credit_values.join(", "));
  const first = details.sample_rows[0] ?? [];
  return (
    <fieldset
      aria-label="Columns"
      style={{ ...stack, border: 0, padding: 0, margin: 0 }}
      disabled={busy}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: 8,
        }}
      >
        {details.columns.map((column) => (
          <label key={column.index} style={{ display: "grid", gap: 4 }}>
            <span>
              <strong>{column.name}</strong>
              {first[column.index] ? <span style={muted}> · {first[column.index]}</span> : null}
            </span>
            <select
              aria-label={`Role of ${column.name}`}
              value={roleOf(mapping, column.index)}
              onChange={(e) =>
                onChange(withRole(mapping, column.index, e.target.value as ColumnRole))
              }
            >
              {COLUMN_ROLES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <div style={row}>
        <label>
          Amounts{" "}
          <select
            aria-label="Amounts"
            value={mapping.amount_strategy}
            onChange={(e) =>
              onChange({ ...mapping, amount_strategy: e.target.value as AmountStrategy })
            }
          >
            {STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {mapping.amount_strategy === "signed" && (
          <label>
            Money in is{" "}
            <select
              aria-label="Sign"
              value={mapping.sign_convention}
              onChange={(e) =>
                onChange({ ...mapping, sign_convention: e.target.value as SignConvention })
              }
            >
              <option value="inflows_positive">positive</option>
              <option value="inflows_negative">negative</option>
            </select>
          </label>
        )}
        <label>
          Decimal{" "}
          <select
            aria-label="Decimal separator"
            value={mapping.decimal_separator}
            onChange={(e) =>
              onChange({ ...mapping, decimal_separator: e.target.value as "." | "," })
            }
          >
            <option value=".">1,234.56</option>
            <option value=",">1.234,56</option>
          </select>
        </label>
        <label>
          Dates{" "}
          <select
            aria-label="Date format"
            value={mapping.date_format ?? ""}
            onChange={(e) => onChange({ ...mapping, date_format: e.target.value || null })}
          >
            {!mapping.date_format && <option value="">Choose…</option>}
            {details.date_formats.map((f) => (
              <option key={f.format} value={f.format}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {mapping.amount_strategy === "indicator" && (
        <div style={row}>
          <label>
            Money-out values{" "}
            <input
              aria-label="Money-out values"
              value={debits}
              onChange={(e) => setDebits(e.target.value)}
              onBlur={() => onChange({ ...mapping, debit_values: valueList(debits) })}
            />
          </label>
          <label>
            Money-in values{" "}
            <input
              aria-label="Money-in values"
              value={credits}
              onChange={(e) => setCredits(e.target.value)}
              onBlur={() => onChange({ ...mapping, credit_values: valueList(credits) })}
            />
          </label>
        </div>
      )}
      {details.date_ambiguous && !mapping.date_format && (
        <p role="status" style={muted}>
          Day and month order is ambiguous.
        </p>
      )}
    </fieldset>
  );
}
