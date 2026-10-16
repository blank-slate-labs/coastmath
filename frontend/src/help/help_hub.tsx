/* The hub: "Calm Topic Cards". A centered hero with one search field and five popular starter
   articles, then eleven uniform topic cards (icon, one-line description, three featured
   links and a "See all" toggle that expands the card in place). The plan year sits below as a quiet
   eight-step timeline whose steps filter to their articles in a panel under it. Searching swaps the
   cards for one results panel. Collapsed links stay in the server-rendered HTML, marked `hidden`. */
import { useId, useMemo, useRef, useState, type ReactNode } from "react";
import help from "@extensions/help";
import {
  articlePath,
  articles,
  articlesIn,
  getSection,
  kindLabels,
  sections,
  stages,
} from "./help_catalog";
import { search } from "./help_search";
import type { ArticleMeta, Section, SectionId, StageId } from "./help_types";
import {
  Footer,
  SearchIcon,
  SearchPalette,
  TopBar,
  usePalette,
  useSearchBodies,
} from "./help_chrome";

/** Hand-picked starter articles under the hero search, with short link labels. */
export const POPULAR: { slug: string; label: string }[] = [
  { slug: "build-your-first-plan", label: "Build your first plan" },
  { slug: "how-a-plan-year-is-calculated", label: "How a plan year is calculated" },
  { slug: "withdrawal-order", label: "How shortfalls are funded" },
  { slug: "todays-and-future-dollars", label: "Today’s and future dollars" },
  { slug: "unexpected-withdrawals", label: "Unexpected withdrawals" },
];

/** How many links a collapsed card shows. */
export const FEATURED_COUNT = 3;

interface TopicGuide {
  blurb: string;
  featured: string[];
  icon: ReactNode;
}

/** Per section: a one-sentence description, its most useful articles first, and a 24px line icon. */
const TOPICS: Record<SectionId, TopicGuide> = {
  start: {
    blurb: "Set up a first plan and see how each projected year is built.",
    featured: [
      "build-your-first-plan",
      "how-a-plan-year-is-calculated",
      "todays-and-future-dollars",
    ],
    icon: (
      <>
        <path d="M5 21V4" />
        <path d="M5 4h12l-2.5 4L17 12H5" />
      </>
    ),
  },
  income: {
    blurb: "Wages, self-employment, Social Security, pensions and payroll deductions.",
    featured: ["social-security", "wages-and-raises", "pensions-and-other-income"],
    icon: (
      <>
        <rect x="2.5" y="6" width="19" height="12" rx="2" />
        <circle cx="12" cy="12" r="2.5" />
        <path d="M6 9.5v5M18 9.5v5" />
      </>
    ),
  },
  spending: {
    blurb: "Expenses, spending rules, health coverage, medical costs and giving.",
    featured: ["expenses", "flexible-spending", "medicare-and-irmaa"],
    icon: (
      <>
        <path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z" />
        <path d="M9 8h6M9 12h6M9 16h3" />
      </>
    ),
  },
  accounts: {
    blurb: "Account types, opening balances, contributions and where surplus is saved.",
    featured: ["account-types", "contributions-and-employer-match", "savings-rules"],
    icon: (
      <>
        <path d="M3 9.5 12 4l9 5.5" />
        <path d="M5.5 10v8M10 10v8M14 10v8M18.5 10v8" />
        <path d="M3 20h18" />
      </>
    ),
  },
  withdrawals: {
    blurb: "How shortfalls are funded, penalties, RMDs, 72(t) and inherited accounts.",
    featured: ["withdrawal-order", "unexpected-withdrawals", "required-minimum-distributions"],
    icon: (
      <>
        <path d="M4 14v6h16v-6" />
        <path d="M12 3v11" />
        <path d="m7.5 9.5 4.5 4.5 4.5-4.5" />
      </>
    ),
  },
  taxes: {
    blurb: "Federal, state and investment taxes, deductions, conversions and estate tax.",
    featured: ["how-taxes-are-calculated", "roth-conversions", "tax-payments-and-settlement"],
    icon: (
      <>
        <circle cx="7" cy="7" r="2.5" />
        <circle cx="17" cy="17" r="2.5" />
        <path d="M19 5 5 19" />
      </>
    ),
  },
  property: {
    blurb: "Homes and other real assets, selling them, and the loans against them.",
    featured: ["homes-and-real-assets", "selling-a-home", "mortgages-and-loans"],
    icon: (
      <>
        <path d="m3 11 9-7 9 7" />
        <path d="M5.5 9.5V20h13V9.5" />
        <path d="M10 20v-5.5h4V20" />
      </>
    ),
  },
  life: {
    blurb: "Milestones, couples, a partner’s death, moves and the independence estimate.",
    featured: ["milestones", "household-and-partner", "financial-independence-estimate"],
    icon: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M3 10h18M8 3v4M16 3v4" />
        <path d="m9.5 15 2 2 3.5-3.5" />
      </>
    ),
  },
  analysis: {
    blurb: "Market and inflation assumptions, growth, success odds and comparisons.",
    featured: [
      "chance-of-success",
      "market-and-inflation-assumptions",
      "plan-vs-chance-of-success",
    ],
    icon: (
      <>
        <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
        <circle cx="15" cy="7" r="2" />
        <circle cx="9" cy="17" r="2" />
      </>
    ),
  },
  results: {
    blurb: "Read the overview, cash flow and tax views, shortfalls and reports.",
    featured: ["overview-and-net-worth", "cash-flow-view", "unfunded-expenses"],
    icon: (
      <>
        <path d="M3 20h18" />
        <path d="M6 20v-8M11 20V5M16 20v-6M20 20V9" />
      </>
    ),
  },
  support: {
    blurb: "Saving changes, conflicts and results that didn’t update.",
    featured: ["saves-and-refresh"],
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="3.5" />
        <path d="m5.6 5.6 3.9 3.9M14.5 14.5l3.9 3.9M18.4 5.6l-3.9 3.9M9.5 14.5l-3.9 3.9" />
      </>
    ),
  },
};

