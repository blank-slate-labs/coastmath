/* CoastMath Help, "Bento Atlas": every page is a grid of flat tiles on a cool canvas. The hub is a
   bento board (navy hero with search, blue library tile, the plan year as eight operable blocks,
   one tile per section); an article is a bento header over a reading tile. */
import { useEffect, useState, type ReactNode } from "react";
import { loadArticle } from "./help_articles";
import { getArticleMeta } from "./help_catalog";
import type { Article, ArticleMeta } from "./help_types";
import { Hub } from "./help_hub";
import { ArticleView, NotFound } from "./help_article_view";
import "./help_page.css";
import "./help_blocks.css";

export const pageTitle = (meta?: ArticleMeta) =>
  meta ? `${meta.title} | CoastMath Help` : "CoastMath Help";

/** `article` is supplied when prerendering or hydrating; otherwise the page loads it. */
export default function HelpPage({
  slug = "",
  article: supplied,
}: {
  slug?: string;
  article?: Article | null;
}): ReactNode {
  const meta = slug ? getArticleMeta(slug) : undefined;
  const [article, setArticle] = useState<Article | null>(supplied ?? null);
  useEffect(() => {
    document.title = pageTitle(meta);
  }, [meta]);
  useEffect(() => {
    if (!meta || supplied) return;
    let live = true;
    void loadArticle(meta.slug).then((loaded) => {
      if (live) setArticle(loaded);
    });
    return () => {
      live = false;
    };
  }, [meta, supplied]);
  return (
    <div className="help-page">
      <a className="help-skip" href="#help_main">
        Skip to content
      </a>
      {!slug ? <Hub /> : meta ? <ArticleView meta={meta} article={article} /> : <NotFound />}
    </div>
  );
}
