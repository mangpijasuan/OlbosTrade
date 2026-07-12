/**
 * SignalDivergence — explicit disclosure when two independently-sourced
 * directional signals for the same symbol disagree. This component only
 * describes the disagreement; it never decides which signal "wins" or
 * implies execution outcome. Authority is only ever stated using the
 * `authority` field already attached to each signal — if that is unknown,
 * the copy says so verbatim rather than guessing.
 */
import React from "react";

import type { SignalAttributionData } from "../types/signal";
import SignalAttribution from "./SignalAttribution";

function normalizedBucket(direction: string): "bullish" | "bearish" | "neutral" | "unknown" {
  const d = direction.toUpperCase();
  if (d === "BUY" || d === "BULLISH") return "bullish";
  if (d === "SELL" || d === "BEARISH") return "bearish";
  if (d === "HOLD" || d === "NEUTRAL") return "neutral";
  return "unknown";
}

function classify(a: SignalAttributionData, b: SignalAttributionData): {
  divergent: boolean;
  label: string;
} {
  const ba = normalizedBucket(a.direction);
  const bb = normalizedBucket(b.direction);

  if ((ba === "bullish" && bb === "bearish") || (ba === "bearish" && bb === "bullish")) {
    return { divergent: true, label: "Signal divergence" };
  }
  if ((ba === "neutral" || bb === "neutral") && ba !== bb) {
    return { divergent: true, label: "Mixed confirmation" };
  }
  if (ba === bb && a.timeframe && b.timeframe && a.timeframe !== b.timeframe) {
    return { divergent: true, label: "Timeframe disagreement" };
  }
  if (ba === "unknown" || bb === "unknown") {
    return { divergent: true, label: "Models disagree" };
  }
  return { divergent: false, label: "Aligned" };
}

function authorityNote(a: SignalAttributionData, b: SignalAttributionData): string {
  const knownA = a.authority === "execution" || a.authority === "advisory";
  const knownB = b.authority === "execution" || b.authority === "advisory";
  if (!knownA && !knownB) {
    return "Execution authority is not available from the current frontend data.";
  }
  return "This view does not determine which signal, if either, is eligible to execute — check each signal's authority above.";
}

export default function SignalDivergence({
  symbol,
  signalA,
  signalB,
}: {
  symbol: string;
  signalA: SignalAttributionData | null;
  signalB: SignalAttributionData | null;
}) {
  if (!signalA || !signalB) return null;

  const { divergent, label } = classify(signalA, signalB);
  if (!divergent) return null;

  return (
    <div
      role="status"
      aria-label={`${label} for ${symbol}`}
      style={{
        border: "1px solid rgba(245,158,11,0.45)",
        background: "rgba(245,158,11,0.08)",
        borderRadius: 4,
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span aria-hidden="true" style={{ color: "var(--amber)", fontSize: 14 }}>&#9888;</span>
        <span style={{ color: "var(--amber)", fontWeight: 700, fontSize: 12, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          {label}
        </span>
        <span className="mono" style={{ color: "var(--ink-dim)", fontSize: 11 }}>{symbol}</span>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
        <SignalAttribution data={signalA} size="sm" />
        <span aria-hidden="true" style={{ color: "var(--ink-faint)" }}>vs</span>
        <SignalAttribution data={signalB} size="sm" />
      </div>

      <div style={{ color: "var(--ink-dim)", fontSize: 11, lineHeight: 1.6 }}>
        {authorityNote(signalA, signalB)}
      </div>
    </div>
  );
}
