import { failedSaveText, useSaveStore } from "@/stores/save_store";

/** Saving, failed or the last save time. */
export function SaveStatus() {
  const { pending, failed, failures, lastSavedAt, announcer } = useSaveStore();
  // While an editor is open, its footer is the live region; this line stays readable without announcing.
  const live = announcer === "header" ? { role: "status", "aria-label": "Save status" } : {};
  const text = pending
    ? "Saving…"
    : failed.length
      ? failedSaveText({ failed, failures })
      : lastSavedAt
        ? `Saved ${new Date(lastSavedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
        : "Saved";
  // A failed save is announced once, by the editor's own alert; this line says only "Not saved" aloud.
  // The open editor's footer states a failure in full; this line then says only "Not saved."
  if (failed.length)
    return (
      <span className="is-failed">
        <span {...live}>Not saved.</span>
        {announcer === "header" && (
          <>
            {" "}
            <span aria-hidden="true">{text}</span>
          </>
        )}
      </span>
    );
  return <span {...live}>{text}</span>;
}
