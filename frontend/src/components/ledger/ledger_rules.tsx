import { useState } from "react";
import type { LedgerCategory, LedgerRule, RuleInput } from "@/api/ledger";
import { muted, row, stack } from "./ledger_format";

const FIELD_LABELS: Record<LedgerRule["match_field"], string> = {
  description: "Description",
  merchant: "Merchant",
  provider_category: "Bank category",
};
const TYPE_LABELS: Record<LedgerRule["match_type"], string> = {
  contains: "contains",
  equals: "is",
  starts_with: "starts with",
};

/** Categorization rules: edit the text or category, or delete. */
export default function LedgerRules({
  rules,
  categories,
  busy,
  onUpdate,
  onDelete,
}: {
  rules: LedgerRule[];
  categories: LedgerCategory[];
  busy: boolean;
  onUpdate: (rule: LedgerRule, body: Partial<RuleInput>) => void;
  onDelete: (rule: LedgerRule) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  return (
    <section aria-label="Rules" style={stack}>
      <h3 style={{ margin: 0 }}>Rules</h3>
      {rules.length === 0 ? (
        <p style={muted}>No rules yet.</p>
      ) : (
        <ul style={{ ...stack, listStyle: "none", padding: 0, margin: 0 }}>
          {rules.map((rule) => {
            const draft = drafts[rule.id] ?? rule.pattern;
            return (
              <li key={rule.id} className="card" style={row}>
                <span>
                  {FIELD_LABELS[rule.match_field]} {TYPE_LABELS[rule.match_type]}
                </span>
                <input
                  aria-label="Rule text"
                  value={draft}
                  maxLength={100}
                  disabled={busy}
                  onChange={(e) => setDrafts({ ...drafts, [rule.id]: e.target.value })}
                  onBlur={() => {
                    if (draft.trim() && draft !== rule.pattern) onUpdate(rule, { pattern: draft });
                  }}
                />
                <select
                  aria-label="Rule category"
                  value={rule.category}
                  disabled={busy}
                  onChange={(e) => onUpdate(rule, { category: e.target.value })}
                >
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
                </select>
                <span style={muted}>{rule.match_count} matched</span>
                <button type="button" disabled={busy} onClick={() => onDelete(rule)}>
                  Delete
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
