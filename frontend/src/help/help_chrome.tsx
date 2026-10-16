/* Shared chrome for every help page: the minimal top row, the footer and the search palette that
   `/` and ⌘K open from anywhere. */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import help from "@extensions/help";
import { HELP_ROOT, articlePath, getSection, kindLabels } from "./help_catalog";
import { loadSearchBodies, search, type SearchBody } from "./help_search";
import { BrandMark } from "@/components/brand_mark";
import type { ArticleMeta } from "./help_types";

export function Brand() {
  return (
    <a className="help-brand" href="/" aria-label="CoastMath home">
      <BrandMark />
      <span>CoastMath</span>
    </a>
  );
}

export const SearchIcon = () => (
  <svg className="help-search-icon" viewBox="0 0 20 20" aria-hidden="true">
    <circle cx="8.5" cy="8.5" r="5.5" />
    <path d="m13 13 4.5 4.5" />
  </svg>
);
export const ArrowIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 12h15m-6-6.5L19.5 12 13 18.5" />
  </svg>
);

export function TopBar({ onSearch }: { onSearch: () => void }) {
  return (
    <header className="help-top">
      <div className="help-shell help-top-inner">
        <div className="help-top-brand">
          <Brand />
          <a className="help-top-section" href={HELP_ROOT}>
            Help
          </a>
        </div>
        <nav className="help-top-nav" aria-label="Help navigation">
          <button
            type="button"
            className="help-top-search"
            onClick={onSearch}
            aria-haspopup="dialog"
          >
            <SearchIcon />
            <span className="help-top-search-text">Search</span>
            <kbd aria-hidden="true">/</kbd>
          </button>
          <a className="help-top-cta" href={help.plannerPath ?? "/"}>
            Open planner
          </a>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="help-footer">
      <div className="help-shell help-footer-inner">
        <Brand />
        <nav aria-label="Footer navigation">
          <a href={HELP_ROOT}>Help</a>
          {help.footerLinks?.map((link) =>
            /^https?:\/\//.test(link.href) ? (
              <a key={link.href} href={link.href} target="_blank" rel="noopener noreferrer">
                {link.label}
              </a>
            ) : (
              <a key={link.href} href={link.href}>
                {link.label}
              </a>
            ),
          )}
        </nav>
        <p>
          Projections depend on your inputs and assumptions and do not guarantee future results.
          Help articles describe how CoastMath models your plan; they are not tax, legal or
          investment advice.
        </p>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ search */

export function useSearchBodies(enabled: boolean) {
  const [bodies, setBodies] = useState<Map<string, SearchBody>>(new Map());
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    void loadSearchBodies().then((map) => {
      if (live) setBodies(map);
    });
    return () => {
      live = false;
    };
  }, [enabled]);
  return bodies;
}

/** `/` (outside a text field) or ⌘K / Ctrl+K opens the palette. */
export function useSearchShortcut(open: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if (
        (event.key === "k" && (event.metaKey || event.ctrlKey)) ||
        (event.key === "/" && !typing)
      ) {
        event.preventDefault();
        open();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
}

/** Palette state plus the global shortcut, shared by every page. */
export function usePalette() {
  const [open, setOpen] = useState(false);
  const show = useCallback(() => setOpen(true), []);
  const close = useCallback(() => setOpen(false), []);
  useSearchShortcut(show);
  return { open, show, close };
}

const FOCUSABLE = 'a[href]:not([tabindex="-1"]), button:not([disabled]), input:not([disabled])';

export function SearchPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const bodies = useSearchBodies(open);
  const results = useMemo(() => search(query, bodies, 10), [query, bodies]);
  const listId = useId();
  const optionId = (index: number) => `${listId}_${index}`;
  const active = Math.min(cursor, Math.max(0, results.length - 1));

  // Focus moves in on open and back to the opener on close; the page behind stops scrolling.
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    input.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.classList.add("help-scroll-lock");
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("help-scroll-lock");
      previous?.focus();
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !results.length) return;
    document.getElementById(optionId(active))?.scrollIntoView?.({ block: "nearest" });
  });

  if (!open) return null;

  const onFieldKey = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor(Math.min(results.length - 1, active + 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor(Math.max(0, active - 1));
    }
    if (event.key === "Enter" && results[active]) {
      event.preventDefault();
      window.location.assign(articlePath(results[active].slug));
    }
  };
  // Keep Tab inside the modal panel.
  const onPanelKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || !panel.current) return;
    const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  const trimmed = query.trim();

  return (
    <div
      className="help-palette-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        className="help-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Help search"
        onKeyDown={onPanelKey}
      >
        <div className="help-palette-field">
          <SearchIcon />
          <input
            ref={input}
            type="search"
            value={query}
            placeholder="Search articles"
            aria-label="Search articles"
            autoComplete="off"
            spellCheck={false}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={results.length > 0}
            aria-controls={listId}
            aria-activedescendant={results.length ? optionId(active) : undefined}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(0);
            }}
            onKeyDown={onFieldKey}
          />
          <button type="button" className="help-palette-close" onClick={onClose}>
            Close
          </button>
        </div>
        <div
          className="help-palette-results"
          id={listId}
          role="listbox"
          aria-label="Matching articles"
        >
          {results.map((meta, index) => (
            <PaletteOption
              key={meta.slug}
              meta={meta}
              id={optionId(index)}
              active={index === active}
              onHover={() => setCursor(index)}
            />
          ))}
        </div>
        {trimmed && !results.length && (
          <p className="help-palette-note" role="status">
            No articles match “{trimmed}”.
          </p>
        )}
        {!trimmed && (
          <p className="help-palette-note">
            Type a question, a symptom or a planner label. <kbd>↑</kbd> <kbd>↓</kbd> to move,{" "}
            <kbd>↵</kbd> to open.
          </p>
        )}
      </div>
    </div>
  );
}

function PaletteOption({
  meta,
  id,
  active,
  onHover,
}: {
  meta: ArticleMeta;
  id: string;
  active: boolean;
  onHover: () => void;
}) {
  return (
    <a
      className={`help-palette-option${active ? " is-active" : ""}`}
      href={articlePath(meta.slug)}
      id={id}
      role="option"
      aria-selected={active}
      tabIndex={-1}
      onMouseMove={onHover}
    >
      <span className="help-palette-title">{meta.title}</span>
      <span className="help-palette-meta">
        {getSection(meta.section).title} · {kindLabels[meta.kind]}
      </span>
    </a>
  );
}
