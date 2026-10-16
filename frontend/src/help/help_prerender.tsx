import { StrictMode } from "react";
import { renderToStaticMarkup, renderToString } from "react-dom/server";
import HelpPage, { pageTitle } from "./help_page";
import { loadArticle } from "./help_articles";
import {
  HELP_ROOT,
  articlePath,
  articles,
  getArticleMeta,
  getSection,
  moduleName,
  movedArticles,
  sections,
} from "./help_catalog";
import { contentViolations, helpContent } from "./help_content_rules";
import { normalize, type SearchBody } from "./help_search";
import type { Article } from "./help_types";

const HUB_DESCRIPTION =
  "How CoastMath projects your plan year by year: income, spending, accounts, withdrawals, taxes and results.";

/** Every catalog article's module, by slug; a missing module fails the build. */
export async function loadArticles(): Promise<Map<string, Article>> {
  const loaded = await Promise.all(
    articles.map(async (meta) => [meta.slug, await loadArticle(meta.slug)] as const),
  );
  const missing = loaded.filter(([, article]) => !article).map(([slug]) => slug);
  if (missing.length) throw new Error(`Help articles missing modules: ${missing.join(", ")}`);
  return new Map(loaded as (readonly [string, Article])[]);
}

/** Old article path to current, for the server's redirects; a move that doesn't retire a slug for a
    catalog article fails the build. */
export function redirectPaths(): Record<string, string> {
  const broken = [...movedArticles]
    .filter(([from, to]) => getArticleMeta(from) || !getArticleMeta(to))
    .map(([from, to]) => `${from} → ${to}`);
  if (broken.length) throw new Error(`Help redirects are broken: ${broken.join(", ")}`);
  return Object.fromEntries(
    [...movedArticles].map(([from, to]) => [articlePath(from), articlePath(to)]),
  );
}

/** No rendered page's help content may cite sources or name internals. */
export function renderPages(modules: Map<string, Article>, origin = "") {
  const moduleFor = (slug: string) => modules.get(slug)!;
  const pages = [
    {
      path: HELP_ROOT,
      file: "help/index.html",
      title: pageTitle(),
      description: HUB_DESCRIPTION,
      html: renderToString(
        <StrictMode>
          <HelpPage />
        </StrictMode>,
      ),
      schema: {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        name: "CoastMath Help",
        description: HUB_DESCRIPTION,
        hasPart: sections.map((section) => ({
          "@type": "ItemList",
          name: section.title,
          itemListElement: articles
            .filter((a) => a.section === section.id)
            .map((a, index) => ({
              "@type": "ListItem",
              position: index + 1,
              name: a.title,
              url: origin + articlePath(a.slug),
            })),
        })),
      },
    },
    ...articles.map((meta) => ({
      path: articlePath(meta.slug),
      file: `help/${moduleName(meta.slug)}.html`,
      title: pageTitle(meta),
      description: meta.dek,
      html: renderToString(
        <StrictMode>
          <HelpPage slug={meta.slug} article={moduleFor(meta.slug)} />
        </StrictMode>,
      ),
      schema: {
        "@context": "https://schema.org",
        "@type": "TechArticle",
        headline: meta.title,
        description: meta.dek,
        dateModified: meta.updated,
        articleSection: getSection(meta.section).title,
        inLanguage: "en-US",
        publisher: { "@type": "Organization", name: "CoastMath" },
        breadcrumb: {
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", position: 1, name: "Help", item: origin + HELP_ROOT },
            {
              "@type": "ListItem",
              position: 2,
              name: meta.title,
              item: origin + articlePath(meta.slug),
            },
          ],
        },
      },
    })),
  ];
  for (const page of pages) {
    const problems = contentViolations(helpContent(page.html));
    if (problems.length) throw new Error(`Help page ${page.path} contains ${problems.join("; ")}`);
  }
  return pages;
}

const decode = (text: string) =>
  text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'");

/** Headings plus each article's distinct words: enough to match queries without shipping the prose twice. */
export function searchBodies(modules: Map<string, Article>): SearchBody[] {
  return articles.map((meta) => {
    const article = modules.get(meta.slug)!;
    const html = renderToStaticMarkup(
      <>
        {article.intro}
        {article.sections.map((s) => (
          <div key={s.id}>
            {s.title} {s.body}
          </div>
        ))}
      </>,
    );
    const words = new Set(
      normalize(decode(html.replace(/<[^>]+>/g, " ")))
        .split(" ")
        .filter((word) => word.length > 2),
    );
    return {
      slug: meta.slug,
      headings: article.sections.map((s) => s.title),
      text: [...words].join(" "),
    };
  });
}
