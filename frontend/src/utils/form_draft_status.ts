import { useEffect, useState } from "react";

/** Compare raw form values so blank, invalid and hidden-field edits stay dirty. */
export function useFormDraftStatus(snapshot: string) {
  const [baseline, setBaseline] = useState(snapshot);
  const [confirmed, setConfirmed] = useState(false);
  const dirty = snapshot !== baseline;
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  return {
    dirty,
    saved: confirmed && !dirty,
    clearSaved: () => setConfirmed(false),
    markSaved: () => {
      setBaseline(snapshot);
      setConfirmed(true);
    },
  };
}
