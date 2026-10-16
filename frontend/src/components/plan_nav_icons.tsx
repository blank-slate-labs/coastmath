import type { ReactNode } from "react";

import type { PlanSectionKey } from "@/pages/plan_setup";
import type { CurveType } from "@/types/plan";

/** Every glyph the plan sidebar draws: one per section, one per assumption, and UI marks. */
export type NavGlyphName = PlanSectionKey | CurveType | "search" | "chevron" | "close";

// 24×24 stroke glyphs, drawn in currentColor so the tile or row sets the colour.
const GLYPHS: Record<NavGlyphName, ReactNode> = {
  plan_details: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  accounts: (
    <>
      <path d="M3 10 12 4l9 6" />
      <path d="M5.5 10v8M10 10v8M14 10v8M18.5 10v8" />
      <path d="M3 21h18" />
    </>
  ),
  income: (
    <>
      <path d="M12 3v11" />
      <path d="m7.5 9.5 4.5 4.5 4.5-4.5" />
      <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </>
  ),
  expenses: (
    <>
      <circle cx="9" cy="20" r="1.4" />
      <circle cx="17.5" cy="20" r="1.4" />
      <path d="M2.5 3.5h2.8l2.4 11a1 1 0 0 0 1 .8h9a1 1 0 0 0 1-.8l1.8-7.8H6" />
    </>
  ),
  assumptions: (
    <>
      <path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1" />
      <circle cx="15" cy="6" r="2" />
      <circle cx="9" cy="12" r="2" />
      <circle cx="17" cy="18" r="2" />
    </>
  ),
  milestones: (
    <>
      <path d="M5.5 21V4" />
      <path d="M5.5 4h12l-2.5 4 2.5 4h-12" />
    </>
  ),
  flex: (
    <>
      <path d="M4 18a8 8 0 1 1 16 0" />
      <path d="m12 18 4-5" />
      <path d="M12 6v1.5M6.3 8.3l1 1M17.7 8.3l-1 1" />
    </>
  ),
  connections: (
    <>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
    </>
  ),
  transactions: (
    <>
      <path d="M4 7h13" />
      <path d="m14 4 3 3-3 3" />
      <path d="M20 17H7" />
      <path d="m10 14-3 3 3 3" />
    </>
  ),
  income_allocation: (
    <>
      <path d="M12 21v-8" />
      <path d="M12 13 5.5 6.5M12 13l6.5-6.5" />
      <path d="M5 11.5V6h5.5M19 11.5V6h-5.5" />
    </>
  ),
  property_debt: (
    <>
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5.5 10v10h13V10" />
      <path d="M10 20v-5.5h4V20" />
    </>
  ),
  drawdown: (
    <>
      <path d="M4 6h10M4 12h7M4 18h4" />
      <path d="M18 4v15" />
      <path d="m14.5 15.5 3.5 3.5 3.5-3.5" />
    </>
  ),
  charitable: (
    <>
      <rect x="3" y="8" width="18" height="4" rx="1" />
      <path d="M12 8v13M5 12v9h14v-9" />
      <path d="M12 8S10.6 3.2 8.2 3.9C6.3 4.5 7.1 8 12 8Zm0 0s1.4-4.8 3.8-4.1C17.7 4.5 16.9 8 12 8Z" />
    </>
  ),
  healthcare: (
    <path d="M12 20s-8-4.9-8-11a4.4 4.4 0 0 1 8-2.6A4.4 4.4 0 0 1 20 9c0 6.1-8 11-8 11Z" />
  ),
  estate: (
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0" />
      <path d="M15.5 4.6a3.5 3.5 0 0 1 0 6.8M18 14.2a6.5 6.5 0 0 1 3.5 5.8" />
    </>
  ),
  notes: (
    <>
      <path d="M4 20h4L19 9l-4-4L4 16Z" />
      <path d="m13 7 4 4" />
    </>
  ),
  market_return: (
    <>
      <path d="m3 17 6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </>
  ),
  inflation: (
    <>
      <path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z" />
      <circle cx="7.5" cy="7.5" r="1.5" />
    </>
  ),
  bond_return: (
    <>
      <path d="M6 3h9l4 4v14H6Z" />
      <path d="M14.5 3v4.5H19M9 13h6M9 17h6" />
    </>
  ),
  bond_allocation: (
    <>
      <path d="M21 12a9 9 0 1 1-9-9v9Z" />
      <path d="M15 3.5A9 9 0 0 1 20.5 9H15Z" />
    </>
  ),
  dividend_yield: (
    <>
      <ellipse cx="12" cy="6" rx="7" ry="3" />
      <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
      <path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
    </>
  ),
  wage_growth: (
    <>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18" />
    </>
  ),
  cash_yield: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 6v12M15 8.5h-4a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4H9" />
    </>
  ),
  social_security_cola: <path d="M12 3 5 6v6c0 4.4 3 7.7 7 9 4-1.3 7-4.6 7-9V6Z" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m20 20-4.4-4.4" />
    </>
  ),
  chevron: <path d="m9 18 6-6-6-6" />,
  close: <path d="M17 7 7 17M7 7l10 10" />,
};

/** A decorative sidebar glyph. Always aria-hidden: the surrounding control carries the name. */
export function NavGlyph({
  name,
  size = 16,
  strokeWidth = 2,
  className,
}: {
  name: NavGlyphName;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {GLYPHS[name]}
    </svg>
  );
}
