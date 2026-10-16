import { readFile, unlink, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { createServer, type Plugin, type ResolvedConfig } from "vite";
import react from "@vitejs/plugin-react";

const escapeHtml = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
interface RenderedPage {
  path: string;
  file: string;
  title: string;
  description: string;
  html: string;
  schema: Record<string, unknown>;
}

/**
 * Dev server only: answers /help and /help/<slug> with the help entry page, as production's help
 * router does, so the planner's global stylesheet never applies to help pages.
 */
export function helpDevRoutes(): Plugin {
  return {
    name: "coastmath_help_dev_routes",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        const [pathname, query] = (request.url ?? "").split("?");
        if (/^\/help(\/[a-z0-9-]+)?\/?$/.test(pathname))
          request.url = `/help.html${query ? `?${query}` : ""}`;
        next();
      });
    },
  };
}

/**
 * Renders the help center to complete HTML documents after every production build, like the
 * calculators. Writes one file per article, `help_manifest.json` and `help_redirects.json` (renamed
 * slugs) for the FastAPI router and `help_search_index.json` for search. Fails the build when an
 * article is missing, a redirect doesn't land on one, or a page cites a source (sources stay in
 * docs/help_center/sources and are never served).
 */
export function helpPrerender(): Plugin {
  let config: ResolvedConfig;
  return {
    name: "coastmath_help_prerender",
    apply: "build",
    configResolved(resolved) {
      config = resolved;
    },
    async closeBundle() {
      const out = path.resolve(config.root, config.build.outDir);
      const templatePath = path.join(out, "help.html");
      const template = await readFile(templatePath, "utf8");
      const configured = process.env.PUBLIC_SITE_URL?.trim();
      const origin = configured ? new URL(configured).origin : "";
      if (configured && !/^https?:\/\//.test(origin))
        throw new Error("PUBLIC_SITE_URL must use http or https.");
      const server = await createServer({
        configFile: false,
        root: config.root,
        plugins: [react()],
        // The build's own aliases, so `@extensions/help` resolves to the same module.
        resolve: { alias: config.resolve.alias },
        optimizeDeps: { noDiscovery: true, include: [] },
        server: { middlewareMode: true, watch: null },
        appType: "custom",
      });
      try {
        const module = await server.ssrLoadModule("/src/help/help_prerender.tsx");
        const articles = await module.loadArticles();
        const pages: RenderedPage[] = module.renderPages(articles, origin);
        await mkdir(path.join(out, "help"), { recursive: true });
        for (const page of pages) {
          const url = origin + page.path;
          const schema = JSON.stringify({ ...page.schema, url }).replace(/</g, "\\u003c");
          const metadata = `<link rel="canonical" href="${escapeHtml(url)}" />\n<meta property="og:type" content="${page.path === "/help" ? "website" : "article"}" />\n<meta property="og:title" content="${escapeHtml(page.title)}" />\n<meta property="og:description" content="${escapeHtml(page.description)}" />\n${origin ? `<meta property="og:url" content="${escapeHtml(url)}" />\n` : ""}<script type="application/ld+json">${schema}</script>`;
          const html = template
            .replace(/<title>.*?<\/title>/, () => `<title>${escapeHtml(page.title)}</title>`)
            .replace(
              /<meta name="description" content="[^"]*"\s*\/>/,
              () => `<meta name="description" content="${escapeHtml(page.description)}" />`,
            )
            .replace("<!--help_metadata-->", () => metadata)
            .replace('<div id="root"></div>', () => `<div id="root">${page.html}</div>`);
          if (!html.includes("<h1") || !html.includes('rel="canonical"'))
            throw new Error(`Prerender failed for ${page.path}`);
          await writeFile(path.join(out, page.file), html);
        }
        await writeFile(
          path.join(out, "help_manifest.json"),
          JSON.stringify(Object.fromEntries(pages.map((page) => [page.path, page.file])), null, 2),
        );
        await writeFile(
          path.join(out, "help_redirects.json"),
          JSON.stringify(module.redirectPaths(), null, 2),
        );
        await writeFile(
          path.join(out, "help_search_index.json"),
          JSON.stringify(module.searchBodies(articles)),
        );
        await unlink(templatePath);
        config.logger.info(`Prerendered ${pages.length} help pages with complete HTML.`);
      } finally {
        await server.close();
      }
    },
  };
}
