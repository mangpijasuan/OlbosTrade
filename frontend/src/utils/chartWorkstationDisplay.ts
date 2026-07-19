/**
 * Pure display helpers for ChartWorkstation trust labels (Phase 1).
 * Kept free of React so Vitest can cover the honesty rules without mounting the page.
 */
import type { SignalAttributionData } from "../types/signal";

export type ExecMode = "manual" | "copilot" | "autopilot";

export function formatExecutionModeDisplay(
  mode: ExecMode | string | null | undefined,
  killActive: boolean,
): { label: string; value: string; tone: string } {
  if (killActive) {
    return { label: "Execution mode", value: "HALTED", tone: "var(--red)" };
  }
  const normalized = (mode === "copilot" || mode === "autopilot" || mode === "manual")
    ? mode
    : "manual";
  if (normalized === "autopilot") {
    return { label: "Execution mode", value: "AUTOPILOT", tone: "var(--amber)" };
  }
  if (normalized === "copilot") {
    return { label: "Execution mode", value: "COPILOT", tone: "var(--cyan)" };
  }
  return { label: "Execution mode", value: "MANUAL", tone: "var(--ink-dim)" };
}

export function chartLevelColors() {
  return {
    entry: "var(--amber)",
    target: "var(--red)",
    support: "var(--cyan)",
    resistance: "#a78bfa", // distinct from entry amber — not a CSS token yet
  };
}

export function tradePlanCardTitle(hasSelectedSignal: boolean, source?: string | null): string {
  if (!hasSelectedSignal) return "Chart levels";
  if (source && source !== "unknown") return "Trade plan";
  return "Trade plan";
}

type ChartSignalLike = {
  action: string;
  confidence: number;
  generated_at?: string;
  source?: string | null;
};

/** Map a chart / equity-signals payload into SignalAttribution — never invent source. */
export function toChartSignalAttribution(sig: ChartSignalLike): SignalAttributionData {
  return {
    direction: sig.action,
    source: sig.source ?? "unknown",
    timeframe: null,
    confidence: sig.action !== "HOLD" ? sig.confidence : null,
    updatedAt: sig.generated_at ?? null,
    authority: "unknown",
  };
}
