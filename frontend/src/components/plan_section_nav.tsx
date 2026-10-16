import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { useFiEstimateHidden } from "@/stores/fi_estimate_store";
import {
  FI_ESTIMATE_LABEL,
  financialIndependence,
  ownFiMilestone,
} from "@/utils/financial_independence";
import { PLAN_SECTIONS, type PlanSectionKey } from "@/pages/plan_setup";
import { NavGlyph } from "@/components/plan_nav_icons";
import { SAVED_METHODS } from "@/domain/withdrawal_strategy";
import type { Account, CurveType, PlanData, SimulationResult } from "@/types/plan";
import { intlCompactCurrency } from "@/utils/format";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import { US_COUNTRY, countryName, planTaxCountry } from "@/domain/intl_plan";

/** Compact money in the plan's display currency ("$1.2M" in USD). */
const money = { format: intlCompactCurrency };

const filingLabels: Record<string, string> = {
  single: "Single",
  married_filing_jointly: "Married (joint)",
  married_filing_separately: "Married (separate)",
  head_of_household: "Head of household",
};

interface TileSummary {
  /** Count badge, shown only when defined. */
  count?: number;
  /** One line of secondary text describing the section's current contents. */
  summary: string;
  /** When true, the tile invites the user to add their first item. */
  empty?: boolean;
}

function ratePct(rate: number | null | undefined): string | null {
  if (rate == null) return null;
  return `${(rate * 100).toFixed(1)}%`;
}

