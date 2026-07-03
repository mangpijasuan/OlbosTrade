/**
 * Signals — unified signal surface across asset classes.
 *
 * Equity is a dense, sortable data table (institutional grid, not cards).
 * Options has two sub-views: Flow scanner and CSP income screener.
 * Crypto/Futures are planned.
 */

import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import BrokerStatus from "../components/BrokerStatus";
import PortfolioGreeks from "../components/PortfolioGreeks";
import OptionsFlow from "./OptionsFlow";
import CspScreener from "./CspScreener";

type AssetClass = "equity" | "options" | "crypto" | "futures";

const ASSET_TABS: { key: AssetClass; label: string; ready: boolean }[] = [
  { key: "equity", label: "Equity", ready: true },
  { key: "options", label: "Options", ready: true },
  { key: "crypto", label: "Crypto", ready: false },
  { key: "futures", label: "Futures", ready: false },
];

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

// ── Sorting ──────────────────────────────────────────────────────────────────
type SortKey =
  | "ticker" | "action" | "confidence" | "orderflow_score" | "iv_overlay_boost"
  | "rsi" | "volume_ratio" | "entry" | "target" | "risk_reward" | "generated_at";

function sortValue(s: Signal, key: SortKey): number | string {
  switch (key) {
    case "ticker": return s.ticker;
    case "action": return s.action;
    case "confidence": return s.confidence;
    case "orderflow_score": return s.orderflow_score;
    case "iv_overlay_boost": return s.iv_overlay_boost;
    case "rsi": return s.indicators?.rsi ?? -1;
    case "volume_ratio": return s.indicators?.volume_ratio ?? -1;
    case "entry": return s.trade_plan?.entry_price ?? -1;
    case "target": return s.trade_plan?.target_price ?? -1;
    case "risk_reward": return s.trade_plan?.risk_reward ?? -1;
    case "generated_at": return s.generated_at;
  }
}

function actionColor(a: Signal["action"]): string {
  return a === "BUY" ? "var(--green)" : a === "SELL" ? "var(--red)" : "var(--ink-dim)";
}

function confColor(v: number): string {
  const pct = v * 100;
  return pct >= 75 ? "var(--green)" : pct >= 62 ? "var(--ink)" : "var(--amber)";
}

function scoreColor(v: number): string {
  return v > 0.1 ? "var(--green)" : v < -0.1 ? "var(--red)" : "var(--ink-dim)";
}

function num(v: number | undefined, digits = 2, prefix = ""): string {
  return v === undefined ? "—" : `${prefix}${v.toFixed(digits)}`;
}

const COLUMNS: { key: SortKey; label: string; align: "left" | "right"; num?: boolean }[] = [
  { key: "ticker", label: "Ticker", align: "left" },
  { key: "action", label: "Action", align: "left" },
  { key: "confidence", label: "Conf", align: "right", num: true },
  { key: "orderflow_score", label: "Flow", align: "right", num: true },
  { key: "iv_overlay_boost", label: "IV", align: "right", num: true },
  { key: "rsi", label: "RSI", align: "right", num: true },
  { key: "volume_ratio", label: "Vol×", align: "right", num: true },
  { key: "entry", label: "Entry", align: "right", num: true },
  { key: "target", label: "Target", align: "right", num: true },
  { key: "risk_reward", label: "R:R", align: "right", num: true },
  { key: "generated_at", label: "Time", align: "right" },
];

function Placeholder({ title, body }: { title: string; body: React.ReactNode }) {
  return (
    <div style={{
      border: "1px dashed var(--line-dim)", borderRadius: 6, padding: 40,
      textAlign: "center", color: "var(--ink-dim)", fontSize: 13,
    }}>
      <div style={{ color: "var(--ink)", fontSize: 14, marginBottom: 8, fontWeight: 500 }}>{title}</div>
      {body}
    </div>
  );
}

