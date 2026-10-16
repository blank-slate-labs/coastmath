import { HELP_ROOT } from "@/help/help_catalog";

/**
 * The planner's always-visible way into the help center: a pill pinned to the bottom left of
 * the window, over the sidebar footer. Help is a separate page, so it opens in a new tab and
 * the planner keeps its place and any open draft. `compact` (the collapsed desktop sidebar)
 * shows only the glyph, which fits the 64px rail. On a phone the pinned pill would cover content,
 * so the `bar` placement sits in the mobile plan bar instead and the pill is hidden there.
 */
export default function HelpButton({
  compact = false,
  placement = "floating",
}: {
  compact?: boolean;
  placement?: "floating" | "bar";
}) {
  return (
    <a
      className={`${placement === "bar" ? "app-help-bar-link" : "app-help-button"} no-print${compact ? " is-compact" : ""}`}
      href={HELP_ROOT}
      target="_blank"
      rel="noopener"
      title="Open CoastMath Help in a new tab"
    >
      <svg
        aria-hidden="true"
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3" />
        <path d="M12 17h.01" />
      </svg>
      <span className="app-help-label">Help</span>
      <span className="app-help-hint"> (opens in a new tab)</span>
    </a>
  );
}
