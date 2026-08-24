/**
 * Bar-by-bar signal replay — steps through run_equity()'s bar_log (one
 * entry per trading day: indicators/action/confidence the model saw, plus
 * trade_fired/position_open/portfolio_value) with PLAY/PAUSE/NEXT/PREV,
 * driving a cursor on TradeMarkerChart so the reader can see exactly what
 * the engine saw on the day it acted (or chose not to).
 */
import React, { useEffect, useRef, useState } from "react";
import TradeMarkerChart from "./TradeMarkerChart";

interface BarLogIndicators {
  rsi?: number | null;
  macd?: number | null;
  bb_pct_b?: number | null;
  atr?: number | null;
  volume_ratio?: number | null;
}

interface BarLogEntry {
  date: string;
  close: number;
  indicators: BarLogIndicators | null;
  action: string;
  confidence: number | null;
  trade_fired: boolean;
  position_open: boolean;
  portfolio_value: number;
}

interface TradeRow {
  entry_date: string;
  exit_date: string;
  direction: string; // "BUY" | "SELL"
  entry_price: number;
  exit_price: number;
}

const btnStyle: React.CSSProperties = {
  background: "transparent", border: "1px solid var(--line-dim)", borderRadius: 3,
  padding: "2px 10px", fontSize: 9, letterSpacing: "0.08em", color: "var(--ink-dim)",
  cursor: "pointer", fontFamily: "var(--mono)",
};

const PLAY_INTERVAL_MS = 400;

const num = (v: any, d = 2) => (typeof v === "number" ? v.toFixed(d) : "—");

export default function BarReplayPanel({
  barLog, trades,
}: { barLog: BarLogEntry[]; trades?: TradeRow[] }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (playing) {
      intervalRef.current = setInterval(() => {
        setCurrentIndex((i) => {
          const next = Math.min(i + 1, barLog.length - 1);
          if (next >= barLog.length - 1) setPlaying(false);
          return next;
        });
      }, PLAY_INTERVAL_MS);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [playing, barLog.length]);

  if (!barLog.length) return null;

  const safeIndex = Math.min(currentIndex, barLog.length - 1);
  const bar = barLog[safeIndex];

  const bars = barLog.map((b) => ({ date: b.date, close: b.close }));
  const equityCurve = barLog.map((b) => ({ date: b.date, value: b.portfolio_value }));
  const markers = (trades || []).flatMap((t) => {
    const entryUp = t.direction === "BUY";
    const out: { date: string; action: "BUY" | "SELL"; price: number }[] = [];
    if (t.entry_date) out.push({ date: t.entry_date, action: entryUp ? "BUY" : "SELL", price: t.entry_price });
    if (t.exit_date) out.push({ date: t.exit_date, action: entryUp ? "SELL" : "BUY", price: t.exit_price });
    return out;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
      <TradeMarkerChart bars={bars} markers={markers} equityCurve={equityCurve} cursor={{ date: bar.date }} />

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <button
          style={{ ...btnStyle, opacity: safeIndex === 0 ? 0.4 : 1 }}
          onClick={() => { setPlaying(false); setCurrentIndex((i) => Math.max(i - 1, 0)); }}
          disabled={safeIndex === 0}
        >
          PREV
        </button>
        <button style={btnStyle} onClick={() => setPlaying((p) => !p)}>
          {playing ? "PAUSE" : "PLAY"}
        </button>
        <button
          style={{ ...btnStyle, opacity: safeIndex === barLog.length - 1 ? 0.4 : 1 }}
          onClick={() => { setPlaying(false); setCurrentIndex((i) => Math.min(i + 1, barLog.length - 1)); }}
          disabled={safeIndex === barLog.length - 1}
        >
          NEXT
        </button>
        <input
          type="range" min={0} max={barLog.length - 1} value={safeIndex}
          onChange={(e) => { setPlaying(false); setCurrentIndex(Number(e.target.value)); }}
          style={{ flex: 1 }}
        />
        <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)", minWidth: 48, textAlign: "right" }}>
          {safeIndex + 1}/{barLog.length}
        </span>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontFamily: "var(--mono)", fontSize: 9 }}>
        <span style={{ color: "var(--ink-dim)" }}>DATE <b style={{ color: "var(--ink)" }}>{bar.date}</b></span>
        <span style={{ color: "var(--ink-dim)" }}>CLOSE <b style={{ color: "var(--ink)" }}>{num(bar.close)}</b></span>
        <span style={{ color: "var(--ink-dim)" }}>
          ACTION{" "}
          <b style={{ color: bar.action === "BUY" ? "var(--green)" : bar.action === "SELL" ? "var(--red)" : "var(--ink)" }}>
            {bar.action}
          </b>
        </span>
        <span style={{ color: "var(--ink-dim)" }}>CONFIDENCE <b style={{ color: "var(--ink)" }}>{num(bar.confidence, 3)}</b></span>
        {bar.indicators && (
          <>
            <span style={{ color: "var(--ink-dim)" }}>RSI <b style={{ color: "var(--ink)" }}>{num(bar.indicators.rsi)}</b></span>
            <span style={{ color: "var(--ink-dim)" }}>MACD <b style={{ color: "var(--ink)" }}>{num(bar.indicators.macd)}</b></span>
            <span style={{ color: "var(--ink-dim)" }}>BB%B <b style={{ color: "var(--ink)" }}>{num(bar.indicators.bb_pct_b)}</b></span>
            <span style={{ color: "var(--ink-dim)" }}>ATR <b style={{ color: "var(--ink)" }}>{num(bar.indicators.atr)}</b></span>
            <span style={{ color: "var(--ink-dim)" }}>VOL RATIO <b style={{ color: "var(--ink)" }}>{num(bar.indicators.volume_ratio)}</b></span>
          </>
        )}
        {bar.trade_fired && <span style={{ color: "var(--amber)" }}>● TRADE FIRED</span>}
        {bar.position_open && <span style={{ color: "var(--cyan)" }}>● POSITION OPEN</span>}
        <span style={{ color: "var(--ink-dim)" }}>PORTFOLIO <b style={{ color: "var(--ink)" }}>{num(bar.portfolio_value)}</b></span>
      </div>
    </div>
  );
}