function SignalsTable({ signals }: { signals: Signal[] }) {
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const rows = useMemo(() => {
    const list = [...signals];
    if (sortKey) {
      list.sort((a, b) => {
        const av = sortValue(a, sortKey);
        const bv = sortValue(b, sortKey);
        const cmp = typeof av === "string" && typeof bv === "string"
          ? av.localeCompare(bv)
          : (av as number) - (bv as number);
        return sortDir === "asc" ? cmp : -cmp;
      });
    } else {
      // Default: actionable first, then confidence desc.
      list.sort((a, b) => {
        const aAct = a.action !== "HOLD" && !a.earnings_gated ? 1 : 0;
        const bAct = b.action !== "HOLD" && !b.earnings_gated ? 1 : 0;
        return bAct - aAct || b.confidence - a.confidence;
      });
    }
    return list;
  }, [signals, sortKey, sortDir]);

  const onSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("desc"); }
  };

  return (
    <div style={{ border: "1px solid var(--line-dim)", borderRadius: 6, overflowX: "auto" }}>
      <table className="t-table">
        <thead>
          <tr>
            {COLUMNS.map(col => {
              const active = sortKey === col.key;
              return (
                <th key={col.key}
                  onClick={() => onSort(col.key)}
                  style={{
                    textAlign: col.align, cursor: "pointer", userSelect: "none",
                    color: active ? "var(--ink)" : undefined, whiteSpace: "nowrap",
                  }}>
                  {col.label}
                  <span style={{ color: "var(--accent)", marginLeft: 4 }}>
                    {active ? (sortDir === "asc" ? "▲" : "▼") : ""}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map(s => {
            const tp = s.trade_plan || {};
            const ind = s.indicators || {};
            const muted = s.action === "HOLD" || s.earnings_gated;
            return (
              <tr key={s.id} style={{ opacity: muted ? 0.6 : 1 }}>
                <td style={{ fontFamily: "var(--mono)", fontWeight: 600 }}>
                  {s.ticker}
                  {s.earnings_gated && (
                    <span title="Earnings gate" style={{
                      marginLeft: 6, fontSize: 9, color: "var(--amber)",
                      border: "1px solid var(--amber)", borderRadius: 2, padding: "0 3px",
                    }}>ER</span>
                  )}
                </td>
                <td>
                  <span style={{
                    color: actionColor(s.action),
                    border: `1px solid ${actionColor(s.action)}`,
                    borderRadius: 3, padding: "1px 7px", fontSize: 11, fontWeight: 600,
                  }}>{s.action}</span>
                </td>
                <td className="tnum" style={{ textAlign: "right", color: confColor(s.confidence), fontWeight: 600 }}>
                  {Math.round(s.confidence * 100)}%
                </td>
                <td className="tnum" style={{ textAlign: "right", color: scoreColor(s.orderflow_score) }}>
                  {s.orderflow_score >= 0 ? "+" : ""}{s.orderflow_score.toFixed(2)}
                </td>
                <td className="tnum" style={{ textAlign: "right", color: scoreColor(s.iv_overlay_boost) }}>
                  {s.iv_overlay_boost >= 0 ? "+" : ""}{s.iv_overlay_boost.toFixed(2)}
                </td>
                <td className="tnum" style={{ textAlign: "right", color: "var(--ink)" }}>{num(ind.rsi, 1)}</td>
                <td className="tnum" style={{ textAlign: "right", color: "var(--ink)" }}>{num(ind.volume_ratio, 1)}</td>
                <td className="tnum" style={{ textAlign: "right", color: "var(--ink)" }}>{num(tp.entry_price, 2, "$")}</td>
                <td className="tnum" style={{ textAlign: "right", color: "var(--green)" }}>{num(tp.target_price, 2, "$")}</td>
                <td className="tnum" style={{ textAlign: "right", color: "var(--ink)" }}>{tp.risk_reward !== undefined ? `${tp.risk_reward.toFixed(2)}x` : "—"}</td>
                <td className="tnum" style={{ textAlign: "right", color: "var(--ink-dim)", fontSize: 12 }}>
                  {new Date(s.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function EquitySignalsPanel() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSignals = () => {
    (api.getEquitySignals() as Promise<{ signals?: Signal[] }>)
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
      await api.scanEquitySignals();
      loadSignals();
    } catch (e) {
      setError(String(e));
    } finally {
      setScanning(false);
    }
  };

  const actionable = signals.filter(s => s.action !== "HOLD" && !s.earnings_gated).length;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <p style={{ margin: 0, color: "var(--ink-dim)", fontSize: 12 }}>
          <span style={{ color: "var(--ink)", fontWeight: 500 }}>{actionable}</span> actionable ·{" "}
          <span className="tnum">{signals.length}</span> total
        </p>
        <div style={{ flex: 1 }} />
        <button
          onClick={runScan}
          disabled={scanning}
          style={{
            background: scanning ? "var(--bg-3)" : "var(--accent)",
            color: scanning ? "var(--ink-dim)" : "#fff",
            border: "none", borderRadius: 4, padding: "6px 16px",
            fontSize: 12, fontWeight: 500,
            cursor: scanning ? "default" : "pointer",
          }}
        >
          {scanning ? "Scanning…" : "Run scan"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <BrokerStatus />
        <PortfolioGreeks />
      </div>

      {error && (
        <div style={{
          background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
          borderRadius: 4, padding: "10px 14px", fontSize: 12, color: "var(--red)",
        }}>
          {error}
        </div>
      )}

      {signals.length === 0 ? (
        <div style={{ border: "1px solid var(--line-dim)", borderRadius: 6, overflow: "hidden" }}>
          {/* Empty state keeps the table skeleton visible (structural anchor). */}
          <table className="t-table">
            <thead>
              <tr>{COLUMNS.map(c => (
                <th key={c.key} style={{ textAlign: c.align }}>{c.label}</th>
              ))}</tr>
            </thead>
          </table>
          <div style={{ textAlign: "center", padding: "32px 0", color: "var(--ink-dim)", fontSize: 13 }}>
            No signals yet. Run a scan to populate.
          </div>
        </div>
      ) : (
        <SignalsTable signals={signals} />
      )}
    </>
  );
}

export default function Signals() {
  const [asset, setAsset] = useState<AssetClass>("equity");
  const [optionsView, setOptionsView] = useState<"flow" | "csp">("flow");

  return (
    <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12, maxWidth: 1280 }}>
      <div>
        <h2 style={{ margin: 0, color: "var(--ink)", fontSize: 16, fontWeight: 600 }}>Signals</h2>
        <p style={{ margin: "2px 0 0", color: "var(--ink-dim)", fontSize: 12 }}>Multi-asset signal engine</p>
      </div>

      {/* Asset-class segmented control */}
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line-dim)" }}>
        {ASSET_TABS.map(tab => {
          const active = asset === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setAsset(tab.key)}
              style={{
                background: "none", border: "none",
                borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
                color: active ? "var(--ink)" : "var(--ink-dim)",
                fontSize: 13, padding: "7px 14px", cursor: "pointer",
                fontWeight: active ? 600 : 400,
              }}
            >
              {tab.label}
              {!tab.ready && (
                <span style={{ color: "var(--ink-faint)", fontSize: 9, marginLeft: 6 }}>soon</span>
              )}
            </button>
          );
        })}
      </div>

      {asset === "equity" && <EquitySignalsPanel />}

      {asset === "options" && (
        <>
          {/* Options sub-views: live flow scanner + CSP income screener. */}
          <div style={{ display: "flex", gap: 6 }}>
            {([["flow", "Flow"], ["csp", "CSP Income"]] as const).map(([k, label]) => (
              <button key={k} onClick={() => setOptionsView(k)}
                className={`btn-t ${optionsView === k ? "active" : ""}`}
                style={{ fontSize: 12 }}>
                {label}
              </button>
            ))}
          </div>
          <div style={{ margin: "-12px -14px -14px" }}>
            {optionsView === "flow" ? <OptionsFlow /> : <CspScreener />}
          </div>
        </>
      )}

      {asset === "crypto" && (
        <Placeholder title="Crypto signals · planned"
          body="Crypto signal source not yet connected. The layout is ready for a spot/perp feed." />
      )}

      {asset === "futures" && (
        <Placeholder title="Futures signals · planned"
          body="Futures (MES/ES) signal pipeline is planned. No CME routing yet." />
      )}
    </div>
  );
}