/** Derive a compact, live summary for one section from the plan + accounts. */
function summarize(
  key: PlanSectionKey,
  plan: PlanData,
  accounts: Account[],
  simulation: SimulationResult | null,
  fiEstimateHidden: boolean,
): TileSummary {
  switch (key) {
    case "plan_details": {
      const bits = [
        filingLabels[plan.filing_status] ?? plan.filing_status,
        `born ${plan.birth_year}`,
      ];
      if (planTaxCountry(plan) !== US_COUNTRY) bits.push(countryName(planTaxCountry(plan)));
      // A US plan without a state pays no state tax; say so, so a forgotten state shows.
      else bits.push(plan.state_code || "no state tax");
      return { summary: bits.join(" · ") };
    }
    case "assumptions": {
      const curves = plan.assumption_curves ?? [];
      const mr = curves.find((c) => c.curve_type === "market_return");
      const inf = curves.find((c) => c.curve_type === "inflation");
      // Unsaved assumptions use the engine defaults the service reports, when it does.
      const defaults = plan.assumption_defaults ?? {};
      const growth =
        mr?.mode === "curve"
          ? "custom curve"
          : (ratePct(mr?.fixed_rate) ?? ratePct(defaults.market_return) ?? "default");
      const inflation =
        inf?.mode === "curve"
          ? "custom"
          : (ratePct(inf?.fixed_rate) ?? ratePct(defaults.inflation) ?? "3.0%");
      return { summary: `Growth ${growth} · inflation ${inflation}` };
    }
    case "milestones": {
      // The built-in CoastMath FI estimate is listed with the plan's milestones.
      const estimate =
        !fiEstimateHidden && !ownFiMilestone(plan)
          ? {
              name: FI_ESTIMATE_LABEL,
              year: financialIndependence(simulation).snapshot?.year ?? null,
            }
          : null;
      const count = plan.milestones.length + (estimate ? 1 : 0);
      if (count === 0) return { count, summary: "No milestones yet.", empty: true };
      const outcomes = [
        ...(simulation?.metadata.milestone_outcomes ?? []),
        ...(estimate ? [estimate] : []),
      ].filter((o) => o.year != null);
      const next = outcomes.sort((a, b) => (a.year ?? 0) - (b.year ?? 0))[0];
      if (next) return { count, summary: `Next: ${next.name} in ${next.year}` };
      return {
        count,
        summary: [...plan.milestones.map((m) => m.name), ...(estimate ? [estimate.name] : [])]
          .slice(0, 2)
          .join(", "),
      };
    }
    case "income": {
      const streams = plan.income_streams;
      if (streams.length === 0)
        return { count: 0, summary: "Add your first income stream", empty: true };
      return { count: streams.length, summary: `${streams.length} sources across plan years` };
    }
    case "expenses": {
      const expenses = plan.expenses;
      if (expenses.length === 0)
        return { count: 0, summary: "Add your living expenses", empty: true };
      return { count: expenses.length, summary: `${expenses.length} expenses across plan years` };
    }
    case "flex": {
      const rules = plan.spending_rules;
      const strategy = plan.withdrawal_strategy?.enabled
        ? SAVED_METHODS.find((m) => m.value === plan.withdrawal_strategy?.method)?.label
        : undefined;
      const spendsLeftover = rules?.surplus_mode === "spend_leftover";
      const extras = `${spendsLeftover ? " · Spends leftover cash" : ""}${strategy ? ` · ${strategy}` : ""}`;
      if (!rules || rules.flex_threshold == null) {
        const upside = (rules?.upside_thresholds?.length ?? 0) > 0;
        if (upside) return { summary: `Raise spending above prior highs${extras}` };
        if (spendsLeftover)
          return { summary: `Spends leftover cash${strategy ? ` · ${strategy}` : ""}` };
        if (strategy) return { summary: `Withdrawal strategy: ${strategy}` };
        return { summary: "No flexible spending rule.", empty: true };
      }
      const cut = Math.round((rules.flex_reduction ?? 0) * 100);
      return { summary: `Cut ${cut}% · ${rules.lookback_years}-yr lookback${extras}` };
    }
    case "accounts": {
      if (accounts.length === 0)
        return { count: 0, summary: "Add your first account", empty: true };
      const total = accounts.reduce((sum, a) => sum + (a.balance ?? 0), 0);
      const types = new Set(accounts.map((a) => a.account_type)).size;
      // An older plan without its own accounts shares the household's with every such plan.
      return {
        count: accounts.length,
        summary: `${money.format(total)} · ${types} ${types === 1 ? "type" : "types"}${plan.client_id ? "" : " · shared"}`,
      };
    }
    case "income_allocation": {
      const priorities = plan.priorities ?? [];
      if (priorities.length === 0) return { count: 0, summary: "No savings rules.", empty: true };
      return {
        count: priorities.length,
        summary: `${priorities.length} savings ${priorities.length === 1 ? "rule" : "rules"}`,
      };
    }
    case "property_debt": {
      const assets = plan.real_assets ?? [];
      const debts = plan.liabilities ?? [];
      const count = assets.length + debts.length;
      if (count === 0) return { count: 0, summary: "No property or debt.", empty: true };
      const assetValue = assets.reduce((sum, a) => sum + (a.current_value ?? 0), 0);
      const debtValue = debts.reduce((sum, d) => sum + (d.principal_balance ?? 0), 0);
      const parts: string[] = [];
      if (assets.length) parts.push(`${money.format(assetValue)} assets`);
      if (debts.length) parts.push(`${money.format(debtValue)} debt`);
      return { count, summary: parts.join(" · ") };
    }
    case "drawdown": {
      const order = [...(plan.drawdown_order ?? [])].sort((a, b) => a.rank - b.rank);
      if (order.length === 0) return { count: 0, summary: "No withdrawal order.", empty: true };
      const names = order
        .slice(0, 3)
        .map((entry) => accounts.find((a) => a.id === entry.source_account_id)?.name ?? "Account");
      const suffix = order.length > 3 ? " → …" : "";
      return { count: order.length, summary: names.join(" → ") + suffix };
    }
    case "connections":
      return { summary: "Institutions, balance sync and reconnects" };
    case "transactions":
      return { summary: "Accounts, months and categories" };
    case "charitable":
      return { summary: "Gifts, donor-advised funds and QCDs" };
    case "healthcare": {
      const hc = plan.healthcare_settings;
      if (!hc || !hc.enabled) return { summary: "No health coverage settings.", empty: true };
      const parts: string[] = [];
      if (hc.aca_enabled) parts.push("Marketplace");
      if (hc.medicare_enabled) parts.push("Medicare");
      return { summary: parts.length ? parts.join(" + ") : "Enabled" };
    }
    case "estate": {
      if (plan.spouse) {
        return { summary: `Partner: ${plan.spouse.name?.trim() || "configured"}` };
      }
      return { summary: "No partner or estate settings.", empty: true };
    }
    case "notes": {
      const notes = plan.notes?.trim();
      if (!notes) return { summary: "No notes.", empty: true };
      const firstLine = notes.split("\n")[0];
      return { summary: firstLine.length > 64 ? `${firstLine.slice(0, 63)}…` : firstLine };
    }
    default:
      return { summary: "" };
  }
}

