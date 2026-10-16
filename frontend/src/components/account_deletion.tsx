import { useState } from "react";

import { useAuthStore } from "@/stores/auth_store";

export function AccountDeletion() {
  const remove = useAuthStore((s) => s.deleteAccount);
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!open)
    return (
      <button type="button" className="link-button is-danger" onClick={() => setOpen(true)}>
        Delete account
      </button>
    );
  return (
    <section aria-label="Delete account">
      <p>
        This permanently deletes your account, plans and financial records and disconnects linked
        institutions. It cannot be undone.
      </p>
      <label>
        Type DELETE to confirm
        <input
          value={confirmation}
          disabled={busy}
          onChange={(event) => setConfirmation(event.target.value)}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <button
        type="button"
        disabled={busy || confirmation !== "DELETE"}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await remove();
          } catch (failure) {
            setError(
              failure instanceof Error
                ? failure.message
                : "Account deletion failed. Please try again.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Working…" : "Permanently delete account"}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setOpen(false);
          setConfirmation("");
          setError("");
        }}
      >
        Cancel
      </button>
    </section>
  );
}
