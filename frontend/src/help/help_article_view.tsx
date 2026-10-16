/* An article as a bento: a navy title tile beside a tile that places the article in the plan year,
   then a white reading tile with a sticky contents tile, related tiles and a blue "next" tile. */
import { useEffect, useMemo, useState } from "react";
import {
  HELP_ROOT,
  articlePath,
  articlesIn,
  getArticleMeta,
  getSection,
  kindLabels,
  movedSections,
  stages,
} from "./help_catalog";
import type { Article, ArticleMeta, Section, StageId } from "./help_types";
import { ArrowIcon, Footer, SearchPalette, TopBar, usePalette } from "./help_chrome";
import { MONTH_NAMES } from "@/domain/months";

const longDate = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTH_NAMES[m - 1]} ${d}, ${y}`;
};
const pad = (n: number) => String(n).padStart(2, "0");

/** Numbers sit outside the links so each link's name is exactly its section title. */
function Toc({
  items,
  activeId,
}: {
  items: { id: string; title: string }[];
  activeId: string | null;
}) {
  return (
    <ol className="help-toc-list">
      {items.map((item, index) => (
        <li key={item.id} className={activeId === item.id ? "is-active" : undefined}>
          <span className="help-toc-num" aria-hidden="true">
            {pad(index + 1)}
          </span>
          <a href={`#${item.id}`} aria-current={activeId === item.id ? "location" : undefined}>
            {item.title}
          </a>
        </li>
      ))}
    </ol>
  );
}

/** The last section whose heading has scrolled near the top of the viewport is the current one. */
function useActiveSection(ids: string[]) {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    if (!ids.length) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      let current: string | null = null;
      for (const id of ids) {
        const element = document.getElementById(id);
        if (element && element.getBoundingClientRect().top <= 120) current = id;
      }
      setActive(current ?? ids[0]);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ids]);
  return active;
}

/** A shipped link to a renamed section's old id lands on that section under its new id. */
function useMovedSectionAnchor(slug: string, article: Article | null) {
  useEffect(() => {
    const id = article && movedSections.get(slug + window.location.hash);
    if (!id) return;
    history.replaceState(history.state, "", `#${id}`);
    document.getElementById(id)?.scrollIntoView?.();
  }, [slug, article]);
}

