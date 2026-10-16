import { useCallback, useEffect, useRef, useState } from "react";
import { ledger } from "@/api/ledger";
import type { DateRange, LedgerAccount, LedgerCategory } from "@/api/ledger";
import { fileToBase64, ledgerImports } from "@/api/ledger_imports";
import type {
  CsvMapping,
  ImportCommitBody,
  ImportCommitResult,
  ImportPreview,
  LedgerImport,
  PreviewRow,
} from "@/api/ledger_imports";
import ImportCsvMapping from "./import_csv_mapping";
import ImportHistory from "./import_history";
import {
  ACCOUNT_KINDS,
  dayLabel,
  exact,
  kindFor,
  mappingFromColumns,
  rangeLabel,
  type AccountKind,
} from "./import_format";
import { errorMessage } from "@/utils/error_message";
import { muted, row, stack } from "./ledger_format";

export interface LedgerPanelProps {
  onChanged: () => void;
  /** Changes when the section removes an account, so the lists reload. */
  reloadKey?: number;
}

interface Upload {
  filename: string;
  content_base64: string;
}
interface NewAccountDraft {
  name: string;
  institution: string;
  kind: AccountKind;
}
const NEW = "new";
const BLANK_ACCOUNT: NewAccountDraft = { name: "", institution: "", kind: "credit_card" };

