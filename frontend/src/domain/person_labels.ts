/**
 * Display labels for the two people in a plan. The wire values stay
 * `"self"` / `"spouse"` (and `"joint"` for accounts); only these labels are
 * shown, so the planner never prints a raw owner value.
 */
export const PRIMARY_PERSON_LABEL = "Primary person";
export const PARTNER_LABEL = "Partner";

/** "Primary person", "Partner" or "Joint" for an owner value; a missing owner is the primary person. */
export function ownerLabel(owner: string | null | undefined): string {
  if (owner === "spouse") return PARTNER_LABEL;
  if (owner === "joint") return "Joint";
  if (owner == null || owner === "" || owner === "self") return PRIMARY_PERSON_LABEL;
  // A legacy value outside the known set: show it rather than guess an owner.
  return owner;
}

/** "Primary person's" or "Partner's". */
export function ownerPossessive(owner: "self" | "spouse"): string {
  return `${ownerLabel(owner)}'s`;
}

/**
 * " (Partner)"-style suffix for a list row. A single-person plan shows none
 * for the primary person's rows; any other owner is always named.
 */
export function ownerSuffix(owner: string | null | undefined, hasPartner: boolean): string {
  const primary = owner == null || owner === "" || owner === "self";
  if (primary && !hasPartner) return "";
  return ` (${ownerLabel(owner)})`;
}
