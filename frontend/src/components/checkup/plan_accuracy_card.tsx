import { useEffect, useRef, useState } from "react";

import type { PlanSectionKey } from "@/pages/plan_setup";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import type { PlanCheckItem, PlanChecksResponse } from "@/types/plan";
import "./plan_accuracy_card.css";

const RING_RADIUS = 26;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/** Server score as a ring; the figure carries the number. */
function ScoreRing({ score }: { score: number }) {
  const filled = (Math.max(0, Math.min(100, score)) / 100) * RING_CIRCUMFERENCE;
  return (
    <svg
      className="plan-accuracy-ring"
      viewBox="0 0 64 64"
      width={64}
      height={64}
      role="img"
      aria-label={`Plan accuracy ${score} of 100`}
    >
      <circle cx={32} cy={32} r={RING_RADIUS} className="plan-accuracy-ring-track" />
      <circle
        cx={32}
        cy={32}
        r={RING_RADIUS}
        className="plan-accuracy-ring-fill"
        strokeDasharray={`${filled} ${RING_CIRCUMFERENCE}`}
        transform="rotate(-90 32 32)"
      />
    </svg>
  );
}

function ItemList({
  label,
  items,
  onEditSection,
}: {
  label: string;
  items: PlanCheckItem[];
  onEditSection: (key: PlanSectionKey) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="plan-accuracy-group">
      <h4>{label}</h4>
      <ul aria-label={label}>
        {items.map((item) => (
          <li key={`${item.key}:${item.target_id ?? item.person ?? ""}`}>
            <button
              type="button"
              className="btn-ghost plan-accuracy-item"
              data-sample-view
              onClick={() => onEditSection(item.section)}
            >
              <span>{item.title}</span>
              <span aria-hidden="true">›</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Plan accuracy: a server-scored completeness figure and the inputs that would change it. */
export default function PlanAccuracyCard({
  onEditSection,
}: {
  onEditSection: (key: PlanSectionKey) => void;
}) {
  const { adapter } = useStorage();
  const planId = usePlanStore((s) => s.plan?.id);
  const simulation = usePlanStore((s) => s.simulation);
  const isSimulating = usePlanStore((s) => s.isSimulating);
  const [result, setResult] = useState<{ planId: string; data: PlanChecksResponse } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const request = useRef(0);

  // Reload when the tab opens and after every projection refresh, which follows each saved edit.
  useEffect(() => {
    if (!planId || isSimulating) return;
    const current = ++request.current;
    setLoading(true);
    setError(false);
    adapter
      .runPlanChecks(planId)
      .then(
        (data) => {
          if (request.current === current) setResult({ planId, data });
        },
        () => {
          if (request.current === current) setError(true);
        },
      )
      .finally(() => {
        if (request.current === current) setLoading(false);
      });
    return () => {
      request.current += 1;
    };
  }, [adapter, planId, simulation, isSimulating, attempt]);

  if (!planId) return null;
  const data = result?.planId === planId ? result.data : null;
  const missing = data?.items.filter((item) => item.kind === "missing") ?? [];
  const review = data?.items.filter((item) => item.kind === "review") ?? [];

  return (
    <section
      className="card plan-accuracy"
      aria-busy={loading || isSimulating}
      aria-labelledby="plan-accuracy-title"
    >
      <div className="plan-accuracy-head">
        {data && <ScoreRing score={data.score} />}
        <div>
          <h3 id="plan-accuracy-title">Plan accuracy</h3>
          {data && (
            <p className="plan-accuracy-figure">
              <strong>{data.score}</strong>
              <span>/100</span>
            </p>
          )}
          {!data && !error && <p className="plan-accuracy-count">Checking…</p>}
        </div>
      </div>
      {error && (
        <p role="alert" className="plan-accuracy-error">
          Could not check this plan.{" "}
          <button
            type="button"
            className="btn-secondary"
            disabled={loading}
            onClick={() => setAttempt((n) => n + 1)}
          >
            Try again
          </button>
        </p>
      )}
      {data && <ItemList label="Missing" items={missing} onEditSection={onEditSection} />}
      {data && <ItemList label="Review" items={review} onEditSection={onEditSection} />}
    </section>
  );
}