type Category = "essentials" | "assumptions" | "optional";

const CATEGORIES: { key: Category; title: string; footer: string }[] = [
  { key: "essentials", title: "Essentials", footer: "Required to run your projection." },
  { key: "optional", title: "Optional", footer: "Add these when they apply to you." },
  { key: "assumptions", title: "Assumptions", footer: "How markets and prices behave over time." },
];

/** Required inputs, in the order a new plan fills them in. */
const ESSENTIAL_ORDER: PlanSectionKey[] = ["plan_details", "accounts", "income", "expenses"];
/** Optional sections, roughly from most to least commonly used. Unlisted sections follow. */
const OPTIONAL_ORDER: PlanSectionKey[] = [
  "connections",
  "transactions",
  "property_debt",
  "income_allocation",
  "milestones",
  "drawdown",
  "healthcare",
  "flex",
  "charitable",
  "estate",
  "notes",
];

/** Extra words the filter matches, so "mortgage" finds Property and debt. */
const KEYWORDS: Partial<Record<PlanSectionKey, string>> = {
  plan_details: "profile filing status tax state birth age",
  accounts: "balances 401k ira roth brokerage savings hsa investments",
  income: "salary wages pension social security",
  expenses: "spending budget costs",
  assumptions: "returns rates market",
  connections: "bank sync link institutions",
  transactions: "spending import categories rules months",
  property_debt: "home house mortgage loan real estate liabilities",
  income_allocation: "savings contributions priorities",
  milestones: "retirement goals financial independence",
  drawdown: "withdrawals retirement",
  healthcare: "medicare aca insurance",
  flex: "guardrails spending cuts withdrawal strategy 4% rule vpw",
  charitable: "donations giving qcd daf",
  estate: "spouse partner heirs",
};

/** The assumptions the Assumptions editor offers, plus any other saved curve type. */
const ASSUMPTION_ROWS: { type: CurveType; label: string }[] = [
  { type: "market_return", label: "Stock growth" },
  { type: "inflation", label: "Inflation" },
  { type: "dividend_yield", label: "Dividend yield" },
  { type: "bond_return", label: "Bond return" },
  { type: "bond_allocation", label: "Bond allocation" },
  { type: "wage_growth", label: "Wage growth" },
  { type: "cash_yield", label: "Cash yield" },
  { type: "social_security_cola", label: "Social Security COLA" },
];

interface AssumptionValue {
  type: CurveType;
  label: string;
  value: string;
  /** Saved by the user (a fixed rate or a curve), or the engine default. */
  source: "saved" | "curve" | "default";
}

/**
 * One readable value per assumption. Stock growth and inflation are always
 * listed, as in the one-line summary; the others appear once saved or when the
 * service reports an engine default for them.
 */
function assumptionValues(plan: PlanData): AssumptionValue[] {
  const curves = plan.assumption_curves ?? [];
  const defaults = plan.assumption_defaults ?? {};
  return ASSUMPTION_ROWS.flatMap(({ type, label }): AssumptionValue[] => {
    const curve = curves.find((c) => c.curve_type === type);
    if (curve?.mode === "curve") return [{ type, label, value: "Custom curve", source: "curve" }];
    const saved = ratePct(curve?.fixed_rate);
    if (saved) return [{ type, label, value: saved, source: "saved" }];
    const fallback =
      ratePct(defaults[type]) ??
      (type === "inflation" ? "3.0%" : type === "market_return" || curve ? "Default" : null);
    return fallback ? [{ type, label, value: fallback, source: "default" }] : [];
  });
}

interface NavRow extends TileSummary {
  key: PlanSectionKey;
  title: string;
  essential: boolean;
  category: Category;
  /** Lower-cased text the filter searches. */
  haystack: string;
}

function categoryOf(key: PlanSectionKey, essential: boolean): Category {
  if (key === "assumptions") return "assumptions";
  return essential ? "essentials" : "optional";
}

