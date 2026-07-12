/**
 * EquitySignals page — displays equity signal cards with confidence, orderflow,
 * IV overlay boost, and entry/stop/target levels.
 */

import React, { useEffect, useState } from "react";
import BrokerStatus from "../components/BrokerStatus";
import PortfolioGreeks from "../components/PortfolioGreeks";
import SignalAttribution from "../components/SignalAttribution";
import type { SignalAttributionData } from "../types/signal";

interface TradePlan {
  entry_price?: number;
  stop_price?: number;
  target_price?: number;
  shares?: number;
  risk_reward?: number;
  risk_dollars?: number;
}

interface Signal {
  id: string;
  ticker: string;
  generated_at: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  orderflow_score: number;
  iv_overlay_boost: number;
  earnings_gated: boolean;
  reason?: string;
  trade_plan?: TradePlan;
  indicators?: {
    rsi?: number;
    macd?: number;
    bb_pct_b?: number;
    atr?: number;
    volume_ratio?: number;
  };
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 75 ? "var(--green)" : pct >= 62 ? "var(--cyan)" : "var(--amber)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{
        flex: 1, height: 4, background: "var(--bg-4)", borderRadius: 2, overflow: "hidden",
      }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ color, fontFamily: "var(--mono)", fontSize: 11, fontWeight: 600, minWidth: 36 }}>
        {pct}%
      </span>
    </div>
  );
}

function toAttribution(sig: Signal): SignalAttributionData {
  return {
    direction: sig.action,
    source: "Equity Scan Engine",
    // Repository verified: /api/equity/signals does not return a bar-timeframe
    // field on the signal payload — do not fabricate one.
    timeframe: null,
    confidence: sig.action !== "HOLD" ? sig.confidence : null,
    updatedAt: sig.generated_at,
    // This page has no execute/approve control of its own (unlike the scan
    // panels), and there's no verified lineage from this payload to
    // AUTOPILOT here — authority is left unknown rather than guessed.
    authority: "unknown",
  };
}

