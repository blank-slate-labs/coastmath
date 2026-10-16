import { lazy, Suspense, useState, useEffect } from "react";

import { LoadingStatus } from "@/components/loading_status";
import { extensions, plannerPath } from "@/extensions";

const App = lazy(() => import("./app"));
const TerminalDashboard = lazy(() =>
  import("./pages/terminal_dashboard").then((module) => ({ default: module.TerminalDashboard })),
);
const PlaidOAuthReturn = lazy(() => import("./pages/plaid_oauth_return"));

export function canonicalPath(path: string) {
  const owned = extensions.routes?.canonicalPath(path);
  if (owned !== undefined) return owned;
  const trimmed = path.replace(/\/+$/, "") || "/";
  if ([plannerPath(), "/terminal", "/plaid/oauth"].includes(trimmed)) return trimmed;
  return path;
}

export default function TerminalRouter() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const route = canonicalPath(path);

  useEffect(() => {
    if (route !== path) {
      window.history.replaceState(
        window.history.state,
        "",
        `${route}${window.location.search}${window.location.hash}`,
      );
    }
  }, [path, route]);

  const page =
    extensions.routes?.page(route) ??
    (route === plannerPath() ? (
      <App />
    ) : route === "/terminal" ? (
      <TerminalDashboard />
    ) : route === "/plaid/oauth" ? (
      <PlaidOAuthReturn />
    ) : (
      <main style={{ maxWidth: 640, margin: "80px auto", padding: 24 }}>
        <h1>Page not found</h1>
        <p>This address does not match a CoastMath page.</p>
        <a href="/">Return to CoastMath</a>
      </main>
    ));

  return <Suspense fallback={<LoadingStatus />}>{page}</Suspense>;
}
