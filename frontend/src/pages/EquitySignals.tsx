/**
 * EquitySignals page — live signal feed with EQUITIES | OPTIONS toggle.
 * Equity cards: confidence, orderflow, IV boost, entry/stop/target.
 * Options cards: OptionsSignals (spread premium, Greeks, contracts, DTE).
 */

import React, { useEffect, useState } from "react";
import BrokerStatus from "../components/BrokerStatus";
import PortfolioGreeks from "../components/PortfolioGreeks";
import SignalAttribution from "../components/SignalAttribution";
import ConfidenceFloorLabel from "../components/ConfidenceFloorLabel";
import WhyBlockedChip from "../components/WhyBlockedChip";
import AlphaEdgeInline, { OpportunityScorePill } from "../components/AlphaEdgeInline";
import type { SignalAttributionData } from "../types/signal";
import { useDeskBlockContext } from "../hooks/useDeskBlockContext";
import { deriveSignalBlockReason } from "../utils/signalBlockReason";
import OptionsSignals from "./OptionsSignals";

export type AssetTab = "equities" | "options";

interface TradePlan {
  entry_price?: number;
  stop_price?: number;
  target_price?: number;
  target_move_pct?: number;
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
  source?: string;
  trade_plan?: TradePlan;
  indicators?: {
    rsi?: number;
    macd?: number;
    bb_pct_b?: number;
    atr?: number;
    volume_ratio?: number;
  };
  opportunity_score?: { score: number; components: Record<string, number> } | null;
}

// Signals from the same scan cycle land within a few seconds of each other
// (the backend scans the whole watchlist concurrently, not one at a time),
// but cycles themselves are ~15 minutes apart. Bucketing to a coarser
// interval than that scan spacing groups a whole cycle together instead of
// having near-simultaneous signals split arbitrarily by their few-second
// timestamp differences — "recent" should mean "which cycle", not "which
// second within a cycle".
const CYCLE_BUCKET_MS = 10 * 60 * 1000;

function cycleBucket(generatedAt: string): number {
  return Math.floor(new Date(generatedAt).getTime() / CYCLE_BUCKET_MS);
}

/** Newest scan cycle first; within the same cycle, highest confidence first.
 * Recency wins the primary sort — a high-confidence signal from three cycles
 * ago is more likely stale than useful, so it shouldn't outrank a fresh one
 * just because its own number was higher when it was generated. */
function sortRecentThenConfident(a: Signal, b: Signal): number {
  const cycleDiff = cycleBucket(b.generated_at) - cycleBucket(a.generated_at);
  if (cycleDiff !== 0) return cycleDiff;
  return b.confidence - a.confidence;
}

/** Deterministic color from the ticker string — used for the fallback
 * initials avatar so a given ticker always gets the same color, not a
 * random one on every render. */
function tickerColor(ticker: string): string {
  let hash = 0;
  for (let i = 0; i < ticker.length; i++) {
    hash = ticker.charCodeAt(i) + ((hash << 5) - hash);
  }
  return `hsl(${Math.abs(hash) % 360}, 55%, 42%)`;
}

function InitialsAvatar({ ticker, size }: { ticker: string; size: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: 6, background: tickerColor(ticker),
      display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
      fontFamily: "var(--mono)", fontSize: size * 0.36, fontWeight: 700, color: "#fff",
    }}>
      {ticker.slice(0, 2)}
    </div>
  );
}

/** Best-effort real company logo, falling back to a generated initials
 * avatar on load failure — never leaves a broken image icon, and works for
 * any ticker without needing a hand-maintained name/domain lookup table. */