/** Eight small blocks, filled where the article's behavior happens. */
function StageLocator({ ids }: { ids: StageId[] }) {
  return (
    <div className="help-tile help-locator">
      <p className="help-tile-label">Where this happens in a plan year</p>
      <p className="help-locator-total">
        <span className="help-locator-num">{ids.length}</span>
        <span>of {stages.length} stages</span>
      </p>
      <ol className="help-locator-grid">
        {stages.map((stage, index) => {
          const on = ids.includes(stage.id);
          return (
            <li key={stage.id} className={on ? "is-on" : undefined}>
              <span className="help-locator-order" aria-hidden="true">
                {index + 1}
              </span>
              <span className="help-locator-name">{stage.name}</span>
              {on && <span className="help-visually-hidden"> (covered)</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Account and setup articles aren't tied to a stage; their side tile places them in their section. */
function SectionPlace({
  section,
  position,
  total,
}: {
  section: Section;
  position: number;
  total: number;
}) {
  return (
    <div className="help-tile help-locator is-place">
      <p className="help-tile-label">In this section</p>
      <p className="help-locator-total">
        <span className="help-locator-num">{position}</span>
        <span>of {total} articles</span>
      </p>
      <p className="help-locator-section">
        <a href={`${HELP_ROOT}#section-${section.id}`}>{section.title}</a>
      </p>
    </div>
  );
}

export function ArticleView({ meta, article }: { meta: ArticleMeta; article: Article | null }) {
  const palette = usePalette();
  const section = getSection(meta.section);
  const ids = useMemo(() => article?.sections.map((s) => s.id) ?? [], [article]);
  const active = useActiveSection(ids);
  useMovedSectionAnchor(meta.slug, article);
  const related = meta.related.map(getArticleMeta).filter((m): m is ArticleMeta => !!m);
  const siblings = articlesIn(meta.section);
  const position = siblings.findIndex((item) => item.slug === meta.slug);
  const next = siblings[position + 1];
  const toc = article ? article.sections.map((s) => ({ id: s.id, title: s.title })) : [];
  const hasToc = toc.length > 1;

  return (
    <>
      <TopBar onSearch={palette.show} />
      <main id="help_main" className="help-shell help-grid help-article">
        <nav className="help-crumbs" aria-label="Breadcrumb">
          <ol>
            <li>
              <a href={HELP_ROOT}>Help</a>
            </li>
            <li>
              <a href={`${HELP_ROOT}#section-${section.id}`}>{section.title}</a>
            </li>
          </ol>
        </nav>
        <header className="help-tile is-navy help-title-tile">
          <p className="help-chips">
            <span className="help-chip">{kindLabels[meta.kind]}</span>
            {meta.figuresYear ? (
              <span className="help-chip is-light">{meta.figuresYear} figures</span>
            ) : null}
          </p>
          <h1>{meta.title}</h1>
          <p className="help-title-dek">{meta.dek}</p>
          <p className="help-title-updated">
            Updated <time dateTime={meta.updated}>{longDate(meta.updated)}</time>
          </p>
        </header>
        {meta.stages.length > 0 ? (
          <StageLocator ids={meta.stages} />
        ) : (
          <SectionPlace section={section} position={position + 1} total={siblings.length} />
        )}
        <article className={`help-tile help-reading${hasToc ? "" : " is-full"}`}>
          {hasToc && (
            <details className="help-toc-fold">
              <summary>On this page</summary>
              <Toc items={toc} activeId={active} />
            </details>
          )}
          {article ? (
            <>
              <div className="help-prose help-intro">{article.intro}</div>
              {article.sections.map((s, index) => (
                <section
                  key={s.id}
                  id={s.id}
                  className="help-prose help-part"
                  aria-labelledby={`${s.id}_heading`}
                >
                  <div className="help-part-head">
                    <span className="help-part-num" aria-hidden="true">
                      {pad(index + 1)}
                    </span>
                    <h2 id={`${s.id}_heading`}>
                      <a className="help-heading-link" href={`#${s.id}`}>
                        {s.title}
                      </a>
                    </h2>
                  </div>
                  {s.body}
                </section>
              ))}
            </>
          ) : (
            <p className="help-loading" role="status">
              Loading article…
            </p>
          )}
        </article>
        {hasToc && (
          <div className="help-tile help-toc-tile">
            <nav aria-label="On this page">
              <p className="help-tile-label" aria-hidden="true">
                On this page
              </p>
              <Toc items={toc} activeId={active} />
            </nav>
          </div>
        )}
        {related.length > 0 && (
          <nav className="help-related" aria-labelledby="help_related_heading">
            <h2 id="help_related_heading">Related</h2>
            <ul>
              {related.map((item) => (
                <li key={item.slug}>
                  <a className="help-tile help-related-tile" href={articlePath(item.slug)}>
                    <span className="help-related-kind">{kindLabels[item.kind]}</span>
                    <span className="help-related-title">{item.title}</span>
                    <span className="help-related-dek">{item.dek}</span>
                    <ArrowIcon className="help-related-arrow" />
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        )}
        {next && (
          <a className="help-tile is-blue help-next" href={articlePath(next.slug)}>
            <span className="help-next-label">Next in {section.title}</span>
            <span className="help-next-title">{next.title}</span>
            <ArrowIcon className="help-next-arrow" />
          </a>
        )}
      </main>
      <Footer />
      <SearchPalette open={palette.open} onClose={palette.close} />
    </>
  );
}

export function NotFound() {
  const palette = usePalette();
  return (
    <>
      <TopBar onSearch={palette.show} />
      <main id="help_main" className="help-shell help-grid help-missing">
        <div className="help-tile is-navy help-missing-tile">
          <h1>Article not found</h1>
          <p>This address doesn’t match a help article.</p>
          <div className="help-missing-actions">
            <a className="help-button is-light" href={HELP_ROOT}>
              Browse all articles
            </a>
            <button
              type="button"
              className="help-button is-chip"
              onClick={palette.show}
              aria-haspopup="dialog"
            >
              Search articles
            </button>
          </div>
        </div>
        <div className="help-tile is-blue help-missing-code" aria-hidden="true">
          404
        </div>
      </main>
      <Footer />
      <SearchPalette open={palette.open} onClose={palette.close} />
    </>
  );
}