/** Import CSV, OFX or QFX statements into file accounts, and revert earlier imports. */
export default function LedgerImportPanel({ onChanged, reloadKey = 0 }: LedgerPanelProps) {
  const [accounts, setAccounts] = useState<LedgerAccount[]>([]);
  const [categories, setCategories] = useState<LedgerCategory[]>([]);
  const [imports, setImports] = useState<LedgerImport[]>([]);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<CsvMapping | null>(null);
  const [period, setPeriod] = useState<DateRange | null>(null);
  const [target, setTarget] = useState<string>(NEW);
  const [draft, setDraft] = useState<NewAccountDraft>(BLANK_ACCOUNT);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [statement, setStatement] = useState(0);
  const [result, setResult] = useState<ImportCommitResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A failed import save, shown by the Import button.
  const [commitError, setCommitError] = useState<string | null>(null);
  // Set before the first await: `busy` reaches a second click only after a render.
  const running = useRef(false);

  const load = useCallback(async () => {
    const [all, cats, history] = await Promise.all([
      ledger.accounts(),
      ledger.categories(),
      ledgerImports.list(),
    ]);
    setAccounts(all.filter((a) => a.provider === "file"));
    setCategories(cats);
    setImports(history);
  }, []);

  useEffect(() => {
    void load().catch((e) => setError(errorMessage(e)));
  }, [load, reloadKey]);

  async function run(action: () => Promise<void>, report: (message: string) => void = setError) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setCommitError(null);
    try {
      await action();
    } catch (e) {
      report(errorMessage(e));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  /** Apply a fresh preview: the first one seeds every choice; later ones keep the customer's. */
  function adopt(next: ImportPreview, first: boolean) {
    setPreview(next);
    setMapping(next.mapping ?? (next.csv ? mappingFromColumns(next.csv) : null));
    // Keep a chosen period only while it still fits the file as now read.
    setPeriod((current) => {
      const bounds = next.period;
      if (!bounds) return null;
      const fits =
        !!current &&
        current.start >= bounds.earliest &&
        current.start <= bounds.suggested.start &&
        current.end <= bounds.latest &&
        current.end >= bounds.suggested.end;
      return !first && fits ? current : bounds.suggested;
    });
    setChoices((current) =>
      Object.fromEntries(
        next.categories.map((c) => [
          c.value,
          first
            ? (c.suggested ?? "uncategorized")
            : (current[c.value] ?? c.suggested ?? "uncategorized"),
        ]),
      ),
    );
    if (first && next.format === "ofx" && next.statements.length) chooseStatement(next, 0);
  }

  function chooseStatement(source: ImportPreview, index: number) {
    const found = source.statements[index];
    setStatement(index);
    setTarget(found.matched_source_id ?? NEW);
    setDraft({
      name: found.name,
      institution: found.institution_name ?? "",
      kind: kindFor(found.account_type, found.subtype),
    });
  }

  function choose(file: File | undefined) {
    if (!file) return;
    void run(async () => {
      const body = { filename: file.name, content_base64: await fileToBase64(file) };
      setResult(null);
      setTarget(NEW);
      setDraft(BLANK_ACCOUNT);
      const next = await ledgerImports.preview(body);
      setUpload(body);
      adopt(next, true);
    });
  }

  function refresh(changes: { mapping?: CsvMapping; target?: string }) {
    if (!upload || !preview) return;
    const nextTarget = changes.target ?? target;
    const nextMapping = changes.mapping ?? mapping;
    if (changes.target !== undefined) setTarget(nextTarget);
    if (changes.mapping) setMapping(changes.mapping);
    void run(async () => {
      adopt(
        await ledgerImports.preview({
          ...upload,
          ...(nextTarget !== NEW ? { source_id: nextTarget } : {}),
          ...(preview.format === "csv" && nextMapping ? { mapping: nextMapping } : {}),
        }),
        false,
      );
    });
  }

  function reset() {
    setUpload(null);
    setPreview(null);
    setMapping(null);
    setPeriod(null);
    setChoices({});
    setCommitError(null);
  }

  function commit() {
    if (!upload || !preview) return;
    const kind = ACCOUNT_KINDS.find((k) => k.id === draft.kind)!;
    const body: ImportCommitBody = {
      ...upload,
      ...(target !== NEW
        ? { source_id: target }
        : {
            new_account: {
              name: draft.name.trim(),
              account_type: kind.account_type,
              subtype: kind.subtype,
              ...(draft.institution.trim() ? { institution_name: draft.institution.trim() } : {}),
            },
          }),
      ...(preview.format === "csv"
        ? {
            mapping: mapping!,
            period: period!,
            categories: Object.entries(choices).map(([value, category]) => ({ value, category })),
          }
        : { statement_index: statement }),
    };
    // A failure keeps the file, mapping and choices so the import can be retried.
    void run(async () => {
      const done = await ledgerImports.commit(body);
      setResult(done);
      reset();
      await load();
      onChanged();
    }, setCommitError);
  }

  function revert(item: LedgerImport) {
    void run(async () => {
      await ledgerImports.revert(item.id, { removeAccount: item.revert_removes_account === true });
      await load();
      onChanged();
    });
  }

  const ofx = preview?.format === "ofx" ? preview.statements[statement] : null;
  const rows: PreviewRow[] = ofx ? ofx.rows : (preview?.parsed?.rows ?? []);
  const count = ofx ? ofx.transaction_count : (preview?.parsed?.transaction_count ?? 0);
  const existing = ofx ? ofx.existing_count : (preview?.parsed?.existing_count ?? null);
  const skipped = ofx ? ofx.issue_count : (preview?.parsed?.issue_count ?? 0);
  const tooOld = (ofx ? ofx.before_retention : preview?.parsed?.before_retention) ?? 0;
  const importable = count - tooOld;
  const retentionStart = preview?.retention_start;
  const resultTooOld = result?.before_retention ?? 0;
  const ready =
    !!preview &&
    !preview.previous_import_id &&
    importable > 0 &&
    (target !== NEW || draft.name.trim() !== "") &&
    (preview.format === "ofx" ? !!ofx?.period : !!preview.parsed && !!period && !!mapping);

  return (
    <section
      aria-label="Import transactions"
      style={stack}
      data-save-pending={busy ? "true" : undefined}
    >
      <h3 style={{ margin: 0 }}>Import</h3>
      {error && (
        <p role="alert" className="field-error">
          {error}
        </p>
      )}
      <label style={row}>
        Statement file{" "}
        <input
          type="file"
          aria-label="Statement file"
          accept=".csv,.ofx,.qfx,text/csv"
          disabled={busy}
          onChange={(e) => {
            choose(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </label>
      {result && (
        <p role="status" style={row}>
          <span>
            <strong>{result.inserted}</strong> imported
          </span>
          <span>
            <strong>{result.existing}</strong> already there
          </span>
          {result.skipped - resultTooOld > 0 && (
            <span>
              <strong>{result.skipped - resultTooOld}</strong> skipped
            </span>
          )}
          {resultTooOld > 0 && result.retention_start && (
            <span>
              <strong>{resultTooOld}</strong> dated before {dayLabel(result.retention_start)},
              skipped
            </span>
          )}
          {result.removed > 0 && (
            <span>
              <strong>{result.removed}</strong> removed
            </span>
          )}
        </p>
      )}
      {preview && upload && (
        <div className="card" style={stack}>
          <strong>{upload.filename}</strong>
          {preview.format === "csv" && preview.csv && mapping && (
            <ImportCsvMapping
              key={preview.file_sha256}
              details={preview.csv}
              mapping={mapping}
              busy={busy}
              onChange={(next) => refresh({ mapping: next })}
            />
          )}
          {preview.parse_error && (
            <p role="alert" className="field-error">
              {preview.parse_error.message}
            </p>
          )}
          {preview.format === "ofx" && preview.statements.length > 1 && (
            <label>
              Account in file{" "}
              <select
                aria-label="Account in file"
                value={statement}
                disabled={busy}
                onChange={(e) => chooseStatement(preview, Number(e.target.value))}
              >
                {preview.statements.map((s) => (
                  <option key={s.index} value={s.index}>
                    {s.name} · {s.transaction_count}
                  </option>
                ))}
              </select>
            </label>
          )}
          {rows.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  <th align="left">Date</th>
                  <th align="left">Description</th>
                  <th align="right">Out</th>
                  <th align="right">In</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td>{r.date}</td>
                    <td>
                      {r.description}
                      {r.status === "PENDING" ? " · pending" : ""}
                    </td>
                    <td align="right">{r.amount > 0 ? exact(r.amount, r.currency) : ""}</td>
                    <td align="right">{r.amount < 0 ? exact(-r.amount, r.currency) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={row}>
            <span>
              <strong>{count}</strong> transactions
            </span>
            {existing != null && (
              <span>
                <strong>{existing}</strong> already there
              </span>
            )}
            {skipped > 0 && (
              <span>
                <strong>{skipped}</strong> unreadable rows
              </span>
            )}
            {tooOld > 0 && retentionStart && (
              <span>
                <strong>{tooOld}</strong> dated before {dayLabel(retentionStart)}, skipped
              </span>
            )}
          </div>
          {preview.format === "csv" && preview.period && period && (
            <fieldset
              aria-label="Statement period"
              style={{ ...stack, border: 0, padding: 0, margin: 0 }}
              disabled={busy}
            >
              <div style={row}>
                <label>
                  From{" "}
                  <input
                    type="date"
                    aria-label="Period start"
                    value={period.start}
                    min={preview.period.earliest}
                    max={preview.period.suggested.start}
                    onChange={(e) =>
                      e.target.value && setPeriod({ ...period, start: e.target.value })
                    }
                  />
                </label>
                <label>
                  To{" "}
                  <input
                    type="date"
                    aria-label="Period end"
                    value={period.end}
                    min={preview.period.suggested.end}
                    max={preview.period.latest}
                    onChange={(e) =>
                      e.target.value && setPeriod({ ...period, end: e.target.value })
                    }
                  />
                </label>
                <button type="button" onClick={() => setPeriod(preview.period!.suggested)}>
                  Dates in file
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setPeriod({ start: preview.period!.earliest, end: preview.period!.latest })
                  }
                >
                  Whole months
                </button>
              </div>
              <p style={muted}>Months count only when the period covers every day.</p>
            </fieldset>
          )}
          {ofx && ofx.period && <span>Period {rangeLabel(ofx.period.start, ofx.period.end)}</span>}
          <div style={row}>
            <label>
              Account{" "}
              <select
                aria-label="Target account"
                value={target}
                disabled={busy}
                onChange={(e) => refresh({ target: e.target.value })}
              >
                <option value={NEW}>New account</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {a.mask ? ` ··${a.mask}` : ""}
                  </option>
                ))}
              </select>
            </label>
            {target === NEW && (
              <>
                <input
                  aria-label="Account name"
                  placeholder="Name"
                  value={draft.name}
                  maxLength={255}
                  disabled={busy}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
                <input
                  aria-label="Institution"
                  placeholder="Institution"
                  value={draft.institution}
                  maxLength={255}
                  disabled={busy}
                  onChange={(e) => setDraft({ ...draft, institution: e.target.value })}
                />
                <select
                  aria-label="Account type"
                  value={draft.kind}
                  disabled={busy}
                  onChange={(e) => setDraft({ ...draft, kind: e.target.value as AccountKind })}
                >
                  {ACCOUNT_KINDS.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>
          {preview.format === "csv" && preview.categories.length > 0 && (
            <fieldset
              aria-label="Bank categories"
              style={{ ...stack, border: 0, padding: 0, margin: 0 }}
              disabled={busy}
            >
              <strong>Bank categories</strong>
              {preview.categories.map((c) => (
                <label key={c.value} style={row}>
                  <span style={{ minWidth: 160 }}>
                    {c.value} <span style={muted}>· {c.count}</span>
                  </span>
                  <select
                    aria-label={`Category for ${c.value}`}
                    value={choices[c.value] ?? "uncategorized"}
                    onChange={(e) => setChoices({ ...choices, [c.value]: e.target.value })}
                  >
                    {categories.map((cat) => (
                      <option key={cat.id} value={cat.id}>
                        {cat.label}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </fieldset>
          )}
          {preview.previous_import_id && (
            <p role="status">This file is already imported into this account.</p>
          )}
          <div style={row}>
            <button type="button" disabled={busy || !ready} onClick={commit}>
              Import {importable} transactions
            </button>
            <button type="button" disabled={busy} onClick={reset}>
              Cancel
            </button>
          </div>
          {commitError && (
            <p role="alert" className="field-error" style={{ margin: 0 }}>
              {commitError}
            </p>
          )}
        </div>
      )}
      <ImportHistory imports={imports} busy={busy} onRevert={revert} />
    </section>
  );
}
