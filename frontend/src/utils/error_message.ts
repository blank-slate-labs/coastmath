/** A thrown error's message, or a generic reload prompt for anything else. */
export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "The change could not be confirmed. Reload before retrying.";
}