function TickerLogo({ ticker, size = 28 }: { ticker: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <InitialsAvatar ticker={ticker} size={size} />;
  return (
    <img
      src={`https://companiesmarketcap.com/img/company-logos/64/${ticker}.png`}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
      style={{ borderRadius: 6, objectFit: "contain", background: "var(--bg-3)", flexShrink: 0 }}
    />
  );
}

function ConfidenceBar({ value, minConfidence }: { value: number; minConfidence: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 75 ? "var(--green)" : pct >= 62 ? "var(--cyan)" : "var(--amber)";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
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
      <ConfidenceFloorLabel confidence={value} minConfidence={minConfidence} />
    </div>
  );
}

function toAttribution(sig: Signal): SignalAttributionData {
  return {
    direction: sig.action,
    // These signals come from the background scanner (main.py), not the
    // equity_scan_engine.py-backed scan panel — read the producer's own
    // "source" field rather than guessing which engine generated it.
    source: sig.source ?? "unknown",
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

function SignalCard({
  sig,
  minConfidence,
  blockCtx,
}: {
  sig: Signal;
  minConfidence: number;
  blockCtx: ReturnType<typeof useDeskBlockContext>;
}) {
  const tp = sig.trade_plan || {};
  const ind = sig.indicators || {};
  const block = deriveSignalBlockReason(sig, blockCtx);

  return (
    <div className="instrument-card" style={{
      border: `1px solid ${sig.action === "BUY" ? "rgba(34,197,94,0.25)" :
                            sig.action === "SELL" ? "rgba(239,68,68,0.25)" :
                            "var(--line-dim)"}`,
      padding: "14px 16px",
      display: "flex",
      flexDirection: "column",
      gap: 10,
    }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <TickerLogo ticker={sig.ticker} />
        <span style={{
          color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 16, fontWeight: 700,
        }}>
          {sig.ticker}
        </span>
        <SignalAttribution data={toAttribution(sig)} size="sm" />
        <WhyBlockedChip reason={block} />
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
          <ConfidenceBar value={sig.confidence} minConfidence={minConfidence} />
        </div>
      )}

      {/* Score pills */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {sig.opportunity_score != null && (
          <OpportunityScorePill value={sig.opportunity_score.score} />
        )}
        <ScorePill label="ORDERFLOW" value={sig.orderflow_score} />
        <ScorePill label="IV BOOST" value={sig.iv_overlay_boost} />
        {ind.rsi !== undefined && <StatPill label="RSI" value={ind.rsi.toFixed(1)} />}
        {ind.volume_ratio !== undefined && <StatPill label="VOL×" value={ind.volume_ratio.toFixed(1)} />}
        {ind.bb_pct_b !== undefined && <StatPill label="BB%B" value={ind.bb_pct_b.toFixed(2)} />}
        <span style={{ flex: 1 }} />
        <AlphaEdgeInline ticker={sig.ticker} assetType="equity" />
      </div>

      {/* Trade plan */}
      {tp.entry_price && (
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
          gap: 8, background: "var(--bg-3)", borderRadius: 4, padding: "8px 12px",
        }}>
          <PriceCell label="ENTRY" value={tp.entry_price} color="var(--ink)" />
          <PriceCell label="STOP"  value={tp.stop_price}  color="var(--red)" />
          <PriceCell label="TARGET" value={tp.target_price} color="var(--green)" />
          <PriceCell label="MOVE" value={tp.target_move_pct} color="var(--amber)" suffix="%" />
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

function PriceCell({ label, value, color, suffix }: { label: string; value?: number; color: string; suffix?: "%" }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ color: "var(--ink-dim)", fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em" }}>
        {label}
      </span>
      <span style={{ color, fontFamily: "var(--mono)", fontSize: 13, fontWeight: 600 }}>
        {value === undefined ? "—" : suffix === "%" ? `${value.toFixed(1)}%` : `$${value.toFixed(2)}`}
      </span>
    </div>
  );
}

export function AssetToggle({ tab, onChange }: { tab: AssetTab; onChange: (t: AssetTab) => void }) {
  const btn = (id: AssetTab, label: string) => {
    const active = tab === id;
    return (
      <button
        type="button"
        onClick={() => onChange(id)}
        style={{
          background: active ? "var(--bg-3)" : "transparent",
          color: active ? "var(--ink)" : "var(--ink-faint)",
          border: active ? "1px solid var(--line)" : "1px solid transparent",
          borderRadius: 4,
          padding: "6px 14px",
          fontFamily: "var(--mono)",
          fontSize: 11,
          letterSpacing: "0.1em",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        {label}
      </button>
    );
  };
  return (
    <div style={{
      display: "inline-flex", gap: 4, padding: 3,
      background: "var(--bg-2)", border: "1px solid var(--line-dim)", borderRadius: 6,
    }}>
      {btn("options", "OPTIONS")}
      {btn("equities", "EQUITIES")}
    </div>
  );
}

const ACTION_GROUP_COLOR: Record<Signal["action"], string> = {
  BUY: "var(--green)",
  SELL: "var(--red)",
  HOLD: "var(--ink-dim)",
};

function SignalGroup({
  action,
  signals,
  minConfidence,
  blockCtx,
}: {
  action: Signal["action"];
  signals: Signal[];
  minConfidence: number;
  blockCtx: ReturnType<typeof useDeskBlockContext>;
}) {
  if (signals.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          color: ACTION_GROUP_COLOR[action], fontFamily: "var(--mono)", fontSize: 12,
          fontWeight: 700, letterSpacing: "0.1em",
        }}>
          {action}
        </span>
        <span style={{ color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11 }}>
          ({signals.length})
        </span>
        <div style={{ flex: 1, height: 1, background: "var(--line-dim)" }} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 12 }}>
        {signals.map(sig => (
          <SignalCard
            key={sig.id}
            sig={sig}
            minConfidence={minConfidence}
            blockCtx={blockCtx}
          />
        ))}
      </div>
    </div>
  );
}

function buildShareText(top: Signal[], label: string): string {
  const lines = top.map(sig => {
    const emoji = sig.action === "BUY" ? "🟢" : "🔴";
    const pct = Math.round(sig.confidence * 100);
    const move = sig.trade_plan?.target_move_pct;
    const moveStr = move != null ? ` · ${move.toFixed(1)}% target move` : "";
    return `${emoji} ${sig.ticker} — ${sig.action} · ${pct}% confidence${moveStr}`;
  });
  const when = new Date().toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
  return [
    `📊 Top ${label} Signals — OlbosTrade (${when})`,
    "",
    ...lines,
    "",
    "Paper trading signals — not investment advice.",
  ].join("\n");
}

function TopSignals({
  top,
  label,
  minConfidence,
  blockCtx,
}: {
  top: Signal[];
  label: string;
  minConfidence: number;
  blockCtx: ReturnType<typeof useDeskBlockContext>;
}) {
  const [copied, setCopied] = useState(false);
  if (top.length === 0) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(buildShareText(top, label));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can fail (permissions, insecure context) — the
      // button just won't flip to "Copied!"; no error worth surfacing.
    }
  };

  return (
    <div className="instrument-card" style={{
      padding: "14px 16px", display: "flex",
      flexDirection: "column", gap: 12,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{
          color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12,
          fontWeight: 700, letterSpacing: "0.1em",
        }}>
          TOP {top.length} {label}
        </span>
        <div style={{ flex: 1 }} />
        <button
          onClick={handleCopy}
          style={{
            background: copied ? "var(--green)" : "var(--bg-3)",
            color: copied ? "var(--bg)" : "var(--ink)",
            border: "1px solid var(--line-dim)", borderRadius: 4,
            padding: "5px 12px", fontFamily: "var(--mono)", fontSize: 10,
            fontWeight: 600, letterSpacing: "0.06em", cursor: "pointer",
          }}
        >
          {copied ? "COPIED ✓" : "COPY TO SHARE"}
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {top.map(sig => {
          const move = sig.trade_plan?.target_move_pct;
          const block = deriveSignalBlockReason(sig, blockCtx);
          return (
            <div key={sig.id} style={{
              display: "flex", alignItems: "center", gap: 10,
              background: "var(--bg-3)", borderRadius: 4, padding: "8px 12px",
              flexWrap: "wrap",
            }}>
              <TickerLogo ticker={sig.ticker} size={24} />
              <span style={{ color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 13, fontWeight: 700, minWidth: 56 }}>
                {sig.ticker}
              </span>
              <span style={{
                color: sig.action === "BUY" ? "var(--green)" : "var(--red)",
                fontFamily: "var(--mono)", fontSize: 11, fontWeight: 700, minWidth: 36,
              }}>
                {sig.action}
              </span>
              <div style={{ flex: 1, maxWidth: 180, minWidth: 120 }}>
                <ConfidenceBar value={sig.confidence} minConfidence={minConfidence} />
              </div>
              <WhyBlockedChip reason={block} />
              {move != null && (
                <span style={{ color: "var(--amber)", fontFamily: "var(--mono)", fontSize: 11, fontWeight: 600 }}>
                  {move.toFixed(1)}% target
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EquitySignalsGrid() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minMovePct, setMinMovePct] = useState(0);
  const blockCtx = useDeskBlockContext();
  const { minConfidence } = blockCtx;

  const loadSignals = () => {
    // Explicit limit — a single scan cycle across the equity watchlist (102
    // tickers as of the Nasdaq-100 switch) can produce one entry per
    // ticker; relying on the backend's implicit default silently truncated
    // a full cycle in the past. 150 covers the current watchlist with room
    // to grow.
    fetch("/api/equity/signals?limit=150")
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

  // Min move % only makes sense for BUY/SELL — a HOLD has no trade_plan
  // (no target price to measure a move against), so it's left out of that
  // filter entirely rather than being silently dropped by an ?? 0 default.
  const buySignals = signals
    .filter(s => s.action === "BUY" && !s.earnings_gated)
    .filter(s => (s.trade_plan?.target_move_pct ?? 0) >= minMovePct)
    .sort(sortRecentThenConfident);
  const sellSignals = signals
    .filter(s => s.action === "SELL" && !s.earnings_gated)
    .filter(s => (s.trade_plan?.target_move_pct ?? 0) >= minMovePct)
    .sort(sortRecentThenConfident);
  const holdSignals = signals
    .filter(s => s.action === "HOLD" || s.earnings_gated)
    .sort(sortRecentThenConfident);
  const actionableCount = buySignals.length + sellSignals.length;
  // Split rather than merged: a mixed top-3 can get crowded out entirely by
  // one side (e.g. three high-confidence BUYs hiding a strong SELL), so BUY
  // and SELL each get their own top-3-by-confidence ranking.
  const topBuySignals = buySignals.slice(0, 3);
  const topSellSignals = sellSignals.slice(0, 3);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div>
          <h2 style={{ margin: 0, color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 16 }}>
            EQUITY SIGNALS
          </h2>
          <p style={{ margin: "4px 0 0", color: "var(--ink-dim)", fontFamily: "var(--mono)", fontSize: 11 }}>
            {actionableCount} actionable ({buySignals.length} buy · {sellSignals.length} sell) · {signals.length} total
          </p>
        </div>
        <div style={{ flex: 1 }} />
        <label style={{
          display: "flex", alignItems: "center", gap: 6,
          fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)",
        }}>
          Min move %
          <input
            type="number"
            min={0}
            step={0.5}
            value={minMovePct || ""}
            onChange={(e) => setMinMovePct(e.target.value ? parseFloat(e.target.value) : 0)}
            placeholder="0"
            title="Only show signals whose target price implies at least this % move from entry"
            style={{
              width: 56, background: "var(--bg-2)", border: "1px solid var(--line-dim)",
              borderRadius: 4, padding: "5px 8px", color: "var(--ink)", fontFamily: "var(--mono)",
              fontSize: 11,
            }}
          />
        </label>
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

      {error && (
        <div style={{
          background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
          borderRadius: 4, padding: "10px 14px",
          fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)",
        }}>
          {error}
        </div>
      )}

      {signals.length === 0 ? (
        <div style={{
          color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 12,
          textAlign: "center", padding: 40,
        }}>
          No signals yet. Click RUN SCAN to generate equity signals.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
            <TopSignals top={topBuySignals} label="BUY" minConfidence={minConfidence} blockCtx={blockCtx} />
            <TopSignals top={topSellSignals} label="SELL" minConfidence={minConfidence} blockCtx={blockCtx} />
          </div>
          <SignalGroup action="BUY" signals={buySignals} minConfidence={minConfidence} blockCtx={blockCtx} />
          <SignalGroup action="SELL" signals={sellSignals} minConfidence={minConfidence} blockCtx={blockCtx} />
          <SignalGroup action="HOLD" signals={holdSignals} minConfidence={minConfidence} blockCtx={blockCtx} />
        </div>
      )}
    </div>
  );
}

export default function EquitySignals() {
  const [tab, setTab] = useState<AssetTab>("equities");

  return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16, maxWidth: 1200 }}>
      <div style={{ display: "flex", alignItems: "stretch", gap: 12, flexWrap: "wrap" }}>
        <AssetToggle tab={tab} onChange={setTab} />
        <div style={{ flex: 1, minWidth: 220 }}><BrokerStatus /></div>
        <div style={{ flex: 1, minWidth: 220 }}><PortfolioGreeks /></div>
      </div>

      {tab === "equities" ? <EquitySignalsGrid /> : <OptionsSignals />}
    </div>
  );
}
