/**
 * Equity discovery rail — watchlist + signal candidates + open positions.
 */

import React, { useEffect, useState } from "react";
import { api } from "../../api/client";
import ConfidenceFloorLabel from "../../components/ConfidenceFloorLabel";
import SignalDirectionBadge from "../../components/SignalDirectionBadge";
import WhyBlockedChip from "../../components/WhyBlockedChip";
import { useDeskBlockContext } from "../../hooks/useDeskBlockContext";
import { deriveSignalBlockReason } from "../../utils/signalBlockReason";

const DEFAULT_WATCH = ["AAPL", "NVDA", "MSFT", "META", "AMZN", "QQQ", "SPY"];

type DiscTab = "watch" | "signals" | "positions";

function RailEmpty({ title, hint, tone }: { title: string; hint?: string; tone?: "error" }) {
  return (
    <div className="instrument-card instrument-card--flat empty-chassis empty-chassis--compact">
      <p className="empty-chassis__title" style={tone === "error" ? { color: "var(--red)" } : undefined}>
        {title}
      </p>
      {hint && <p className="empty-chassis__hint">{hint}</p>}
    </div>
  );
}

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

  const actionable = signals.filter((s) => s.action !== "HOLD").slice(0, 20);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div className="discovery-rail-tabs" role="tablist" aria-label="Equity discovery">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`discovery-rail-tabs__btn${tab === t.key ? " discovery-rail-tabs__btn--active" : ""}`}
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
                className={`instrument-card discovery-rail-row${on ? " discovery-rail-row--selected" : ""}`}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <span className="mono" style={{ fontWeight: 700, fontSize: 12, color: "var(--ink)" }}>{t}</span>
                  <span className="tnum" style={{ fontSize: 10, color: (pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {typeof pct === "number" ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : "—"}
                  </span>
                </div>
                <div className="tnum" style={{ fontSize: 10, color: "var(--ink-dim)", marginTop: 2 }}>
                  {typeof s?.last_close === "number" ? `$${s.last_close.toFixed(2)}` : "—"}
                </div>
              </button>
            );
          })}

        {tab === "signals" &&
          (actionable.length === 0 ? (
            <RailEmpty
              title={signalsError ? "Failed to load signals" : "No equity signals yet"}
              hint={signalsError ? undefined : "Run a scan on Live Signals to fill this rail."}
              tone={signalsError ? "error" : undefined}
            />
          ) : (
            actionable.map((s) => (
              <button
                key={s.id || `${s.ticker}-${s.generated_at}`}
                type="button"
                onClick={() => onSelect(s.ticker)}
                className="instrument-card discovery-rail-row"
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                  <span className="mono" style={{ fontWeight: 700, fontSize: 12, color: "var(--ink)" }}>{s.ticker}</span>
                  <SignalDirectionBadge action={s.action} size="sm" />
                </div>
                <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                  <ConfidenceFloorLabel confidence={s.confidence} minConfidence={minConfidence} />
                  <WhyBlockedChip reason={deriveSignalBlockReason(s, blockCtx)} />
                </div>
              </button>
            ))
          ))}

        {tab === "positions" &&
          (positions.length === 0 ? (
            <RailEmpty
              title={positionsError ? "Failed to load positions" : "No open positions"}
              hint={positionsError ? undefined : "Held equity will appear here."}
              tone={positionsError ? "error" : undefined}
            />
          ) : (
            positions.map((p: any) => (
              <button
                key={`${p.symbol}-${p.entry_date || "x"}`}
                type="button"
                onClick={() => onSelect(p.symbol || p.underlying)}
                className="instrument-card discovery-rail-row"
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <span className="mono" style={{ fontWeight: 700, fontSize: 12, color: "var(--ink)" }}>
                    {p.symbol || p.underlying}
                  </span>
                  <span
                    className="tnum"
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
