import help from "@extensions/help";
import { moduleName } from "./help_catalog";
import type { Article } from "./help_types";

/* Each article is its own chunk: a page downloads only the article it shows. */
const loaders = import.meta.glob<{ default: Article }>("./articles/*.tsx");
const hosted = new Map((help.articles ?? []).map(({ meta, load }) => [meta.slug, load]));

const loaderFor = (slug: string) =>
  hosted.get(slug) ?? loaders[`./articles/${moduleName(slug)}.tsx`];

/** Slugs of every article module: this directory's and a hosting package's. */
export const articleModuleSlugs = () => [
  ...Object.keys(loaders).map((file) =>
    file
      .replace("./articles/", "")
      .replace(/\.tsx$/, "")
      .replace(/_/g, "-"),
  ),
  ...hosted.keys(),
];
export const hasArticleModule = (slug: string) => !!loaderFor(slug);

export async function loadArticle(slug: string): Promise<Article | null> {
  const loader = loaderFor(slug);
  return loader ? (await loader()).default : null;
}
