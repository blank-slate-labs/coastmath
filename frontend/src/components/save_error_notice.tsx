import { useEffect, useRef } from "react";

/** `focus` moves focus to the notice; an autosave on blur leaves focus where the person moved it. */
export default function SaveErrorNotice({
  message,
  focus = true,
}: {
  message: string | null;
  focus?: boolean;
}) {
  const notice = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (message && focus) notice.current?.focus();
  }, [message, focus]);
  if (!message) return null;
  return (
    <div ref={notice} tabIndex={-1} role="alert" style={{ overflowWrap: "anywhere" }}>
      <p>{message}</p>
      <p>Your draft is kept.</p>
    </div>
  );
}
