/**
 * OptionsFlow page — live options flow feed (Options Intelligence module).
 *
 * Bloomberg-style: dark bg, monospace, existing theme variables. Streams the
 * /api/options-flow/ws channel with filter params, seeded by an initial REST
 * pull. Feed pauses on hover; WebSocket reconnects with exponential backoff.
 *
 * NOTE: real ticks require a live IBKR OPRA subscription with
 * options_flow_enabled=true. With options_flow_demo_mode=true the backend
 * emits synthetic ticks so this panel can be exercised end-to-end.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, optionsFlowWsUrl } from "../api/client";

interface FlowTick {
  id?: number;
  ticker: string;
  strike: number;
  expiry: string;
  right: "C" | "P";
  exchange: string | null;
  timestamp: string;
  premium: number;
  size: number;
  trade_type: "sweep" | "block" | "single";
  sentiment: "bullish" | "bearish" | "neutral";
  iv: number | null;
  delta: number | null;
  dte: number;
  relative_volume: number | null;
  sweep_confirmed: boolean;
  large_sweep: boolean;
}

const TICKERS = ["ALL", "SPY", "QQQ", "IWM"];
const MAX_ROWS = 250;

function fmtUsd(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}
function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", { hour12: false });
  } catch {
    return iso;
  }
}

function rowStyle(t: FlowTick): React.CSSProperties {
  const s: React.CSSProperties = {
    cursor: "pointer",
    borderBottom: "1px solid var(--line-dim)",
  };
  if (t.sentiment === "bullish") s.background = "rgba(34,197,94,0.07)";
  else if (t.sentiment === "bearish") s.background = "rgba(239,68,68,0.07)";
  if (t.sweep_confirmed || t.large_sweep) {
    s.borderLeft = "2px solid var(--amber)";
    if (t.large_sweep) s.fontWeight = 700;
  }
  return s;
}

function SentimentTag({ s }: { s: FlowTick["sentiment"] }) {
  const color =
    s === "bullish" ? "var(--green)" : s === "bearish" ? "var(--red)" : "var(--ink-dim)";
  return <span style={{ color, fontWeight: 600 }}>{s.toUpperCase()}</span>;
}

function RatioBar({ ratio }: { ratio: number }) {
  const bull = Math.round(ratio * 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 160 }}>
      <div style={{ flex: 1, height: 8, borderRadius: 2, overflow: "hidden", display: "flex" }}>
        <div style={{ width: `${bull}%`, background: "var(--green)" }} />
        <div style={{ width: `${100 - bull}%`, background: "var(--red)" }} />
      </div>
      <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
        {bull}% / {100 - bull}%
      </span>
    </div>
  );
}

export default function OptionsFlow() {
  const [ticker, setTicker] = useState("ALL");
  const [right, setRight] = useState<"all" | "C" | "P">("all");
  const [minPremium, setMinPremium] = useState(0);
  const [tradeType, setTradeType] = useState<"" | "sweep" | "block" | "single">("");

  const [rows, setRows] = useState<FlowTick[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [connected, setConnected] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  const pausedRef = useRef(false);          // pause feed on hover
  const bufferRef = useRef<FlowTick[]>([]);  // hold ticks while paused
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const closedRef = useRef(false);

  const filters = useMemo(
    () => ({
      ticker: ticker === "ALL" ? undefined : ticker,
      right: right === "all" ? undefined : right,
      min_premium: minPremium > 0 ? minPremium : undefined,
      trade_type: tradeType || undefined,
    }),
    [ticker, right, minPremium, tradeType]
  );

  // ── Initial REST seed + summary, refreshed on filter change ────────────────
  useEffect(() => {
    let alive = true;
    api
      .getOptionsFlow({ ...filters, limit: 100 })
      .then((r) => alive && setRows(r.results || []))
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, [filters]);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.getOptionsFlowSummary().then((s) => alive && setSummary(s)).catch(() => {});
    load();
    const id = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const flushBuffer = useCallback(() => {
    if (bufferRef.current.length) {
      setRows((prev) => [...bufferRef.current, ...prev].slice(0, MAX_ROWS));
      bufferRef.current = [];
    }
  }, []);

  // ── WebSocket with exponential backoff reconnect ───────────────────────────
  useEffect(() => {
    closedRef.current = false;

    const connect = () => {
      if (closedRef.current) return;
      const ws = new WebSocket(optionsFlowWsUrl({ ...filters }));
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 0;
      };
      ws.onmessage = (ev) => {
        try {
          const tick: FlowTick = JSON.parse(ev.data);
          if (pausedRef.current) {
            bufferRef.current = [tick, ...bufferRef.current].slice(0, MAX_ROWS);
          } else {
            setRows((prev) => [tick, ...prev].slice(0, MAX_ROWS));
          }
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (closedRef.current) return;
        const delay = Math.min(1000 * 2 ** retryRef.current, 30000);
        retryRef.current += 1;
        setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closedRef.current = true;
      wsRef.current?.close();
    };
  }, [filters]);

  return (
    <div style={{ padding: 16, fontFamily: "var(--sans)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontFamily: "var(--mono)", color: "var(--cyan)" }}>
          OPTIONS FLOW
        </h2>
        <span className={`dot ${connected ? "live" : "dead"}`} />
        <span style={{ fontSize: 11, color: "var(--ink-dim)" }}>
          {connected ? "STREAMING" : "DISCONNECTED"}
        </span>
      </div>

      {/* Top filter bar */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 16,
          alignItems: "center",
          background: "var(--bg-2)",
          border: "1px solid var(--line-dim)",
          borderRadius: 6,
          padding: "10px 14px",
          marginBottom: 12,
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          {TICKERS.map((t) => (
            <button
              key={t}
              onClick={() => setTicker(t)}
              style={{
                fontFamily: "var(--mono)",
                fontSize: 11,
                padding: "4px 10px",
                borderRadius: 4,
                cursor: "pointer",
                border: `1px solid ${ticker === t ? "var(--cyan)" : "var(--line-dim)"}`,
                background: ticker === t ? "var(--cyan-dim)" : "transparent",
                color: ticker === t ? "var(--cyan)" : "var(--ink-dim)",
              }}
            >
              {t}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", gap: 4 }}>
          {(["all", "C", "P"] as const).map((r) => (
            <button
              key={r}
              onClick={() => setRight(r)}
              style={{
                fontFamily: "var(--mono)",
                fontSize: 11,
                padding: "4px 10px",
                borderRadius: 4,
                cursor: "pointer",
                border: `1px solid ${right === r ? "var(--cyan)" : "var(--line-dim)"}`,
                background: right === r ? "var(--cyan-dim)" : "transparent",
                color: right === r ? "var(--cyan)" : "var(--ink-dim)",
              }}
            >
              {r === "all" ? "C/P" : r}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--ink-dim)" }}>MIN PREM</span>
          <input
            type="range"
            min={0}
            max={1_000_000}
            step={25_000}
            value={minPremium}
            onChange={(e) => setMinPremium(Number(e.target.value))}
          />
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, minWidth: 48 }}>
            {fmtUsd(minPremium)}
          </span>
        </div>

        <select
          value={tradeType}
          onChange={(e) => setTradeType(e.target.value as any)}
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            background: "var(--bg-3)",
            color: "var(--ink)",
            border: "1px solid var(--line-dim)",
            borderRadius: 4,
            padding: "4px 8px",
          }}
        >
          <option value="">ALL TYPES</option>
          <option value="sweep">SWEEP</option>
          <option value="block">BLOCK</option>
          <option value="single">SINGLE</option>
        </select>
      </div>

      {/* Summary row */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 24,
          alignItems: "center",
          background: "var(--bg-2)",
          border: "1px solid var(--line-dim)",
          borderRadius: 6,
          padding: "10px 14px",
          marginBottom: 12,
        }}
      >
        <Metric label="TOTAL PREMIUM" value={summary ? fmtUsd(summary.total_premium_today || 0) : "—"} />
        <div>
          <div style={{ fontSize: 10, color: "var(--ink-dim)", marginBottom: 4 }}>
            BULLISH / BEARISH
          </div>
          <RatioBar
            ratio={
              summary?.by_ticker?.length
                ? summary.by_ticker.reduce((a: number, t: any) => a + (t.bullish_ratio || 0.5), 0) /
                  summary.by_ticker.length
                : 0.5
            }
          />
        </div>
        <Metric
          label="LARGE SWEEPS"
          value={summary ? String(summary.large_sweep_count_today || 0) : "—"}
          color="var(--amber)"
        />
        <div>
          <div style={{ fontSize: 10, color: "var(--ink-dim)", marginBottom: 4 }}>MOST ACTIVE</div>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 12,
              padding: "2px 8px",
              borderRadius: 4,
              background: "var(--cyan-dim)",
              color: "var(--cyan)",
            }}
          >
            {summary?.most_active_ticker || "—"}
          </span>
        </div>
      </div>

      {/* Live feed table */}
      <div
        onMouseEnter={() => {
          pausedRef.current = true;
        }}
        onMouseLeave={() => {
          pausedRef.current = false;
          flushBuffer();
        }}
        style={{
          background: "var(--bg-2)",
          border: "1px solid var(--line-dim)",
          borderRadius: 6,
          maxHeight: "calc(100vh - 320px)",
          overflowY: "auto",
        }}
      >
        <table className="t-table" style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 12 }}>
          <thead>
            <tr style={{ position: "sticky", top: 0, background: "var(--bg-3)", zIndex: 1 }}>
              <Th>Time</Th><Th>Ticker</Th><Th>C/P</Th><Th>Strike</Th><Th>Expiry</Th>
              <Th align="right">Size</Th><Th align="right">Premium</Th><Th>Type</Th><Th>Sentiment</Th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} style={{ padding: 24, textAlign: "center", color: "var(--ink-dim)" }}>
                  No flow yet. Enable options_flow_demo_mode (or a live OPRA feed) to see ticks.
                </td>
              </tr>
            )}
            {rows.map((t, i) => {
              const key = t.id ?? `${t.timestamp}-${i}`;
              const isOpen = expanded === (t.id ?? i);
              return (
                <React.Fragment key={key}>
                  <tr style={rowStyle(t)} onClick={() => setExpanded(isOpen ? null : t.id ?? i)}>
                    <td>{fmtTime(t.timestamp)}</td>
                    <td style={{ color: "var(--cyan)" }}>{t.ticker}</td>
                    <td style={{ color: t.right === "C" ? "var(--green)" : "var(--red)" }}>{t.right}</td>
                    <td>{t.strike}</td>
                    <td>{t.expiry}</td>
                    <td style={{ textAlign: "right" }}>{t.size.toLocaleString()}</td>
                    <td style={{ textAlign: "right" }}>{fmtUsd(t.premium)}</td>
                    <td style={{ textTransform: "uppercase", color: t.trade_type === "sweep" ? "var(--amber)" : "var(--ink)" }}>
                      {t.trade_type}
                    </td>
                    <td><SentimentTag s={t.sentiment} /></td>
                  </tr>
                  {isOpen && (
                    <tr style={{ background: "var(--bg-4)" }}>
                      <td colSpan={9} style={{ padding: "8px 14px", color: "var(--ink-dim)" }}>
                        <span style={{ marginRight: 18 }}>Δ {t.delta ?? "—"}</span>
                        <span style={{ marginRight: 18 }}>IV {t.iv != null ? `${(t.iv * 100).toFixed(1)}%` : "—"}</span>
                        <span style={{ marginRight: 18 }}>DTE {t.dte}</span>
                        <span style={{ marginRight: 18 }}>Exch {t.exchange || "—"}</span>
                        <span style={{ marginRight: 18 }}>RelVol {t.relative_volume ?? "—"}×</span>
                        <span>Sweep {t.sweep_confirmed ? "✓" : "—"}{t.large_sweep ? " (LARGE)" : ""}</span>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th style={{ textAlign: align, padding: "8px 10px", color: "var(--ink-faint)", fontWeight: 600 }}>
      {children}
    </th>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--ink-dim)", marginBottom: 4 }}>{label}</div>
      <div style={{ fontFamily: "var(--mono)", fontSize: 16, fontWeight: 600, color: color || "var(--ink)" }}>
        {value}
      </div>
    </div>
  );
}
