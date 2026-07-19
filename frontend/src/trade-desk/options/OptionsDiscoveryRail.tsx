/**
 * Options discovery — underlying picker + recent options signals.
 */

import React, { useEffect, useState } from "react";
import { api } from "../../api/client";

const UNDERLYINGS = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "MSFT", "META", "AMZN", "TSLA"];

type DiscTab = "underlyings" | "signals" | "positions";

export default function OptionsDiscoveryRail({
  symbol,
  onSelect,
}: {
  symbol: string;
  onSelect: (symbol: string) => void;
}) {
  const [tab, setTab] = useState<DiscTab>("underlyings");
  const [snaps, setSnaps] = useState<Record<string, { last_close: number | null; change_pct: number | null }>>({});
  const [signals, setSignals] = useState<any[]>([]);
  const [positions, setPositions] = useState<any[]>([]);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const entries = await Promise.all(
        UNDERLYINGS.map(async (t) => {
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
        const sig: any = await api.getOptionsSignals(30);
        if (alive) setSignals(sig.signals || []);
      } catch {
        if (alive) setSignals([]);
      }
      try {
        const pos: any = await api.getPositions();
        const list = pos.positions || (Array.isArray(pos) ? pos : []);
        if (alive) {
          setPositions(
            list.filter(
              (p: any) =>
                (p.asset_type || "").toLowerCase().includes("option") ||
                p.option_type ||
                p.short_strike ||
                p.spread_type,
            ),
          );
        }
      } catch {
        if (alive) setPositions([]);
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
    { key: "underlyings", label: "Underlyings" },
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
              fontSize: 9,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: 8 }}>
        {tab === "underlyings" &&
          UNDERLYINGS.map((t) => {
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
            <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)", padding: 8 }}>
              No options signals yet.
            </div>
          ) : (
            signals.slice(0, 20).map((s) => (
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
                  <span style={{ fontSize: 9, color: "var(--cyan)" }}>
                    {(s.strategy || s.action || "").toString().replace(/_/g, " ")}
                  </span>
                </div>
              </button>
            ))
          ))}

        {tab === "positions" &&
          (positions.length === 0 ? (
            <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)", padding: 8 }}>
              No open options positions detected.
            </div>
          ) : (
            positions.map((p: any, i: number) => (
              <button
                key={`${p.symbol || p.underlying}-${i}`}
                type="button"
                onClick={() => onSelect(p.underlying || p.symbol)}
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
                <div style={{ fontWeight: 700, fontSize: 12, color: "var(--ink)" }}>
                  {p.underlying || p.symbol}
                </div>
                <div style={{ fontSize: 10, color: "var(--ink-dim)", marginTop: 2 }}>
                  {(p.spread_type || p.option_type || "options").toString()}
                </div>
              </button>
            ))
          ))}
      </div>
    </div>
  );
}
