/* Building blocks for help articles. Articles compose these instead of styling their own markup,
   so every page shares one type scale, one callout vocabulary and one way of showing arithmetic. */
import type { ReactNode } from "react";
import help from "@extensions/help";
import { articlePath, getArticleMeta } from "./help_catalog";
import { formatValue, type ValueFormat } from "./help_format";

/** A passage about the hosted service: a hosting package's version of part `id`, or `fallback`. */
export function hostedPart<T>(id: string, fallback: T): T {
  const part = help.parts?.[id];
  return part ? (part({ HelpLink, UIPath }) as T) : fallback;
}

/** Link to another help article, optionally to a section: to="roth-conversions#five-year-clock". */
export function HelpLink({ to, children }: { to: string; children?: ReactNode }) {
  const [slug, hash] = to.split("#");
  const meta = getArticleMeta(slug);
  return (
    <a
      className="help-inline-link"
      href={`${articlePath(slug)}${hash ? `#${hash}` : ""}`}
      data-help-link={slug}
    >
      {children ?? meta?.title}
    </a>
  );
}

/** A planner location, e.g. <UIPath steps={['Plan', 'Accounts', 'Cost basis']} />. Use the UI's exact labels. */
export function UIPath({ steps }: { steps: string[] }) {
  return (
    <span className="help-ui-path">
      {steps.map((step, index) => (
        <span key={`${step}-${index}`}>
          {index > 0 && (
            <span className="help-ui-path-sep" aria-hidden="true">
              ›
            </span>
          )}
          <span className="help-ui-path-step">{step}</span>
        </span>
      ))}
    </span>
  );
}

const calloutLabels = {
  entry: "Entry rule",
  boundary: "Not modeled",
  consequence: "Can’t be undone",
  where: "Where to find it",
} as const;

/**
 * entry: a data-entry rule (blank vs zero, gross vs net, today's dollars).
 * boundary: something CoastMath does not model that a reader would otherwise assume.
 * consequence: an irreversible result of an action.
 * where: the planner location that controls or shows the behavior.
 */
export function Callout({
  kind,
  title,
  children,
}: {
  kind: keyof typeof calloutLabels;
  title?: string;
  children: ReactNode;
}) {
  return (
    <aside className={`help-callout is-${kind}`}>
      {/* The kind chip always shows, so the four kinds differ by label as well as colour; a custom title sits beside it. */}
      <p className="help-callout-label">
        <span className="help-callout-kind">
          <CalloutIcon kind={kind} />
          {calloutLabels[kind]}
        </span>
        {title && <span className="help-callout-title">{title}</span>}
      </p>
      <div className="help-callout-body">{children}</div>
    </aside>
  );
}

function CalloutIcon({ kind }: { kind: keyof typeof calloutLabels }) {
  const paths = {
    entry: "M4 16.5V20h3.5L18 9.5 14.5 6 4 16.5Zm12.2-12.2 3.5 3.5",
    boundary: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm-6.4 2.6 12.8 12.8",
    consequence: "M12 4 2.8 20h18.4L12 4Zm0 6v4.5m0 2.7v.1",
    where:
      "M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21Zm0-9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d={paths[kind]} />
    </svg>
  );
}

/** A variable in a formula. */
export const V = ({ children }: { children: ReactNode }) => (
  <span className="help-var">{children}</span>
);
/** An operator in a formula: + − × ÷ = ≤ ≥ min max. */
export const Op = ({ children }: { children: ReactNode }) => (
  <span className="help-op">{children}</span>
);
/** A stacked fraction inside a formula. */
export const Frac = ({ num, den }: { num: ReactNode; den: ReactNode }) => (
  <span className="help-frac">
    <span className="help-frac-num">{num}</span>
    <span className="help-frac-den">{den}</span>
  </span>
);

/** The governing relation for a calculation: <Formula result="RMD"><V>…</V><Op>÷</Op><V>…</V></Formula>. */
export function Formula({
  result,
  children,
  note,
}: {
  result: ReactNode;
  children: ReactNode;
  note?: ReactNode;
}) {
  return (
    <div className="help-formula">
      <p className="help-formula-line">
        <span className="help-formula-result">{result}</span>
        <span className="help-op">=</span>
        <span className="help-formula-expr">{children}</span>
      </p>
      {note && <p className="help-formula-note">{note}</p>}
    </div>
  );
}

export type LedgerOp = "+" | "−" | "×" | "÷" | "=" | "→";
export interface LedgerRow {
  /** Operator applied to this row; '=' marks a result and draws a rule above it. */
  op?: LedgerOp;
  label: ReactNode;
  value: number | string;
  format?: ValueFormat;
  digits?: number;
  /** Secondary detail under the label. */
  detail?: ReactNode;
}

/** A worked example set like an adding-machine tape. Every figure must be reproducible; record how in the sources file. */
export function Ledger({
  title,
  rows,
  note,
}: {
  title: ReactNode;
  rows: LedgerRow[];
  note?: ReactNode;
}) {
  return (
    <figure className="help-ledger">
      <figcaption className="help-ledger-title">{title}</figcaption>
      <table>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className={row.op === "=" ? "is-result" : undefined}>
              <td className="help-ledger-op" aria-hidden={row.op ? undefined : true}>
                {row.op ?? ""}
              </td>
              <th scope="row">
                {row.label}
                {row.detail && <span className="help-ledger-detail">{row.detail}</span>}
              </th>
              <td className="help-ledger-value">
                {typeof row.value === "number"
                  ? formatValue(row.value, row.format ?? "usd", row.digits)
                  : row.value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {note && <p className="help-ledger-note">{note}</p>}
    </figure>
  );
}

/** Labeled figures, e.g. this year's limits. Prefer this to a sentence full of numbers. */
export function KeyFigures({
  items,
  caption,
}: {
  items: {
    label: ReactNode;
    value: number | string;
    format?: ValueFormat;
    digits?: number;
    detail?: ReactNode;
  }[];
  caption?: ReactNode;
}) {
  return (
    <figure className="help-key-figures">
      {caption && <figcaption>{caption}</figcaption>}
      <dl>
        {items.map((item, index) => (
          <div key={index}>
            <dt>{item.label}</dt>
            <dd>
              {typeof item.value === "number"
                ? formatValue(item.value, item.format ?? "usd", item.digits)
                : item.value}
            </dd>
            {item.detail && <dd className="help-key-detail">{item.detail}</dd>}
          </div>
        ))}
      </dl>
    </figure>
  );
}

/** A real sequence of actions. Not for unordered points. */
export function Steps({ children }: { children: ReactNode }) {
  return <ol className="help-steps">{children}</ol>;
}

export interface TableColumn {
  key: string;
  label: ReactNode;
  align?: "start" | "end";
  format?: ValueFormat;
  digits?: number;
}

/** A reference table. Numeric columns take a format and align to the end. */
export function DataTable({
  caption,
  columns,
  rows,
  note,
}: {
  caption: ReactNode;
  columns: TableColumn[];
  rows: Record<string, ReactNode | number>[];
  note?: ReactNode;
}) {
  // Text-heavy tables stack into one card per row on phones; numeric tables scroll sideways.
  const stacked = columns.filter((column) => !column.format && column.align !== "end").length >= 3;
  return (
    <figure className={`help-table${stacked ? " is-stacked" : ""}`}>
      <figcaption>{caption}</figcaption>
      <div
        className="help-table-scroll"
        tabIndex={0}
        role="region"
        aria-label={typeof caption === "string" ? caption : "Table"}
      >
        <table>
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={column.align === "end" || column.format ? "is-end" : undefined}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map((column, cellIndex) => {
                  const value = row[column.key];
                  const text =
                    typeof value === "number" && column.format
                      ? formatValue(value, column.format, column.digits)
                      : value;
                  const end = column.align === "end" || !!column.format;
                  return cellIndex === 0 ? (
                    <th key={column.key} scope="row" className={end ? "is-end" : undefined}>
                      {text}
                    </th>
                  ) : (
                    <td
                      key={column.key}
                      className={end ? "is-end" : undefined}
                      data-label={
                        stacked && typeof column.label === "string" ? column.label : undefined
                      }
                    >
                      {text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note && <p className="help-table-note">{note}</p>}
    </figure>
  );
}

/** Troubleshooting: what the reader sees, what to check, what to do. */
export function Symptoms({
  rows,
}: {
  rows: { symptom: ReactNode; check: ReactNode; next: ReactNode }[];
}) {
  return (
    <div className="help-symptoms" role="table" aria-label="Symptoms, checks and next steps">
      <div className="help-symptoms-head" role="row">
        <span role="columnheader">You see</span>
        <span role="columnheader">Check</span>
        <span role="columnheader">Then</span>
      </div>
      {rows.map((row, index) => (
        <div className="help-symptoms-row" role="row" key={index}>
          <div role="cell">
            <span className="help-symptoms-key" aria-hidden="true">
              You see
            </span>
            {row.symptom}
          </div>
          <div role="cell">
            <span className="help-symptoms-key" aria-hidden="true">
              Check
            </span>
            {row.check}
          </div>
          <div role="cell">
            <span className="help-symptoms-key" aria-hidden="true">
              Then
            </span>
            {row.next}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Two short, parallel cases side by side, e.g. before and after an election. */
export function Pair({
  left,
  right,
}: {
  left: { title: ReactNode; body: ReactNode };
  right: { title: ReactNode; body: ReactNode };
}) {
  return (
    <div className="help-pair">
      {[left, right].map((side, index) => (
        <div key={index} className="help-pair-side">
          <p className="help-pair-title">{side.title}</p>
          <div>{side.body}</div>
        </div>
      ))}
    </div>
  );
}

/**
 * Wrapper for a chart. `title` names what is plotted; `caption` adds only what the chart can't show
 * (never restate its readout). Pass `table` so every chart has a readable data view.
 */
export function Figure({
  title,
  caption,
  table,
  children,
  wide,
}: {
  title: ReactNode;
  caption?: ReactNode;
  table?: { columns: TableColumn[]; rows: Record<string, ReactNode | number>[] };
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <figure className={`help-figure${wide ? " is-wide" : ""}`}>
      <figcaption className="help-figure-title">{title}</figcaption>
      <div className="help-figure-plot">{children}</div>
      {caption && <p className="help-figure-caption">{caption}</p>}
      {table && (
        <details className="help-figure-data">
          <summary>Show data</summary>
          <DataTable caption={title} columns={table.columns} rows={table.rows} />
        </details>
      )}
    </figure>
  );
}
