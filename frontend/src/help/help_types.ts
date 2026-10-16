import type { ReactNode } from "react";
import type { HelpLink, UIPath } from "./help_kit";

/** Stages of one projection year, in the order the engine settles them. */
export type StageId =
  "events" | "growth" | "required" | "income" | "spending" | "cashflow" | "taxes" | "yearend";

export type SectionId =
  | "start"
  | "income"
  | "spending"
  | "accounts"
  | "withdrawals"
  | "taxes"
  | "property"
  | "life"
  | "analysis"
  | "results"
  | "support";

/** guide: how to do something. calculation: how the engine computes it. troubleshooting: symptom first. */
export type ArticleKind = "guide" | "calculation" | "troubleshooting";

export interface Stage {
  id: StageId;
  name: string;
  summary: string;
}
export interface Section {
  id: SectionId;
  title: string;
}

export interface ArticleMeta {
  /** URL slug with dashes; the module file uses underscores. */
  slug: string;
  title: string;
  /** One sentence shown under the title and in lists. */
  dek: string;
  section: SectionId;
  kind: ArticleKind;
  /** Where in the year the article's behavior happens; empty for account and support topics. */
  stages: StageId[];
  /** Phrases readers search for, including symptoms. Not displayed. */
  aliases: string[];
  related: string[];
  /** ISO date the article was last checked against the product. */
  updated: string;
  /** Tax or benefit year of any statutory figures quoted. */
  figuresYear?: number;
}

export interface ArticleSection {
  id: string;
  title: string;
  body: ReactNode;
}

/** An article module's default export. Metadata lives in the catalog. */
export interface Article {
  intro: ReactNode;
  sections: ArticleSection[];
}

/**
 * What a hosting package adds to the help center. `@extensions/help` resolves to it like
 * `@extensions/active` (vite.config.ts, tsconfig.json), but help pages load only this module.
 */
export interface HelpExtension {
  /** Articles about the hosted service, each placed next to a catalog article. */
  articles?: HelpArticleExtension[];
  /** Catalog fields that replace a catalog article's own, by slug. */
  revisions?: Record<string, Partial<Omit<ArticleMeta, "slug">>>;
  /** A passage's hosted version, by part id; see `hostedPart` in help_kit. */
  parts?: Record<string, (kit: PartKit) => unknown>;
  /** A hub card's blurb and featured articles, by section. */
  topics?: Partial<Record<SectionId, { blurb: string; featured: string[] }>>;
  /** Footer links after Help; an absolute URL opens in a new tab. */
  footerLinks?: { href: string; label: ReactNode }[];
  /** Where "Open planner" leads; "/" without an extension. */
  plannerPath?: string;
}

export interface HelpArticleExtension {
  meta: ArticleMeta;
  load(): Promise<{ default: Article }>;
  /** The catalog article this one directly precedes, or follows. */
  before?: string;
  after?: string;
}

/** Components a hosted part may use: the hosting package's help can't import help_kit without a cycle. */
export interface PartKit {
  HelpLink: typeof HelpLink;
  UIPath: typeof UIPath;
}
