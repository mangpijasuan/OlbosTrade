import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MetricHint, { METRIC_HINTS, resolveMetricHint, metricHintKey } from "../MetricHint";

describe("MetricHint glossary", () => {
  it("resolves known metrics case-insensitively", () => {
    expect(resolveMetricHint("Sharpe")).toBe(METRIC_HINTS.sharpe);
    expect(resolveMetricHint("POP")).toBe(METRIC_HINTS.pop);
    expect(resolveMetricHint("Consec. Loss")).toBe(METRIC_HINTS["consecutive losses"]);
    expect(metricHintKey("  Max DD ")).toBe("max dd");
  });

  it("returns undefined for unknown labels", () => {
    expect(resolveMetricHint("Totally Fake Metric")).toBeUndefined();
  });

  it("renders a title tooltip for known metrics", () => {
    render(<MetricHint id="kelly" />);
    const el = screen.getByText("Kelly");
    expect(el.getAttribute("title")).toMatch(/bankroll/i);
  });

  it("humanizes consecutive-loss label from Consec. Loss", () => {
    render(<MetricHint id="Consec. Loss" />);
    expect(screen.getByText("Consecutive losses")).toBeInTheDocument();
  });
});
