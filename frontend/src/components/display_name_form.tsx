import { useId, useState } from "react";
import { useAuthStore } from "@/stores/auth_store";
import type { User } from "@/types/plan";

/** The account's display name (PUT /auth/me). A failed save keeps the draft. */
export function DisplayNameForm({ user }: { user: User }) {
  const updateProfile = useAuthStore((s) => s.updateProfile);
  const saved = user.display_name && user.display_name !== "Anonymous" ? user.display_name : "";
  const [name, setName] = useState(saved);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const errorId = useId();

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const value = name.trim();
    if (!value) {
      setError("Enter a name.");
      return;
    }
    setSaving(true);
    setError(null);
    setDone(false);
    try {
      await updateProfile(value);
      setName(value);
      setDone(true);
    } catch (err) {
      setError(
        err instanceof Error && err.message ? err.message : "Could not save your name. Try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="session-name" onSubmit={handleSubmit}>
      <label>
        Your name
        <input
          value={name}
          maxLength={255}
          autoComplete="name"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(e) => {
            setName(e.target.value);
            setDone(false);
            setError(null);
          }}
        />
      </label>
      <button type="submit" disabled={saving || name.trim() === saved}>
        {saving ? "Saving…" : "Save name"}
      </button>
      {error && (
        <p id={errorId} role="alert">
          {error}
        </p>
      )}
      {done && <p role="status">Name saved.</p>}
    </form>
  );
}
