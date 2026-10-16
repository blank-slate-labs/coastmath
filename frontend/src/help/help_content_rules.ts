/**
 * Published help text never carries source citations or internal implementation references.
 * Citations stay outside the frontend and are never bundled or served. The build and the
 * article tests both reject a rendered page's help content (see `helpContent`) that matches any of
 * these patterns.
 */
export const FORBIDDEN_CONTENT: { pattern: RegExp; reason: string }[] = [
  { pattern: /https?:\/\/(?!(www\.)?coastmath\.com)/i, reason: "external URL" },
  { pattern: /\b[a-z0-9-]+\.gov\b/i, reason: "government source domain" },
  { pattern: /\bU\.\s?S\.\s?C\.?|\bUSC\b/, reason: "U.S. Code citation" },
  { pattern: /C\.\s?F\.\s?R\.?|\bCFR\b/, reason: "regulation citation" },
  { pattern: /§/, reason: "section symbol" },
  { pattern: /\bIRC\b|Internal Revenue Code/i, reason: "tax code citation" },
  { pattern: /\b(Pub\.|Publication)\s*\d/i, reason: "publication citation" },
  {
    pattern: /\bRev\.\s*(Proc|Rul)\b|\bRevenue (Procedure|Ruling)\b/i,
    reason: "revenue procedure citation",
  },
  { pattern: /\bNotice\s+20\d\d-\d+/i, reason: "notice citation" },
  { pattern: /Treas\.?\s*Reg\b|Treasury Regulation/i, reason: "regulation citation" },
  { pattern: /\bPOMS\b|\bIRM\b/, reason: "agency manual citation" },
  {
    pattern: /\.py\b|\bapp\/|\bengine\/|\bbackend\b|\bsimulator\b|\bdataclass\b/i,
    reason: "implementation reference",
  },
  { pattern: /\b[a-z]+_[a-z0-9_]+\(/, reason: "code identifier" },
];

/**
 * A rendered page's `<main>`: the hub or the article. The top bar and footer are site chrome whose
 * links (downloads, legal pages) are configured, not written help text.
 */
export function helpContent(html: string) {
  const count = html.match(/<main[\s>]/g)?.length ?? 0;
  const main = html.match(/<main[\s>][\s\S]*<\/main>/);
  if (count !== 1 || !main) throw new Error(`Expected one <main> in a help page, found ${count}`);
  return main[0];
}

export function contentViolations(html: string) {
  const text = html.replace(/<[^>]+>/g, " ");
  const hrefs = [...html.matchAll(/href="([^"]*)"/g)].map((match) => match[1]).join(" ");
  return FORBIDDEN_CONTENT.filter(
    (rule) => rule.pattern.test(text) || rule.pattern.test(hrefs),
  ).map((rule) => {
    const match = text.match(rule.pattern) ?? hrefs.match(rule.pattern);
    return `${rule.reason}: “${match?.[0] ?? ""}”`;
  });
}
