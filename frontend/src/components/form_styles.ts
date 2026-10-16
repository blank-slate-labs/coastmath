/** Grid layout of the inline add/edit forms for plan rows (accounts, incomes, expenses, milestones, charities). */
export const formStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(220px, 100%), 1fr))",
  gap: 12,
  padding: 14,
  background: "var(--gray-50)",
  borderRadius: "var(--radius-md)",
  marginBottom: 8,
};

/** Small secondary help text under a control. */
export const helpTextStyle: React.CSSProperties = { fontSize: 12, color: "var(--text-secondary)" };

/** A radio or checkbox with its text on one line. */
export const choiceLabelStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
};
