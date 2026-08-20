/**
 * Equity discovery rail — watchlist + signal candidates + open positions.
 */

import React, { useEffect, useState } from "react";
import { api } from "../../api/client";
import ConfidenceFloorLabel from "../../components/ConfidenceFloorLabel";
import WhyBlockedChip from "../../components/WhyBlockedChip";
import { useDeskBlockContext } from "../../hooks/useDeskBlockContext";
import { deriveSignalBlockReason } from "../../utils/signalBlockReason";

const DEFAULT_WATCH = ["AAPL", "NVDA", "MSFT", "META", "AMZN", "QQQ", "SPY"];

type DiscTab = "watch" | "signals" | "positions";

export default function EquityDiscoveryRail({
  symbol,
  onSelect,
}: {
  symbol: string;
  onSelect: (symbol: string) => void;
}) {
  const [tab, setTab] = useState<DiscTab>("watch");
  const [snaps, setSnaps] = useState<Record<string, { last_close: number | null; change_pct: number | null }>>({});
  const [signals, setSignals] = useState<any[]>([]);
  const [positions, setPositions] = useState<any[]>([]);
  const [signalsError, setSignalsError] = useState(false);
  const [positionsError, setPositionsError] = useState(false);
  const blockCtx = useDeskBlockContext();
  const { minConfidence } = blockCtx;

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const entries = await Promise.all(
        DEFAULT_WATCH.map(async (t) => {
          try {
            const s: any = await api.getSnapshot(t);
            return [t, { last_close: s.last_close ?? null, change_pct: s.change_pct ?? null }] as const;
          } catch {
            return [t, { last_close: null, change_pct: null }] as const;
          }
        }),
      );
      if (!alive) return;
      setSnaps(Object.fromEntries(entries));
      try {
        const sig: any = await api.getEquitySignals(30);
        if (alive) { setSignals(sig.signals || []); setSignalsError(false); }
      } catch {
        if (alive) { setSignals([]); setSignalsError(true); }
      }
      try {
        const pos: any = await api.getPositions();
        if (alive) { setPositions(pos.positions || (Array.isArray(pos) ? pos : [])); setPositionsError(false); }
      } catch {
        if (alive) { setPositions([]); setPositionsError(true); }
      }
    };
    load();
    const id = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const tabs: { key: DiscTab; label: string }[] = [
    { key: "watch", label: "Watch" },
    { key: "signals", label: "Signals" },
    { key: "positions", label: "Held" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{ display: "flex", borderBottom: "1px solid var(--line-dim)", flexShrink: 0 }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            style={{
              flex: 1,
              padding: "8px 4px",
              border: "none",
              background: "transparent",
              borderBottom: tab === t.key ? "2px solid var(--cyan)" : "2px solid transparent",
              color: tab === t.key ? "var(--cyan)" : "var(--ink-dim)",
              fontFamily: "var(--mono)",
              fontSize: 10,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: 8 }}>
        {tab === "watch" &&
          DEFAULT_WATCH.map((t) => {
            const s = snaps[t];
            const on = t === symbol;
            const pct = s?.change_pct;
            return (
              <button
                key={t}
                type="button"
                onClick={() => onSelect(t)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 10px",
                  marginBottom: 4,
                  border: on ? "1px solid var(--cyan)" : "1px solid var(--line-dim)",
                  background: on ? "var(--cyan-dim)" : "var(--bg-3)",
                  color: "var(--ink)",
                  cursor: "pointer",
                  fontFamily: "var(--mono)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontWeight: 700, fontSize: 12 }}>{t}</span>
                  <span style={{ fontSize: 10, color: (pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {typeof pct === "number" ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : "—"}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: "var(--ink-dim)", marginTop: 2 }}>
                  {typeof s?.last_close === "number" ? `$${s.last_close.toFixed(2)}` : "—"}
                </div>
              </button>
            );
          })}

        {tab === "signals" &&
          (signals.length === 0 ? (
            <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: signalsError ? "var(--red)" : "var(--ink-faint)", padding: 8 }}>
              {signalsError ? "Failed to load signals." : "No equity signals yet."}
            </div>
          ) : (
            signals
              .filter((s) => s.action !== "HOLD")
              .slice(0, 20)
              .map((s) => (
                <button
                  key={s.id || `${s.ticker}-${s.generated_at}`}
                  type="button"
                  onClick={() => onSelect(s.ticker)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "8px 10px",
                    marginBottom: 4,
                    border: "1px solid var(--line-dim)",
                    background: "var(--bg-3)",
                    cursor: "pointer",
                    fontFamily: "var(--mono)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontWeight: 700, fontSize: 12, color: "var(--ink)" }}>{s.ticker}</span>
                    <span
                      style={{
                        fontSize: 10,
                        color: s.action === "BUY" ? "var(--green)" : "var(--red)",
                      }}
                    >
                      {s.action}
                    </span>
                  </div>
                  <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                    <ConfidenceFloorLabel confidence={s.confidence} minConfidence={minConfidence} />
                    <WhyBlockedChip reason={deriveSignalBlockReason(s, blockCtx)} />
                  </div>
                </button>
              ))
          ))}

        {tab === "positions" &&
          (positions.length === 0 ? (
            <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: positionsError ? "var(--red)" : "var(--ink-faint)", padding: 8 }}>
              {positionsError ? "Failed to load positions." : "No open positions."}
            </div>
          ) : (
            positions.map((p: any) => (
              <button
                key={`${p.symbol}-${p.entry_date || "x"}`}
                type="button"
                onClick={() => onSelect(p.symbol || p.underlying)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 10px",
                  marginBottom: 4,
                  border: "1px solid var(--line-dim)",
                  background: "var(--bg-3)",
                  cursor: "pointer",
                  fontFamily: "var(--mono)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontWeight: 700, fontSize: 12, color: "var(--ink)" }}>
                    {p.symbol || p.underlying}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      color: (p.unrealized_pnl ?? 0) >= 0 ? "var(--green)" : "var(--red)",
                    }}
                  >
                    {typeof p.unrealized_pnl === "number"
                      ? `${p.unrealized_pnl >= 0 ? "+" : ""}$${p.unrealized_pnl.toFixed(0)}`
                      : "—"}
                  </span>
                </div>
              </button>
            ))
          ))}
      </div>
    </div>
  );
}
