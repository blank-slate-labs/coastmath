import { useCallback, useMemo } from "react";

import AssumptionCurveEditor from "@/components/assumption_curve_editor";
import { usePlanStore } from "@/stores/plan_store";
import * as api from "@/api/client";
import type { ControlPoint, CurveMode } from "@/types/plan";

interface PresetConfig {
  label: string;
  points: (startAge: number, endAge: number) => ControlPoint[];
}

const PRESETS: PresetConfig[] = [
  {
    label: "Aggressive (10% \u2192 40%)",
    points: (s, e) => [
      { x: s, y: 0.1 },
      { x: e, y: 0.4 },
    ],
  },
  {
    label: "Moderate (20% \u2192 60%)",
    points: (s, e) => [
      { x: s, y: 0.2 },
      { x: e, y: 0.6 },
    ],
  },
  {
    label: "Conservative (40% \u2192 80%)",
    points: (s, e) => [
      { x: s, y: 0.4 },
      { x: e, y: 0.8 },
    ],
  },
  {
    label: "Target Date",
    points: (s, e) => {
      const mid = Math.round((s + e) / 2);
      return [
        { x: s, y: 0.1 },
        { x: mid, y: 0.4 },
        { x: e, y: 0.7 },
      ];
    },
  },
];

export default function BondGlidePathEditor() {
  const plan = usePlanStore((s) => s.plan);
  const loadPlan = usePlanStore((s) => s.loadPlan);

  const curve = useMemo(
    () => plan?.assumption_curves.find((c) => c.curve_type === "bond_allocation") ?? null,
    [plan],
  );

  const startAge = plan ? new Date().getFullYear() - plan.birth_year : 30;
  const endAge = plan?.life_expectancy ?? 95;

  const persist = useCallback(
    async (update: {
      mode?: CurveMode;
      fixedRate?: number | null;
      controlPoints?: ControlPoint[];
    }) => {
      if (!plan) return;
      const payload = {
        curve_type: "bond_allocation" as const,
        ...(update.mode !== undefined && { mode: update.mode }),
        ...(update.fixedRate !== undefined && { fixed_rate: update.fixedRate }),
        ...(update.controlPoints !== undefined && {
          control_points: update.controlPoints,
        }),
      };
      if (curve) {
        await api.updateAssumption(plan.id, curve.id, payload);
      } else {
        await api.createAssumption(plan.id, {
          ...payload,
          mode: update.mode ?? "curve",
          control_points: update.controlPoints ?? [
            { x: startAge, y: 0.2 },
            { x: endAge, y: 0.6 },
          ],
        });
      }
      await loadPlan(plan.id);
    },
    [plan, curve, loadPlan, startAge, endAge],
  );

  const handlePreset = useCallback(
    (idx: number) => {
      const preset = PRESETS[idx];
      if (!preset) return;
      const points = preset.points(startAge, endAge);
      persist({ mode: "curve", controlPoints: points });
    },
    [startAge, endAge, persist],
  );

  if (!plan) return null;

  return (
    <div data-testid="bond-glide-path-editor">
      {/* Presets dropdown */}
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: "#333" }} htmlFor="bond-preset">
          Preset:{" "}
        </label>
        <select
          id="bond-preset"
          data-testid="preset-select"
          defaultValue=""
          onChange={(e) => {
            const idx = parseInt(e.target.value, 10);
            if (!isNaN(idx)) handlePreset(idx);
            e.target.value = "";
          }}
          style={{
            fontSize: 12,
            padding: "4px 8px",
            border: "1px solid #ccc",
            borderRadius: 4,
          }}
        >
          <option value="" disabled>
            Select a preset...
          </option>
          {PRESETS.map((p, i) => (
            <option key={p.label} value={i}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      <AssumptionCurveEditor
        curveType="bond_allocation"
        mode={curve?.mode ?? "curve"}
        fixedRate={curve?.fixed_rate ?? null}
        controlPoints={
          curve?.control_points ?? [
            { x: startAge, y: 0.2 },
            { x: endAge, y: 0.6 },
          ]
        }
        onChange={persist}
        minAge={startAge}
        maxAge={endAge}
        minValue={0}
        maxValue={1}
        label="Bond Allocation Glide Path"
      />
    </div>
  );
}
