import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import * as fs from "fs";
import * as path from "path";

import AssumptionCurveEditor from "./assumption_curve_editor";
import type { AssumptionCurveEditorProps } from "./assumption_curve_editor";
import type { ControlPoint } from "@/types/plan";

const defaultPoints: ControlPoint[] = [
  { x: 30, y: 0.07 },
  { x: 50, y: 0.05 },
  { x: 70, y: 0.03 },
];

function renderEditor(overrides: Partial<AssumptionCurveEditorProps> = {}) {
  const onChange = vi.fn();
  const props: AssumptionCurveEditorProps = {
    curveType: "market_return",
    mode: "curve",
    fixedRate: 0.07,
    controlPoints: defaultPoints,
    onChange,
    minAge: 20,
    maxAge: 90,
    minValue: 0,
    maxValue: 0.15,
    label: "Market Return",
    ...overrides,
  };
  const result = render(<AssumptionCurveEditor {...props} />);
  return { ...result, onChange, props };
}

describe("AssumptionCurveEditor", () => {
  it("renders label and mode toggle buttons", () => {
    renderEditor();
    expect(screen.getByText("Market Return")).toBeInTheDocument();
    expect(screen.getByTestId("mode-fixed")).toBeInTheDocument();
    expect(screen.getByTestId("mode-curve")).toBeInTheDocument();
  });

  it("renders SVG canvas in curve mode", () => {
    renderEditor({ mode: "curve" });
    expect(screen.getByTestId("curve-svg")).toBeInTheDocument();
    // Should render all 3 control points
    expect(screen.getByTestId("control-point-0")).toBeInTheDocument();
    expect(screen.getByTestId("control-point-1")).toBeInTheDocument();
    expect(screen.getByTestId("control-point-2")).toBeInTheDocument();
  });

  it("renders numeric input in fixed mode", () => {
    renderEditor({ mode: "fixed" });
    const input = screen.getByTestId("fixed-rate-input") as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe("7");
    // SVG should not be rendered
    expect(screen.queryByTestId("curve-svg")).not.toBeInTheDocument();
  });

  it("calls onChange with mode when mode button clicked", () => {
    const { onChange } = renderEditor({ mode: "curve" });
    fireEvent.click(screen.getByTestId("mode-fixed"));
    expect(onChange).toHaveBeenCalledWith({ mode: "fixed" });
  });

  it("calls onChange with fixedRate when input changes", () => {
    const { onChange } = renderEditor({ mode: "fixed" });
    const input = screen.getByTestId("fixed-rate-input");
    fireEvent.change(input, { target: { value: "5" } });
    expect(onChange).toHaveBeenCalledWith({ fixedRate: 0.05 });
  });

  it("renders correct number of control points", () => {
    const pts: ControlPoint[] = [
      { x: 25, y: 0.08 },
      { x: 65, y: 0.04 },
    ];
    renderEditor({ controlPoints: pts });
    expect(screen.getByTestId("control-point-0")).toBeInTheDocument();
    expect(screen.getByTestId("control-point-1")).toBeInTheDocument();
    expect(screen.queryByTestId("control-point-2")).not.toBeInTheDocument();
  });

  it("does not use D3 DOM manipulation (d3.select / d3.append)", () => {
    const source = fs.readFileSync(
      path.resolve(__dirname, "./assumption_curve_editor.tsx"),
      "utf-8",
    );
    expect(source).not.toMatch(/d3\.select/);
    expect(source).not.toMatch(/d3\.append/);
    expect(source).not.toMatch(/\.select\s*\(/);
    expect(source).not.toMatch(/\.append\s*\(\s*["']/);
  });
});
