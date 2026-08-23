/**
 * [BACKTEST] [REPLAY] [HISTORY] — additive per-signal buttons for
 * EquitySignals.tsx / OptionsSignals.tsx cards.
 *
 * BACKTEST runs the real walk-forward backtester (equity: any ticker via
 * POST /api/backtest/run-equity; options: the signal's own spread strategy
 * via the existing POST /api/backtest/run, which is SPY-only — the button
 * says so rather than silently backtesting the wrong underlying).
 * REPLAY / HISTORY deep-link via the existing TerminalNavContext to the
 * already-built Trade Replay and Signal History tools — no new pages.
 */
import React, { useState } from "react";
import { useBacktest } from "../hooks/useBacktest";
import { useTerminalNav } from "./TerminalNavContext";

function sixMonthsAgo(): string {
  const d = new Date();
  d.setMonth(d.getMonth() - 6);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

const btnStyle: React.CSSProperties = {
  background: "transparent", border: "1px solid var(--line-dim)", borderRadius: 3,
  padding: "2px 8px", fontSize: 9, letterSpacing: "0.08em", color: "var(--ink-dim)",
  cursor: "pointer", fontFamily: "var(--mono)",
};

const pct = (v: any) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—");
const num = (v: any, d = 2) => (typeof v === "number" ? v.toFixed(d) : "—");

function ResultsStrip({ results }: { results: any }) {
  const done = results?.status === "completed";
  const failed = results?.status === "failed";
  if (failed) {
    return (
      <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--red)" }}>
        ⚠ {results.error || "backtest failed"}
      </div>
    );
  }
  if (!done) {
    return (
      <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--amber)" }}>
        RUNNING… ({results?.status || "queued"})
      </div>
    );
  }
  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontFamily: "var(--mono)", fontSize: 9 }}>
      <span style={{ color: "var(--ink-dim)" }}>RETURN <b style={{ color: (results.total_return_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{pct(results.total_return_pct)}</b></span>
      <span style={{ color: "var(--ink-dim)" }}>SHARPE <b style={{ color: "var(--ink)" }}>{num(results.sharpe_ratio)}</b></span>
      <span style={{ color: "var(--ink-dim)" }}>WIN RATE <b style={{ color: "var(--ink)" }}>{pct(results.win_rate)}</b></span>
      <span style={{ color: "var(--ink-dim)" }}>MAX DD <b style={{ color: "var(--red)" }}>{pct(results.max_drawdown_pct)}</b></span>
      <span style={{ color: "var(--ink-dim)" }}>TRADES <b style={{ color: "var(--ink)" }}>{results.total_trades ?? 0}</b></span>
    </div>
  );
}

interface BacktestButtonsProps {
  ticker: string;
  assetType: "equity" | "options";
  strategy?: string;   // options only — the signal's own spread strategy name
}

export default function BacktestButtons({ ticker, assetType, strategy }: BacktestButtonsProps) {
  const { loading, results, error, runBacktest, runEquityBacktest } = useBacktest();
  const [expanded, setExpanded] = useState(false);
  const nav = useTerminalNav();

  const optionsSpyOnly = assetType === "options" && ticker.toUpperCase() !== "SPY";

  const runIt = () => {
    setExpanded(true);
    if (assetType === "equity") {
      runEquityBacktest({ ticker, start_date: sixMonthsAgo(), end_date: today() });
    } else if (strategy) {
      runBacktest({ strategy, start_date: sixMonthsAgo(), end_date: today() });
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
      <div style={{ display: "flex", gap: 6 }}>
        <button
          onClick={runIt}
          disabled={loading || (assetType === "options" && !strategy) || optionsSpyOnly}
          style={{ ...btnStyle, opacity: (loading || optionsSpyOnly) ? 0.5 : 1, cursor: optionsSpyOnly ? "not-allowed" : "pointer" }}
          title={optionsSpyOnly ? "The options backtester currently only supports SPY" : undefined}
        >
          {loading ? "RUNNING…" : optionsSpyOnly ? "BACKTEST (SPY ONLY)" : "BACKTEST"}
        </button>
        <button onClick={() => nav("trade:replay")} style={btnStyle}>REPLAY</button>
        <button onClick={() => nav("strat:signal-history")} style={btnStyle}>HISTORY</button>
      </div>
      {expanded && (results || error) && (
        <div style={{ background: "var(--bg-3)", borderRadius: 3, padding: "5px 10px" }}>
          {error ? (
            <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--red)" }}>⚠ {error}</span>
          ) : (
            <ResultsStrip results={results} />
          )}
        </div>
      )}
    </div>
  );
}
