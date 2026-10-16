import { render } from "@testing-library/react";
import HelpPage from "./help_page";
import { loadArticle } from "./help_articles";
import { articlePath, getArticleMeta, movedArticles, movedSections } from "./help_catalog";
import { redirectPaths } from "./help_prerender";

const ESTATE = "estate-tax-and-net-estate";

describe("renamed help links", () => {
  it("sends each retired slug's path to its current article", () => {
    expect(redirectPaths()).toMatchObject({
      "/help/estate-tax-and-net-legacy": "/help/estate-tax-and-net-estate",
    });
    for (const [from, to] of movedArticles) {
      expect(getArticleMeta(from), `${from} is still a catalog slug`).toBeUndefined();
      expect(getArticleMeta(to), `${from} moves to unknown ${to}`).toBeDefined();
    }
  });

  it("maps each old section id to a section its current article has", async () => {
    for (const [key, id] of movedSections) {
      const [slug, old] = key.split("#");
      const ids = (await loadArticle(slug))!.sections.map((s) => s.id);
      expect(ids, `${key} moves to missing #${id}`).toContain(id);
      expect(ids, `${key} is still a section id`).not.toContain(old);
    }
  });

  it("lands an old section anchor on the renamed section", async () => {
    const article = (await loadArticle(ESTATE))!;
    const scrollIntoView = Element.prototype.scrollIntoView;
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.history.replaceState(
      null,
      "",
      `${articlePath(ESTATE)}?from=app#reading-the-legacy-card`,
    );
    try {
      render(<HelpPage slug={ESTATE} article={article} />);
      const { pathname, search, hash } = window.location;
      expect(pathname + search + hash).toBe(
        `${articlePath(ESTATE)}?from=app#reading-the-estate-card`,
      );
      expect(scroll.mock.contexts).toEqual([document.getElementById("reading-the-estate-card")]);
    } finally {
      Element.prototype.scrollIntoView = scrollIntoView;
      window.history.replaceState(null, "", "/");
    }
  });
});
