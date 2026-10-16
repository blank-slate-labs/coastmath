import { useEffect, useRef, useState } from "react";
import { errorMessage } from "@/utils/error_message";
import { resumePlaidConnection, takePlaidSession } from "@/components/ledger/plaid_link";
import { plannerPath } from "@/extensions";

/** Where an OAuth institution returns during Plaid Link: resume Link, then go back to the planner. */
export default function PlaidOAuthReturn() {
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    // StrictMode runs effects twice; the saved session can resume Link only once.
    if (started.current) return;
    started.current = true;
    const href = window.location.href;
    const session = takePlaidSession();
    // The OAuth state must not stay in the address bar or history.
    window.history.replaceState(null, "", "/plaid/oauth");
    if (!session) {
      setError("This bank sign-in expired. Start the connection again.");
      return;
    }
    resumePlaidConnection(session, href)
      .then(() => window.location.replace(plannerPath()))
      .catch((failure) => setError(errorMessage(failure)));
  }, []);

  return (
    <main style={{ maxWidth: 480, margin: "12vh auto", padding: 24 }}>
      <h1>Connecting your bank</h1>
      {error ? (
        <>
          <p role="alert">{error}</p>
          <a href={plannerPath()}>Return to CoastMath</a>
        </>
      ) : (
        <p role="status">Finishing with Plaid…</p>
      )}
    </main>
  );
}