function rank(row: Pick<NavRow, "key" | "category">): number {
  const order = row.category === "essentials" ? ESSENTIAL_ORDER : OPTIONAL_ORDER;
  const index = order.indexOf(row.key);
  const base = CATEGORIES.findIndex((c) => c.key === row.category) * 100;
  return base + (index === -1 ? 99 : index);
}

/** Whether a key press is text entry into some other field, which shortcuts must leave alone. */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.closest(
      "input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='combobox']",
    ) != null
  );
}

/**
 * Sidebar list of plan sections, as inset grouped cards: Essentials (required
 * inputs), Optional sections and Assumptions (model settings, shown as values).
 * A filter field at the top (⌘K, Ctrl+K or /) narrows every card at once.
 * Selecting a row opens that section in the Edit sheet; `activeKey` highlights
 * the section currently open.
 */
export default function PlanSectionNav({
  activeKey,
  onEdit,
}: {
  activeKey: PlanSectionKey | null;
  onEdit: (key: PlanSectionKey) => void;
}) {
  const plan = usePlanStore((s) => s.plan);
  const simulation = usePlanStore((s) => s.simulation);
  const fiEstimateHidden = useFiEstimateHidden(plan?.id);
  const { adapter } = useStorage();
  const { accounts, status: accountStatus } = usePlanAccounts(adapter, plan?.id);
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const filterRef = useRef<HTMLInputElement>(null);
  const uid = useId();

  const assumptions = useMemo(() => (plan ? assumptionValues(plan) : []), [plan]);

  const rows = useMemo<NavRow[]>(() => {
    if (!plan) return [];
    return PLAN_SECTIONS.map((section) => {
      const tile: TileSummary = {
        ...summarize(section.key, plan, accounts, simulation, fiEstimateHidden),
        ...(section.key === "accounts" && accountStatus !== "ready"
          ? {
              count: undefined,
              summary:
                accountStatus === "loading" ? "Loading accounts…" : "Could not load accounts",
              empty: false,
            }
          : {}),
      };
      const essential = section.essential === true;
      const category = categoryOf(section.key, essential);
      const settings =
        section.key === "assumptions" ? assumptions.map((a) => `${a.label} ${a.value}`) : [];
      const haystack = [section.title, tile.summary, KEYWORDS[section.key] ?? "", ...settings]
        .join(" ")
        .toLowerCase();
      return { ...tile, key: section.key, title: section.title, essential, category, haystack };
    }).sort((a, b) => rank(a) - rank(b));
  }, [plan, accounts, simulation, accountStatus, fiEstimateHidden, assumptions]);

  // ⌘K / Ctrl+K / "/" focus the filter, unless the visitor is typing elsewhere,
  // a modal (the Edit sheet, a dialog, the sign-in prompt) is open, or the
  // sidebar is collapsed.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // Browser autofill dispatches keydown events without a key.
      if (
        typeof event.key !== "string" ||
        event.defaultPrevented ||
        event.isComposing ||
        event.altKey
      )
        return;
      const commandK =
        (event.metaKey || event.ctrlKey) && !event.shiftKey && event.key.toLowerCase() === "k";
      const slash = event.key === "/" && !event.metaKey && !event.ctrlKey;
      if (!commandK && !slash) return;
      const input = filterRef.current;
      if (!input || input.closest("[hidden], [inert]")) return;
      if (isEditableTarget(event.target)) return;
      if (document.querySelector('[role="dialog"][aria-modal="true"], dialog[open]')) return;
      event.preventDefault();
      input.focus();
      input.select();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  if (!plan) return null;

  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const filtering = terms.length > 0;
  const visible = filtering
    ? rows.filter((row) => terms.every((term) => row.haystack.includes(term)))
    : rows;
  const essentials = rows.filter((row) => row.category === "essentials");
  const essentialsDone = essentials.filter((row) => !row.empty).length;

  const clearFilter = () => {
    setQuery("");
    filterRef.current?.focus();
  };

  const onFilterKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      if (query) {
        event.preventDefault();
        event.stopPropagation();
        setQuery("");
      } else {
        event.currentTarget.blur();
      }
    } else if (event.key === "ArrowDown") {
      const first = navRef.current?.querySelector<HTMLElement>("button.plan-nav-item");
      if (first) {
        event.preventDefault();
        first.focus();
      }
    } else if (event.key === "Enter" && filtering && visible.length > 0) {
      event.preventDefault();
      onEdit(visible[0].key);
    }
  };

  // Arrow keys move between rows; Tab still walks every control in order.
  const onNavKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    if (!target.matches("button.plan-nav-item")) return;
    const items = Array.from(
      navRef.current?.querySelectorAll<HTMLElement>("button.plan-nav-item") ?? [],
    );
    const index = items.indexOf(target);
    let next: HTMLElement | null | undefined;
    if (event.key === "ArrowDown") next = items[index + 1];
    else if (event.key === "ArrowUp") next = index === 0 ? filterRef.current : items[index - 1];
    else if (event.key === "Home") next = items[0];
    else if (event.key === "End") next = items[items.length - 1];
    else return;
    event.preventDefault();
    next?.focus();
  };

  // Title-line badge: essentials still missing input, otherwise the item count.
  const badge = (row: NavRow) => {
    if (row.essential && row.empty) {
      return (
        <span className="plan-nav-needs" id={`${uid}-${row.key}-needs`}>
          <span className="plan-nav-dot" aria-hidden="true" />
          Needs input
        </span>
      );
    }
    return row.count != null ? <span className="plan-nav-count">{row.count}</span> : null;
  };

  const renderRow = (row: NavRow) => {
    const active = row.key === activeKey;
    const describedBy = [
      `${uid}-${row.key}-summary`,
      row.essential && row.empty ? `${uid}-${row.key}-needs` : "",
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <li key={row.key}>
        <button
          type="button"
          className={`plan-nav-item${row.empty ? " is-empty" : ""}${active ? " is-active" : ""}`}
          onClick={() => onEdit(row.key)}
          aria-label={`Edit ${row.title}${row.essential ? "" : ", optional"}`}
          aria-describedby={describedBy}
          aria-current={active ? "true" : undefined}
        >
          <span className={`plan-nav-tile is-${row.category}`} aria-hidden="true">
            <NavGlyph name={row.key} />
          </span>
          <span className="plan-nav-body">
            <span className="plan-nav-main">
              <span className="plan-nav-head">
                <span className="plan-nav-name">{row.title}</span>
                {badge(row)}
              </span>
              <span
                className="plan-nav-summary"
                id={`${uid}-${row.key}-summary`}
                title={row.summary}
              >
                {row.summary}
              </span>
            </span>
            <NavGlyph name="chevron" size={14} strokeWidth={2.4} className="plan-nav-chevron" />
          </span>
        </button>
      </li>
    );
  };

  // Assumptions are model settings, not the user's data: one control that
  // reads like a settings panel, with each value on its own line.
  const renderAssumptions = (row: NavRow) => {
    const active = row.key === activeKey;
    return (
      <li key={row.key}>
        <button
          type="button"
          className={`plan-nav-item plan-nav-settings${active ? " is-active" : ""}`}
          onClick={() => onEdit(row.key)}
          aria-label={`Edit ${row.title}${row.essential ? "" : ", optional"}`}
          aria-describedby={`${uid}-${row.key}-summary`}
          aria-current={active ? "true" : undefined}
        >
          {assumptions.map((a) => (
            <span className="plan-nav-setting" key={a.type}>
              <span className="plan-nav-tile is-assumptions" aria-hidden="true">
                <NavGlyph name={a.type} />
              </span>
              <span className="plan-nav-body">
                <span className="plan-nav-name">{a.label}</span>
                <span
                  className={`plan-nav-value is-${a.source}`}
                  title={a.source === "default" ? `${a.label}: CoastMath default` : undefined}
                >
                  {a.value}
                </span>
                <NavGlyph name="chevron" size={14} strokeWidth={2.4} className="plan-nav-chevron" />
              </span>
            </span>
          ))}
          <span className="plan-nav-sr" id={`${uid}-${row.key}-summary`}>
            {row.summary}
          </span>
        </button>
      </li>
    );
  };

  const renderGroup = (category: (typeof CATEGORIES)[number]) => {
    const groupRows = visible.filter((row) => row.category === category.key);
    if (groupRows.length === 0) return null;
    const headingId = `${uid}-${category.key}-heading`;
    const listId = `${uid}-${category.key}-list`;
    let content: ReactNode;
    let more: ReactNode = null;
    if (category.key === "assumptions") {
      content = groupRows.map(renderAssumptions);
    } else if (category.key === "optional" && !filtering) {
      // Sections in use (and the open one) stay in view; the rest wait behind "Show more".
      const primary = groupRows.filter((row) => !row.empty || row.key === activeKey);
      const extra = groupRows.filter((row) => row.empty && row.key !== activeKey);
      content = (showAll ? [...primary, ...extra] : primary).map(renderRow);
      if (extra.length > 0) {
        more = (
          <li key="more">
            <button
              type="button"
              className={`plan-nav-item plan-nav-more${showAll ? " is-open" : ""}`}
              onClick={() => setShowAll((open) => !open)}
              aria-expanded={showAll}
              aria-controls={listId}
              aria-label={
                showAll
                  ? "Show fewer optional sections"
                  : `Show ${extra.length} more optional sections`
              }
            >
              <span className="plan-nav-tile is-spacer" aria-hidden="true" />
              <span className="plan-nav-body">
                <span className="plan-nav-more-label">
                  {showAll ? "Show fewer" : `Show ${extra.length} more`}
                </span>
                <span className="plan-nav-trail">
                  {!showAll && <span className="plan-nav-more-hint">Not set up</span>}
                  <NavGlyph
                    name="chevron"
                    size={14}
                    strokeWidth={2.4}
                    className="plan-nav-chevron"
                  />
                </span>
              </span>
            </button>
          </li>
        );
      }
    } else {
      content = groupRows.map(renderRow);
    }
    return (
      <section
        key={category.key}
        className={`plan-nav-group is-${category.key}`}
        aria-labelledby={headingId}
      >
        <div className="plan-nav-group-head">
          <h3 className="plan-nav-group-title" id={headingId}>
            {category.title}
          </h3>
          {category.key === "essentials" && !filtering && (
            <span className="plan-nav-group-meta">
              {essentialsDone === essentials.length
                ? "All set"
                : `${essentialsDone} of ${essentials.length} set`}
            </span>
          )}
        </div>
        <ul className="plan-nav-card" id={listId} role="list">
          {content}
          {more}
        </ul>
        {!filtering && <p className="plan-nav-footer">{category.footer}</p>}
      </section>
    );
  };

  const matchCount = visible.length;

  return (
    <nav className="plan-nav" aria-label="Plan sections" ref={navRef} onKeyDown={onNavKeyDown}>
      <div className="plan-nav-filter" data-sample-view>
        <label className="plan-nav-sr" htmlFor={`${uid}-filter`}>
          Filter plan sections
        </label>
        <span className="plan-nav-filter-glyph" aria-hidden="true">
          <NavGlyph name="search" size={15} />
        </span>
        <input
          ref={filterRef}
          id={`${uid}-filter`}
          className="plan-nav-filter-input"
          type="search"
          placeholder="Filter sections"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onFilterKeyDown}
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="go"
          aria-keyshortcuts="Meta+K Control+K /"
        />
        {query ? (
          <button
            type="button"
            className="btn-ghost plan-nav-filter-clear"
            aria-label="Clear filter"
            onClick={clearFilter}
          >
            <NavGlyph name="close" size={14} strokeWidth={2.4} />
          </button>
        ) : (
          <kbd className="plan-nav-kbd" aria-hidden="true">
            /
          </kbd>
        )}
      </div>

      {CATEGORIES.map(renderGroup)}

      {filtering && matchCount === 0 && (
        <div className="plan-nav-empty">
          <p>No sections match “{query.trim()}”.</p>
          <button type="button" className="btn-ghost plan-nav-empty-clear" onClick={clearFilter}>
            Show all sections
          </button>
        </div>
      )}
      <p className="plan-nav-sr" role="status">
        {filtering
          ? matchCount
            ? `${matchCount} ${matchCount === 1 ? "section matches" : "sections match"}`
            : "No sections match"
          : ""}
      </p>
    </nav>
  );
}
