import type { ComponentType, ReactNode } from "react";

import type { SetupNext } from "@/components/goals_intake_form";
import type { PlanSectionDef } from "@/pages/plan_setup";
import type { StorageAdapter } from "@/storage/adapter";
import type { PlanCreate, PlanData, PlanSummary, User } from "@/types/plan";

/**
 * What a hosting package adds to the open-source planner. Every member is
 * optional: without an extension the planner runs on its own, with every
 * feature available to the one local account. `@extensions/active` resolves
 * to the hosting package when it is present (vite.config.ts, tsconfig.json).
 */
export interface Extensions {
  routes?: RouteExtension;
  session?: SessionExtension;
  access?: AccessExtension;
  planner?: PlannerExtension;
  api?: ApiExtension;
}

/** Pages outside the planner. */
export interface RouteExtension {
  /** Where the planner is served; "/" without an extension. */
  plannerPath: string;
  /** The canonical form of a path the extension owns, or undefined. */
  canonicalPath(path: string): string | undefined;
  /** The page for a canonical path the extension owns, or undefined. */
  page(route: string): ReactNode | undefined;
}

/** Sign-in providers. Without them the planner opens an anonymous session. */
export interface SessionExtension {
  /** Shown to a signed-out visitor instead of starting an anonymous session. */
  sample: SampleExtension;
  /** Ends the provider's own session after the server's. */
  signOut(): Promise<void>;
  /** Where the browser goes after signing out. */
  afterSignOut: string;
  /** Deletes an account whose sign-in provider must confirm it; false leaves deletion to the server route. */
  deleteAccount(user: User): Promise<boolean>;
  /** The planner header's save status and account menu. */
  SessionStatus: ComponentType;
  /** Shown instead of the planner while an account deletion is pending. */
  DeletionPending: ComponentType;
}

/** A read-only planner over static data for signed-out visitors. */
export interface SampleExtension {
  createAdapter(): StorageAdapter;
  /** Called with true while the sample is open; requests that would change data are refused. */
  setActive(active: boolean): void;
  /** Mounted while the sample is open. */
  Mode: ComponentType;
  /** Beside the plan title while the sample is open. */
  Badge: ComponentType;
  loadingText: string;
}

/** Features an access policy may lock. The server enforces each one separately. */
export interface AccessExtension {
  locked(user: User | null, feature: string): boolean;
  /** Explains why `feature` is locked, for an action the account just tried. */
  explain(feature: string): void;
  /** Marks an action whose feature is locked. */
  LockGlyph: ComponentType<{ size?: number }>;
  /** Shown where a locked feature would be. */
  LockedFeature: ComponentType<{ feature: string }>;
}

/** Extra parts of the planner shell. */
export interface PlannerExtension {
  /** Before the session status in the planner header. */
  HeaderLead?: ComponentType;
  /** After the session status in the planner header. */
  HeaderTrail?: ComponentType;
  /** In the mobile plan bar, before the plan menu button. */
  MobileBarActions?: ComponentType;
  /** Above the plan views. */
  Banner?: ComponentType<{ onReviewConnections: () => void }>;
  /** Under the plan title. */
  PlanNotice?: ComponentType<{ plan: PlanData | null }>;
  /** While no editor sheet is open. */
  SheetNotice?: ComponentType<{
    plan: PlanData | null;
    sections: PlanSectionDef[];
    onOpenSection: (key: string) => void;
  }>;
  /** Before the planner layout while the printable report is closed. */
  BeforeShell?: ComponentType;
  /** After the planner layout, e.g. dialogs. */
  Overlays?: ComponentType;
  /** A plan section's editor opened. */
  onSectionOpened?(planId: string, sectionKey: string): void;
  /** Builder sections inserted after Accounts. */
  sections?: PlanSectionDef[];
  /** Ways to start a plan besides an empty one. */
  imports?: {
    key: string;
    label: string;
    Form: ComponentType<{ onCreate: (next?: SetupNext) => void }>;
  }[];
  /** Client workspaces besides the default one. */
  workspaces?: WorkspaceExtension;
  /** Text fields of the plan shown first under Plan details › Advanced tax settings. */
  planTextFields?: PlanTextField[];
}

/** A plan field that holds free text (not a choice list). */
export type PlanTextKey = {
  [K in keyof PlanCreate & keyof PlanData]-?: string extends NonNullable<PlanCreate[K]>
    ? NonNullable<PlanCreate[K]> extends string
      ? K
      : never
    : never;
}[keyof PlanCreate & keyof PlanData];

/**
 * A text input the plan editor adds for an extension. It autosaves on blur like the
 * editor's own fields, a blank value as null, and keeps its draft when a save fails.
 */
export interface PlanTextField {
  field: PlanTextKey;
  label: string;
  autoComplete?: string;
  maxLength?: number;
}

/**
 * Plans grouped by client workspace. Without it the plan selector lists every
 * plan and new plans go to the account's default workspace.
 */
export interface WorkspaceExtension {
  /**
   * The plans the selector lists, given every active plan and the open one, and
   * the client a new plan belongs to: undefined for the default workspace.
   */
  useScope(
    plans: PlanSummary[],
    plan: PlanData | null,
  ): { plans: PlanSummary[]; clientId?: string };
  /** Above the plan selector. `onNewPlan` starts a plan in a client; null is the default workspace. */
  Switcher: ComponentType<{ onNewPlan: (clientId: string | null) => void }>;
}

/** A refusal the extension explains itself, e.g. with a prompt. */
export interface Refusal {
  /** One line naming what was refused. */
  message: string;
  /** Shows the extension's explanation. */
  announce(): void;
  /** The error callers receive, carrying `message`. */
  error(message: string): Error;
}

export interface ApiExtension {
  /** Runs before each request; throwing stops it. */
  beforeRequest?(config: { method?: string; url?: string }): void;
  /** The extension's own refusal in a failed response, or undefined. */
  refusal?(error: unknown): Refusal | undefined;
  /** True for an error whose own prompt already explained it. */
  isExplained?(error: unknown): boolean;
}
