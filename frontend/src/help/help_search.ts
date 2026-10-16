import { articles, getSection } from "./help_catalog";
import type { ArticleMeta } from "./help_types";

/** Body text the build extracts from each article, fetched on first search. */
export interface SearchBody {
  slug: string;
  headings: string[];
  text: string;
}
export const SEARCH_INDEX_PATH = "/help_search_index.json";

const STOP = new Set([
  "a",
  "an",
  "the",
  "my",
  "i",
  "is",
  "are",
  "of",
  "to",
  "and",
  "or",
  "in",
  "on",
  "for",
  "do",
  "does",
  "did",
  "how",
  "what",
  "when",
  "why",
  "can",
  "it",
  "me",
  "with",
  "be",
  "at",
  "from",
  "this",
  "that",
  "there",
]);

export function normalize(text: string) {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[’']/g, "")
    .replace(/[^a-z0-9½]+/g, " ")
    .trim();
}

export function tokens(query: string) {
  return normalize(query)
    .split(" ")
    .filter((token) => token && !STOP.has(token));
}

interface Field {
  text: string;
  weight: number;
}

function fieldsFor(meta: ArticleMeta, body?: SearchBody): Field[] {
  return [
    { text: normalize(meta.title), weight: 10 },
    { text: normalize(meta.aliases.join(" | ")), weight: 7 },
    { text: normalize(body?.headings.join(" | ") ?? ""), weight: 4 },
    { text: normalize(meta.dek), weight: 3 },
    { text: normalize(getSection(meta.section).title), weight: 2 },
    { text: normalize(body?.text ?? ""), weight: 1 },
  ];
}

const wordStart = (text: string, token: string) =>
  text.startsWith(token) || text.includes(` ${token}`);
/** Light stemming so "retiring", "retired" and "retirement" meet at "retir". */
const stem = (token: string) => {
  const cut = token.replace(/(ments?|ing|ed|es|s)$/, "");
  return cut.length >= 3 && cut !== token ? cut.replace(/e$/, "") : token;
};

/**
 * Most query words must match (all of them for one or two words); title and alias matches rank
 * first, so symptom phrasing finds its troubleshooting article.
 */
export function search(
  query: string,
  bodies: Map<string, SearchBody> = new Map(),
  limit = 12,
): ArticleMeta[] {
  const wanted = tokens(query);
  const phrase = normalize(query);
  if (!wanted.length) return [];
  const needed = wanted.length <= 2 ? wanted.length : Math.ceil(wanted.length * 0.6);
  const scored = articles.map((meta) => {
    const fields = fieldsFor(meta, bodies.get(meta.slug));
    let score = 0;
    let matched = 0;
    for (const token of wanted) {
      const root = stem(token);
      let best = 0;
      for (const field of fields) {
        if (!field.text) continue;
        if (wordStart(field.text, token)) best = Math.max(best, field.weight);
        else if (root !== token && wordStart(field.text, root))
          best = Math.max(best, field.weight * 0.8);
        else if (token.length > 3 && field.text.includes(token))
          best = Math.max(best, field.weight / 2);
      }
      if (best) {
        matched += 1;
        score += best;
      }
    }
    if (matched < needed) return { meta, score: 0 };
    score *= matched / wanted.length;
    if (phrase.length > 3 && fields[0].text.includes(phrase)) score += 12;
    if (phrase.length > 3 && fields[1].text.includes(phrase)) score += 8;
    if (meta.kind === "troubleshooting" && fields[1].text.includes(phrase)) score += 2;
    return { meta, score };
  });
  return scored
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((item) => item.meta);
}

let pending: Promise<Map<string, SearchBody>> | null = null;

/** Loads the build's body index once; falls back to metadata-only search when it's unavailable (dev server). */
export function loadSearchBodies(): Promise<Map<string, SearchBody>> {
  pending ??= fetch(SEARCH_INDEX_PATH)
    .then((response) => (response.ok ? (response.json() as Promise<SearchBody[]>) : []))
    .then((list) => new Map(list.map((body) => [body.slug, body])))
    .catch(() => new Map<string, SearchBody>());
  return pending;
}