function SignalCard({ sig }: { sig: Signal }) {
  const tp = sig.trade_plan || {};
  const ind = sig.indicators || {};

  return (
    <div style={{
      background: "var(--bg-2)",
      border: `1px solid ${sig.action === "BUY" ? "rgba(34,197,94,0.25)" :
                            sig.action === "SELL" ? "rgba(239,68,68,0.25)" :
                            "var(--line-dim)"}`,
      borderRadius: 6,
      padding: "14px 16px",
      display: "flex",
      flexDirection: "column",
      gap: 10,
    }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{
          color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 16, fontWeight: 700,
        }}>
          {sig.ticker}
        </span>
        <SignalAttribution data={toAttribution(sig)} size="sm" />
        {sig.earnings_gated && (
          <span style={{
            color: "var(--amber)", border: "1px solid var(--amber)",
            borderRadius: 3, padding: "2px 6px", fontSize: 9, letterSpacing: "0.1em",
          }}>
            EARNINGS GATE
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span style={{
          color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 9,
        }}>
          {new Date(sig.generated_at).toLocaleTimeString()}
        </span>
      </div>

      {/* Confidence */}
      {sig.action !== "HOLD" && (
        <div>
          <div style={{ color: "var(--ink-dim)", fontSize: 9, fontFamily: "var(--mono)", marginBottom: 4, letterSpacing: "0.08em" }}>
            CONFIDENCE
          </div>
          <ConfidenceBar value={sig.confidence} />
        </div>
      )}

      {/* Score pills */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <ScorePill label="ORDERFLOW" value={sig.orderflow_score} />
        <ScorePill label="IV BOOST" value={sig.iv_overlay_boost} />
        {ind.rsi !== undefined && <StatPill label="RSI" value={ind.rsi.toFixed(1)} />}
        {ind.volume_ratio !== undefined && <StatPill label="VOL×" value={ind.volume_ratio.toFixed(1)} />}
        {ind.bb_pct_b !== undefined && <StatPill label="BB%B" value={ind.bb_pct_b.toFixed(2)} />}
      </div>

      {/* Trade plan */}
      {tp.entry_price && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
          gap: 8, background: "var(--bg-3)", borderRadius: 4, padding: "8px 12px",
        }}>
          <PriceCell label="ENTRY" value={tp.entry_price} color="var(--ink)" />
          <PriceCell label="STOP"  value={tp.stop_price}  color="var(--red)" />
          <PriceCell label="TARGET" value={tp.target_price} color="var(--green)" />
          {tp.shares !== undefined && (
            <div style={{ gridColumn: "1/-1", display: "flex", gap: 16,
              fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)", marginTop: 4 }}>
              <span>SHARES: <b style={{color:"var(--ink)"}}>{tp.shares}</b></span>
              {tp.risk_reward !== undefined && (
                <span>R:R <b style={{color:"var(--cyan)"}}>{tp.risk_reward.toFixed(2)}x</b></span>
              )}
              {tp.risk_dollars !== undefined && (
                <span>RISK <b style={{color:"var(--amber)"}}>${tp.risk_dollars.toFixed(0)}</b></span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ScorePill({ label, value }: { label: string; value: number }) {
  const color = value > 0.1 ? "var(--green)" : value < -0.1 ? "var(--red)" : "var(--ink-faint)";
  return (
    <div style={{
      background: "var(--bg-3)", borderRadius: 3, padding: "3px 8px",
      fontFamily: "var(--mono)", fontSize: 9, display: "flex", gap: 5, alignItems: "center",
    }}>
      <span style={{ color: "var(--ink-dim)", letterSpacing: "0.08em" }}>{label}</span>
      <span style={{ color, fontWeight: 600 }}>
        {value >= 0 ? "+" : ""}{value.toFixed(3)}
      </span>
    </div>
  );
}

function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      background: "var(--bg-3)", borderRadius: 3, padding: "3px 8px",
      fontFamily: "var(--mono)", fontSize: 9, display: "flex", gap: 5, alignItems: "center",
    }}>
      <span style={{ color: "var(--ink-dim)", letterSpacing: "0.08em" }}>{label}</span>
      <span style={{ color: "var(--ink)", fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function PriceCell({ label, value, color }: { label: string; value?: number; color: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ color: "var(--ink-dim)", fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em" }}>
        {label}
      </span>
      <span style={{ color, fontFamily: "var(--mono)", fontSize: 13, fontWeight: 600 }}>
        {value !== undefined ? `$${value.toFixed(2)}` : "—"}
      </span>
    </div>
  );
}

export default function EquitySignals() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSignals = () => {
    fetch("/api/equity/signals")
      .then(r => r.json())
      .then(d => setSignals(d.signals || []))
      .catch(e => setError(String(e)));
  };

  useEffect(() => {
    loadSignals();
    const t = setInterval(loadSignals, 60000);
    return () => clearInterval(t);
  }, []);

  const runScan = async () => {
    setScanning(true);
    setError(null);
    try {
      await fetch("/api/equity/scan", { method: "POST" });
      loadSignals();
    } catch (e) {
      setError(String(e));
    } finally {
      setScanning(false);
    }
  };

  const actionable = signals.filter(s => s.action !== "HOLD" && !s.earnings_gated);

  return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16, maxWidth: 1200 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div>
          <h2 style={{ margin: 0, color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 16 }}>
            EQUITY SIGNALS
          </h2>
          <p style={{ margin: "4px 0 0", color: "var(--ink-dim)", fontFamily: "var(--mono)", fontSize: 11 }}>
            {actionable.length} actionable · {signals.length} total
          </p>
        </div>
        <div style={{ flex: 1 }} />
        <button
          onClick={runScan}
          disabled={scanning}
          style={{
            background: scanning ? "var(--bg-3)" : "var(--cyan)",
            color: scanning ? "var(--ink-faint)" : "var(--bg)",
            border: "none", borderRadius: 4,
            padding: "8px 16px",
            fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.08em",
            cursor: scanning ? "default" : "pointer",
            fontWeight: 600,
          }}
        >
          {scanning ? "SCANNING..." : "RUN SCAN"}
        </button>
      </div>

      {/* Broker + Greeks */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <BrokerStatus />
        <PortfolioGreeks />
      </div>

      {error && (
        <div style={{
          background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
          borderRadius: 4, padding: "10px 14px",
          fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)",
        }}>
          {error}
        </div>
      )}

      {/* Signal cards — actionable first */}
      {signals.length === 0 ? (
        <div style={{
          color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 12,
          textAlign: "center", padding: 40,
        }}>
          No signals yet. Click RUN SCAN to generate equity signals.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 12 }}>
          {[...actionable, ...signals.filter(s => s.action === "HOLD" || s.earnings_gated)]
            .map(sig => <SignalCard key={sig.id} sig={sig} />)
          }
        </div>
      )}
    </div>
  );
}
