/**
 * Market Bias Panel — Chart Intelligence Phase 1.
 *
 * Reusable bias card + multi-timeframe alignment for a symbol. Evidence only —
 * shows no buy/sell recommendation. Progressive disclosure: summary always,
 * timeframe detail on expand.
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";

interface Bias {
  symbol: string; price: number | null; bias: "bullish" | "neutral" | "bearish";
  confidence: number; trend_state: string; volatility_state: string;
  relative_volume_state: string; vwap_state: string; regime_fit: string;
  macro_risk: string; timeframe_alignment: string; main_evidence: string;
  main_risk: string; data_freshness_s: number;
}
interface TF { timeframe: string; trend: string; detail: string; }
interface Alignment {
  per_timeframe: TF[]; score: number; max_score: number;
  bullish_count: number; total: number; dominant: string; interpretation: string;
}

const BIAS_TONE: Record<string, string> = {
  bullish: "var(--green)", bearish: "var(--red)", neutral: "var(--ink-dim)",
};

function trendTone(t: string): string {
  return t === "bullish" ? "var(--green)" : t === "bearish" ? "var(--red)" : "var(--ink-dim)";
}

export default function MarketBiasPanel({ symbol }: { symbol: string }) {
  const [bias, setBias] = useState<Bias | null>(null);
  const [align, setAlign] = useState<Alignment | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    Promise.all([
      api.getMarketBias(symbol) as Promise<Bias>,
      (api.getTimeframeAlignment(symbol) as Promise<Alignment>).catch(() => null),
    ]).then(([b, a]) => { if (alive) { setBias(b); setAlign(a); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [symbol]);

  return (
    <div style={{ border: "1px solid var(--line-dim)", borderRadius: 6, background: "var(--bg-2)" }}>
      <div style={{ padding: "9px 12px", borderBottom: "1px solid var(--line-dim)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="panel-title">Market Bias · {symbol}</span>
        {bias && <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>~{Math.round(bias.data_freshness_s / 60)}m old</span>}
      </div>
      <div style={{ padding: 12 }}>
        {loading && !bias ? (
          <div style={{ fontSize: 12, color: "var(--ink-dim)" }}>Loading…</div>
        ) : !bias ? (
          <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>No bias available.</div>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
              <span style={{ fontSize: 18, fontWeight: 600, color: BIAS_TONE[bias.bias], textTransform: "capitalize" }}>{bias.bias}</span>
              <span className="tnum" style={{ fontSize: 13, color: "var(--ink-dim)" }}>{bias.confidence}/100</span>
              <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--ink-dim)" }}>{bias.timeframe_alignment}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 12px", fontSize: 12, marginBottom: 8 }}>
              <Row label="Trend" value={bias.trend_state} />
              <Row label="VWAP" value={bias.vwap_state} />
              <Row label="Volatility" value={bias.volatility_state} />
              <Row label="Rel. volume" value={bias.relative_volume_state} />
              <Row label="Regime" value={bias.regime_fit} />
              <Row label="Macro risk" value={bias.macro_risk} tone={bias.macro_risk === "high" || bias.macro_risk === "very_high" ? "var(--red)" : undefined} />
            </div>
            <div style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 4 }}>
              <span className="kicker">Evidence</span> {bias.main_evidence}
            </div>
            <div style={{ fontSize: 12, color: "var(--amber)", marginBottom: 8 }}>
              <span className="kicker" style={{ color: "var(--amber)" }}>Main risk</span> {bias.main_risk}
            </div>

            {align && (
              <>
                <button className="btn-t" style={{ fontSize: 11 }} onClick={() => setOpen(o => !o)}>
                  {open ? "Hide" : "Show"} timeframes
                </button>
                {open && (
                  <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
                    {align.per_timeframe.map(tf => (
                      <div key={tf.timeframe} style={{ display: "flex", gap: 8, fontSize: 12 }}>
                        <span className="mono" style={{ width: 34, color: "var(--ink-dim)" }}>{tf.timeframe}</span>
                        <span style={{ width: 60, color: trendTone(tf.trend), textTransform: "capitalize" }}>{tf.trend}</span>
                        <span style={{ color: "var(--ink-faint)" }}>{tf.detail}</span>
                      </div>
                    ))}
                    <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 4 }}>{align.interpretation}</div>
                  </div>
                )}
              </>
            )}
            <div style={{ fontSize: 10, color: "var(--ink-faint)", marginTop: 8, borderTop: "1px solid var(--line-dim)", paddingTop: 6 }}>
              Evidence score, not a probability. Not a buy/sell recommendation.
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
      <span style={{ color: "var(--ink-faint)" }}>{label}</span>
      <span style={{ color: tone || "var(--ink)", textTransform: "capitalize", textAlign: "right" }}>{value}</span>
    </div>
  );
}