/** The topics with a hosting package's blurbs and featured articles. */
export const TOPIC_GUIDE = Object.fromEntries(
  Object.entries(TOPICS).map(([id, guide]) => [
    id,
    { ...guide, ...help.topics?.[id as SectionId] },
  ]),
) as Record<SectionId, TopicGuide>;

/** A section's articles with its featured ones first, then the rest in catalog order. */
export function orderedArticles(id: SectionId): ArticleMeta[] {
  const list = articlesIn(id);
  const featured = TOPIC_GUIDE[id].featured
    .map((slug) => list.find((meta) => meta.slug === slug))
    .filter((meta): meta is ArticleMeta => !!meta);
  return [...featured, ...list.filter((meta) => !featured.includes(meta))];
}

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

export function Hub() {
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState<StageId | null>(null);
  const palette = usePalette();
  const field = useRef<HTMLInputElement>(null);
  const trimmed = query.trim();
  const searching = trimmed.length > 0;
  const bodies = useSearchBodies(searching);
  const results = useMemo(() => search(query, bodies, 40), [query, bodies]);
  const counts = useMemo(
    () =>
      Object.fromEntries(
        stages.map((s) => [s.id, articles.filter((a) => a.stages.includes(s.id)).length]),
      ) as Record<StageId, number>,
    [],
  );
  const selected = stages.find((s) => s.id === stage);
  const inStage = (meta: ArticleMeta) => !stage || meta.stages.includes(stage);
  const shown = searching ? results.filter(inStage) : articles.filter(inStage);
  const reset = () => {
    setStage(null);
    setQuery("");
  };
  const clearSearch = () => {
    setQuery("");
    field.current?.focus();
  };

  const status = searching
    ? `${plural(shown.length, "article")} for “${trimmed}”${selected ? ` in ${selected.name}` : ""}`
    : selected
      ? `${plural(shown.length, "article")} about ${selected.name.toLowerCase()}`
      : "";

  return (
    <>
      <TopBar onSearch={palette.show} />
      <main id="help_main" className="help-shell help-hub">
        <header className="help-hero">
          <h1>How CoastMath works</h1>
          <form
            className="help-hero-search"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              if (shown[0] && searching) window.location.assign(articlePath(shown[0].slug));
            }}
          >
            <SearchIcon />
            <label className="help-visually-hidden" htmlFor="help_query">
              Search help
            </label>
            <input
              ref={field}
              id="help_query"
              type="search"
              value={query}
              autoComplete="off"
              spellCheck={false}
              placeholder="Search, e.g. withdrawals before I retire"
              onChange={(event) => setQuery(event.target.value)}
            />
          </form>
          <nav className="help-popular" aria-labelledby="help_popular_label">
            <p id="help_popular_label">Popular</p>
            <ul>
              {POPULAR.map((item) => (
                <li key={item.slug}>
                  <a href={articlePath(item.slug)}>{item.label}</a>
                </li>
              ))}
            </ul>
          </nav>
        </header>

        {searching ? (
          <ResultsPanel
            heading={`Results for “${trimmed}”`}
            note={selected ? `Only articles about ${selected.name.toLowerCase()}` : undefined}
            list={shown}
            resetLabel="Clear search"
            onReset={clearSearch}
            empty={`No articles match “${trimmed}”${selected ? ` in ${selected.name}` : ""}. Try a shorter phrase or the name of a plan section.`}
          />
        ) : (
          <section className="help-topics" aria-labelledby="help_topics_heading">
            <h2 id="help_topics_heading" className="help-band-heading">
              Browse by topic
            </h2>
            <ul className="help-cards">
              {sections.map((section) => (
                <li key={section.id}>
                  <TopicCard section={section} />
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="help-year" aria-labelledby="help_year_heading">
          <div className="help-year-head">
            <h2 id="help_year_heading" className="help-band-heading">
              How CoastMath calculates a year
            </h2>
            <p>
              Every projected year runs these eight steps in order. Choose one to list its articles.
            </p>
          </div>
          <ol className="help-steps" aria-labelledby="help_year_heading">
            {stages.map((item, index) => {
              const on = stage === item.id;
              return (
                <li key={item.id} className="help-step-item">
                  <button
                    type="button"
                    className="help-step"
                    aria-pressed={on}
                    onClick={() => setStage((current) => (current === item.id ? null : item.id))}
                    aria-label={`${item.name}: ${item.summary} ${counts[item.id]} articles.`}
                  >
                    <span className="help-step-dot" aria-hidden="true">
                      {index + 1}
                    </span>
                    <span className="help-step-text" aria-hidden="true">
                      <span className="help-step-name">{item.name}</span>
                      <span className="help-step-count">{plural(counts[item.id], "article")}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          {!searching && selected && (
            <ResultsPanel
              heading={`Articles about ${selected.name.toLowerCase()}`}
              note={selected.summary}
              list={shown}
              resetLabel="Clear step"
              onReset={reset}
              empty="No articles cover this step yet."
            />
          )}
        </section>
        <p className="help-visually-hidden" role="status">
          {status}
        </p>
      </main>
      <Footer />
      <SearchPalette open={palette.open} onClose={palette.close} />
    </>
  );
}

function TopicCard({ section }: { section: Section }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const guide = TOPIC_GUIDE[section.id];
  const list = orderedArticles(section.id);
  const headingId = `help_topic_${section.id}`;
  const more = list.length > FEATURED_COUNT;
  return (
    <article className="help-card" id={`section-${section.id}`} aria-labelledby={headingId}>
      <div className="help-card-head">
        <svg className="help-card-icon" viewBox="0 0 24 24" aria-hidden="true">
          {guide.icon}
        </svg>
      </div>
      <h3 id={headingId}>{section.title}</h3>
      <p className="help-card-blurb">{guide.blurb}</p>
      <ul id={listId} className="help-card-list" aria-labelledby={headingId}>
        {list.map((meta, index) => (
          <li key={meta.slug} hidden={!open && index >= FEATURED_COUNT}>
            <a href={articlePath(meta.slug)}>{meta.title}</a>
          </li>
        ))}
      </ul>
      {more && (
        <button
          type="button"
          className="help-card-toggle"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Show fewer" : `See all ${list.length}`}
          <span className="help-visually-hidden"> {section.title} articles</span>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="m4 6 4 4 4-4" />
          </svg>
        </button>
      )}
    </article>
  );
}

function ResultsPanel({
  heading,
  note,
  list,
  empty,
  resetLabel,
  onReset,
}: {
  heading: string;
  note?: string;
  list: ArticleMeta[];
  empty: string;
  resetLabel: string;
  onReset: () => void;
}) {
  return (
    <section className="help-results" aria-labelledby="help_results_heading">
      <div className="help-results-head">
        <div className="help-results-text">
          <h2 id="help_results_heading">{heading}</h2>
          <p className="help-results-note">
            {note ? `${note} · ` : ""}
            {plural(list.length, "article")}
          </p>
        </div>
        <button type="button" className="help-reset" onClick={onReset}>
          {resetLabel}
        </button>
      </div>
      {list.length ? (
        <ul className="help-results-list">
          {list.map((meta) => (
            <li key={meta.slug}>
              <a href={articlePath(meta.slug)}>
                <span className="help-row-title">{meta.title}</span>
                <span className="help-row-dek">{meta.dek}</span>
                <span className="help-row-meta">
                  {getSection(meta.section).title} · {kindLabels[meta.kind]}
                </span>
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="help-empty">{empty}</p>
      )}
    </section>
  );
}
