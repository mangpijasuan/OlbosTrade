/**
 * Market Bias Panel — Chart Intelligence Phase 1.
 *
 * Reusable bias card + multi-timeframe alignment for a symbol. Evidence only —
 * shows no buy/sell recommendation. Progressive disclosure: summary always,
 * timeframe detail on expand.
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { Panel, Button } from "./ui";

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

interface Confirmation {
  confirmation: { score: number; supporting: string[]; risk_factors: string[] };
}

type ViewLevel = "beginner" | "intermediate" | "advanced";

function setupStatus(bias: Bias, score?: number | null) {
  const macroBlocked = bias.macro_risk === "high" || bias.macro_risk === "very_high";
  if (macroBlocked) {
    return {
      label: "Blocked",
      tone: "var(--red)",
      action: "Avoid new exposure until macro risk clears",
    };
  }
  if ((score ?? 0) >= 75 && bias.bias !== "neutral") {
    return {
      label: "Confirmed",
      tone: "var(--green)",
      action: "Review evidence; still requires risk and portfolio gates",
    };
  }
  if ((score ?? 0) >= 60 && bias.bias !== "neutral") {
    return {
      label: "Ready",
      tone: "var(--amber)",
      action: "Review before Copilot consideration",
    };
  }
  if (bias.bias !== "neutral") {
    return {
      label: "Early",
      tone: "var(--accent)",
      action: "Watch for closed-bar confirmation",
    };
  }
  return {
    label: "Wait",
    tone: "var(--ink-dim)",
    action: "Wait for timeframe alignment",
  };
}

export default function MarketBiasPanel({ symbol }: { symbol: string }) {
  const [bias, setBias] = useState<Bias | null>(null);
  const [align, setAlign] = useState<Alignment | null>(null);
  const [conf, setConf] = useState<Confirmation["confirmation"] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<ViewLevel>("beginner");

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    setError(null);
    Promise.all([
      api.getMarketBias(symbol) as Promise<Bias>,
      (api.getTimeframeAlignment(symbol) as Promise<Alignment>).catch(() => null),
      (api.getConfirmation(symbol) as Promise<Confirmation>).catch(() => null),
    ]).then(([b, a, c]) => { if (alive) { setBias(b); setAlign(a); setConf(c ? c.confirmation : null); } })
      .catch((err: Error) => {
        if (alive) {
          setBias(null);
          setAlign(null);
          setConf(null);
          setError(err.message);
        }
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [symbol]);

  return (
    <Panel
      sectionStyle={{ borderRadius: 6 }}
      padding={12}
      title={`Market Bias · ${symbol}`}
      action={bias && <span style={{ fontSize: 11, color: "var(--ink-faint)" }}>~{Math.round(bias.data_freshness_s / 60)}m old</span>}
    >
        {loading && !bias ? (
          <div style={{ fontSize: 12, color: "var(--ink-dim)" }}>Loading…</div>
        ) : error ? (
          <div className="empty-state">Market bias unavailable: {error}</div>
        ) : !bias ? (
          <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>No bias available.</div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
              {(["beginner", "intermediate", "advanced"] as const).map((item) => (
                <Button
                  key={item}
                  active={view === item}
                  style={{ fontSize: 11, textTransform: "capitalize" }}
                  onClick={() => setView(item)}
                >
                  {item}
                </Button>
              ))}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
              <span style={{ fontSize: 18, fontWeight: 600, color: BIAS_TONE[bias.bias], textTransform: "capitalize" }}>{bias.bias}</span>
              <span className="tnum" style={{ fontSize: 13, color: "var(--ink-dim)" }}>{bias.confidence}/100</span>
              <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--ink-dim)" }}>{bias.timeframe_alignment}</span>
            </div>

            {(() => {
              const status = setupStatus(bias, conf?.score);
              return (
                <div className="instrument-card--flat" style={{ border: `1px solid ${status.tone}66`, padding: 10, marginBottom: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
                    <span className="kicker">Setup Status</span>
                    <span style={{ color: status.tone, fontWeight: 700, textTransform: "uppercase" }}>{status.label}</span>
                  </div>
                  <div style={{ color: "var(--ink-dim)", fontSize: 12, lineHeight: 1.65 }}>
                    Suggested next action: {status.action}
                  </div>
                </div>
              );
            })()}

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 12px", fontSize: 12, marginBottom: 8 }}>
              <Row label="Trend" value={bias.trend_state} />
              <Row label="Macro risk" value={bias.macro_risk} tone={bias.macro_risk === "high" || bias.macro_risk === "very_high" ? "var(--red)" : undefined} />
              {view !== "beginner" && (
                <>
                  <Row label="VWAP" value={bias.vwap_state} />
                  <Row label="Volatility" value={bias.volatility_state} />
                  <Row label="Rel. volume" value={bias.relative_volume_state} />
                  <Row label="Regime" value={bias.regime_fit} />
                </>
              )}
            </div>
            <div style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 4 }}>
              <span className="kicker">Evidence</span> {bias.main_evidence}
            </div>
            <div style={{ fontSize: 12, color: "var(--amber)", marginBottom: 8 }}>
              <span className="kicker" style={{ color: "var(--amber)" }}>Main risk</span> {bias.main_risk}
            </div>

            {conf && view !== "beginner" && (
              <div style={{ borderTop: "1px solid var(--line-dim)", paddingTop: 8, marginBottom: 4 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
                  <span className="kicker">Confirmation</span>
                  <span className="tnum" style={{ fontSize: 15, fontWeight: 600, color: conf.score >= 60 ? "var(--green)" : "var(--ink-dim)" }}>{conf.score}/100</span>
                </div>
                {conf.supporting.slice(0, 3).map((s, i) => (
                  <div key={i} style={{ fontSize: 12, color: "var(--ink-dim)" }}>+ {s}</div>
                ))}
                {conf.risk_factors.slice(0, 2).map((s, i) => (
                  <div key={i} style={{ fontSize: 12, color: "var(--amber)" }}>− {s}</div>
                ))}
              </div>
            )}

            {align && view === "advanced" && (
              <>
                <Button style={{ fontSize: 11 }} onClick={() => setOpen(o => !o)}>
                  {open ? "Hide" : "Show"} timeframes
                </Button>
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
    </Panel>
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
