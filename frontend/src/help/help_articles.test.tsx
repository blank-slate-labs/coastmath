import { renderToStaticMarkup } from "react-dom/server";
import HelpPage from "./help_page";
import { articleModuleSlugs, loadArticle } from "./help_articles";
import { articlePath, getArticleMeta } from "./help_catalog";
import { contentViolations, helpContent } from "./help_content_rules";
import type { Article } from "./help_types";

// Gated articles (Transactions) are checked like every other article.
vi.hoisted(() => {
  vi.stubEnv("VITE_TRANSACTIONS_ENABLED", "true");
});

/* One describe block per article module (this directory's and a hosting package's), each importing
   only its own module, so an article in progress fails its own checks without hiding the others. Run
   one with -t "<slug>". */
const slugs = articleModuleSlugs().sort();
const load = async (slug: string) => (await loadArticle(slug)) ?? undefined;

it("discovers article modules", () => expect(slugs.length).toBeGreaterThan(0));

describe.each(slugs.map((slug) => ({ slug })))("$slug", ({ slug }) => {
  let article: Article;
  let html: string;
  beforeAll(async () => {
    article = (await loadArticle(slug))!;
    html = renderToStaticMarkup(<HelpPage slug={slug} article={article} />);
  });

  it("is listed in the catalog under the same slug", () => {
    expect(getArticleMeta(slug), `${slug} has no catalog entry`).toBeDefined();
  });

  it("renders an intro and at least two sections with unique kebab-case ids", () => {
    expect(
      renderToStaticMarkup(<>{article.intro}</>)
        .replace(/<[^>]+>/g, "")
        .trim().length,
    ).toBeGreaterThan(40);
    expect(article.sections.length).toBeGreaterThanOrEqual(2);
    const ids = article.sections.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
    for (const s of article.sections) expect(s.title.trim().length).toBeGreaterThan(2);
  });

  it("leaves the page title as the only h1", () => {
    expect(html.match(/<h1[\s>]/g)).toHaveLength(1);
  });

  it("never publishes citations, external links or implementation references", () => {
    expect(contentViolations(helpContent(html))).toEqual([]);
  });

  it("links only to catalog articles and to sections that exist", async () => {
    const targets = [...html.matchAll(/href="\/help\/([a-z0-9-]+)(?:#([a-z0-9-]+))?"/g)];
    for (const [, target, anchor] of targets) {
      expect(getArticleMeta(target), `link to unknown article ${target}`).toBeDefined();
      if (!anchor) continue;
      const linked = target === slug ? article : await load(target).catch(() => undefined);
      // A target still being written is checked once it exists; the catalog test requires it.
      if (linked)
        expect(
          linked.sections.map((s) => s.id),
          `missing #${anchor} in ${target}`,
        ).toContain(anchor);
    }
    for (const [, anchor] of html.matchAll(/href="#([a-z0-9-]+)"/g)) {
      expect(html.includes(`id="${anchor}"`), `missing in-page anchor #${anchor}`).toBe(true);
    }
    expect(articlePath(slug)).toBe(`/help/${slug}`);
  });
});
