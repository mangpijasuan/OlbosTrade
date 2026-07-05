/**
 * Multi-Timeframe Alignment Panel — Chart Intelligence Phase 1.
 *
 * Read-only evidence panel. It explains agreement across closed-bar
 * timeframes and does not create orders, alerts, or recommendations.
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { Panel } from "./ui";

interface TimeframeState {
  timeframe: string;
  trend: "bullish" | "neutral" | "bearish";
  price_vs_ema: string;
  higher_highs_lows: boolean;
  detail: string;
}

interface Alignment {
  per_timeframe: TimeframeState[];
  score: number;
  max_score: number;
  bullish_count: number;
  bearish_count: number;
  total: number;
  dominant: "bullish" | "neutral" | "bearish";
  interpretation: string;
}

const TREND_TONE: Record<string, string> = {
  bullish: "var(--green)",
  bearish: "var(--red)",
  neutral: "var(--ink-dim)",
};

function pct(score: number, maxScore: number) {
  if (!maxScore) return 0;
  return Math.max(0, Math.min(100, Math.round((score / maxScore) * 100)));
}

export default function TimeframeAlignmentPanel({
  symbol,
  strategy = "default",
}: {
  symbol: string;
  strategy?: string;
}) {
  const [alignment, setAlignment] = useState<Alignment | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    setError(null);
    (api.getTimeframeAlignment(symbol, strategy) as Promise<Alignment>)
      .then((data) => {
        if (alive) setAlignment(data);
      })
      .catch((err: Error) => {
        if (alive) {
          setAlignment(null);
          setError(err.message);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [symbol, strategy]);

  const agreementPct = alignment ? pct(alignment.score, alignment.max_score) : 0;

  return (
    <Panel
      title="Multi-Timeframe Alignment"
      action={<span className="kicker">{strategy.replace(/_/g, " ")}</span>}
    >
      {loading && !alignment ? (
        <div className="empty-state">Loading timeframe evidence...</div>
      ) : error ? (
        <div className="empty-state">Alignment unavailable: {error}</div>
      ) : !alignment ? (
        <div className="empty-state">No alignment evidence available.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontSize: 24, fontWeight: 700, color: TREND_TONE[alignment.dominant], textTransform: "capitalize" }}>
              {alignment.dominant}
            </span>
            <span className="tnum" style={{ color: "var(--ink-dim)" }}>
              {alignment.bullish_count} bullish / {alignment.bearish_count} bearish / {alignment.total} total
            </span>
            <span className="tnum" style={{ marginLeft: "auto", color: "var(--amber)" }}>
              {agreementPct}%
            </span>
          </div>

          <div className="bar-track" aria-label={`Alignment strength ${agreementPct}%`}>
            <div
              className="bar-fill"
              style={{ width: `${agreementPct}%`, background: TREND_TONE[alignment.dominant] }}
            />
          </div>

          <div className="chart-intel-timeframes">
            {alignment.per_timeframe.map((tf) => (
              <div key={tf.timeframe} className="chart-intel-tf">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                  <span className="mono" style={{ color: "var(--ink)", fontWeight: 700 }}>{tf.timeframe}</span>
                  <span style={{ color: TREND_TONE[tf.trend], textTransform: "uppercase", fontSize: 11 }}>
                    {tf.trend}
                  </span>
                </div>
                <div style={{ color: "var(--ink-dim)", fontSize: 12, lineHeight: 1.55 }}>
                  {tf.detail}
                </div>
                <div style={{ color: "var(--ink-faint)", fontSize: 11, marginTop: 6 }}>
                  EMA {tf.price_vs_ema} · HH/HL {tf.higher_highs_lows ? "yes" : "no"}
                </div>
              </div>
            ))}
          </div>

          <div style={{ color: "var(--ink-dim)", fontSize: 12, lineHeight: 1.7 }}>
            {alignment.interpretation}
          </div>
        </div>
      )}
    </Panel>
  );
}
