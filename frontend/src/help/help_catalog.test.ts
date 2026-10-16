import { articles, getArticleMeta, sections, stages } from "./help_catalog";
import { hasArticleModule } from "./help_articles";

// Gated articles (Transactions) are checked like every other article.
vi.hoisted(() => {
  vi.stubEnv("VITE_TRANSACTIONS_ENABLED", "true");
});

describe("help catalog", () => {
  it("has unique kebab-case slugs, one-sentence deks and search aliases", () => {
    const slugs = articles.map((a) => a.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
    for (const a of articles) {
      expect(a.slug).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
      expect(a.dek).toMatch(/^[A-Z0-9].*\.$/);
      expect(a.dek.split(/\.\s/).length, `${a.slug} dek has more than one sentence`).toBe(1);
      expect(a.aliases.length).toBeGreaterThan(2);
      expect(a.updated).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it("references real sections, stages and related articles", () => {
    const stageIds = new Set(stages.map((s) => s.id));
    for (const a of articles) {
      expect(sections.some((s) => s.id === a.section)).toBe(true);
      for (const id of a.stages) expect(stageIds.has(id)).toBe(true);
      expect(new Set(a.stages).size).toBe(a.stages.length);
      for (const slug of a.related) {
        expect(getArticleMeta(slug), `${a.slug} relates to unknown ${slug}`).toBeDefined();
        expect(slug).not.toBe(a.slug);
      }
      if (a.kind === "calculation")
        expect(a.stages.length, `${a.slug} needs stages`).toBeGreaterThan(0);
    }
    for (const section of sections)
      expect(articles.some((a) => a.section === section.id)).toBe(true);
  });

  it("has an article module for every entry", () => {
    expect(articles.filter((a) => !hasArticleModule(a.slug)).map((a) => a.slug)).toEqual([]);
  });
});
