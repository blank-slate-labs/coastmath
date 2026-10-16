import { StrictMode } from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import HelpPage from "./help_page";
import { loadArticle } from "./help_articles";
import { HELP_ROOT, articlePath, getArticleMeta, movedArticles } from "./help_catalog";

const root = document.getElementById("root")!;
const path = window.location.pathname.replace(/\/+$/, "");
const requested = path.startsWith(`${HELP_ROOT}/`) ? path.slice(HELP_ROOT.length + 1) : "";
// The server redirects a renamed slug; the dev server answers every slug, so map it here too.
const slug = movedArticles.get(requested) ?? requested;
if (slug !== requested) {
  const { search, hash } = window.location;
  history.replaceState(history.state, "", `${articlePath(slug)}${search}${hash}`);
}

// Hydration needs the same article the prerender used, so load its chunk first; the
// prerendered HTML stays readable meanwhile.
async function start() {
  const article = slug && getArticleMeta(slug) ? await loadArticle(slug) : null;
  const page = (
    <StrictMode>
      <HelpPage slug={slug} article={article} />
    </StrictMode>
  );
  if (root.hasChildNodes()) hydrateRoot(root, page);
  else createRoot(root).render(page);
}
void start();
