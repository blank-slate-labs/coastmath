/** While a view's code downloads, its space stays empty; only screen readers hear the status. */
export function LoadingStatus({ label = "Loading CoastMath…" }: { label?: string }) {
  return (
    <div role="status" style={VISUALLY_HIDDEN}>
      {label}
    </div>
  );
}

const VISUALLY_HIDDEN = {
  position: "absolute",
  width: 1,
  height: 1,
  margin: -1,
  padding: 0,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
} as const;
