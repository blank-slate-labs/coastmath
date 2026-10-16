/** Device preferences (theme, currency mode) outlive a sign-out; these account and plan keys do not. */
const accountKeyPrefixes = [
  "coastmath:active-plan:",
  "coastmath:metrics:",
  "coastmath:fi_estimate_hidden:",
  "coastmath:builder:",
  "coastmath.",
];

export function clearAccountStorage(): void {
  try {
    const keys = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i) ?? "");
    for (const key of keys) {
      if (accountKeyPrefixes.some((prefix) => key.startsWith(prefix))) localStorage.removeItem(key);
    }
  } catch {
    /* Storage unavailable: nothing was kept. */
  }
  // Unsaved allocation drafts include amounts and account identifiers.
  try {
    sessionStorage.clear();
  } catch {
    /* Storage unavailable: nothing was kept. */
  }
}
