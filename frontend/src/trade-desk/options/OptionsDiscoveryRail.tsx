/**
 * Options discovery — underlying picker + recent options signals.
 */

import React, { useEffect, useState } from "react";
import { api } from "../../api/client";
import SignalDirectionBadge from "../../components/SignalDirectionBadge";

const UNDERLYINGS = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "MSFT", "META", "AMZN", "TSLA"];

type DiscTab = "underlyings" | "signals" | "positions";

function RailEmpty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="instrument-card instrument-card--flat empty-chassis empty-chassis--compact">
      <p className="empty-chassis__title">{title}</p>
      {hint && <p className="empty-chassis__hint">{hint}</p>}
    </div>
  );
}

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
  const [signalsError, setSignalsError] = useState(false);

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
        if (alive) { setSignals(sig.signals || []); setSignalsError(false); }
      } catch {
        if (alive) { setSignals([]); setSignalsError(true); }
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

  const actionable = signals
    .filter((s) => s.action === "BUY_SPREAD" || s.action === "SELL_SPREAD" || s.action === "BUY" || s.action === "SELL")
    .slice(0, 20);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div className="discovery-rail-tabs" role="tablist" aria-label="Options discovery">
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
              title={signalsError ? "Failed to load signals" : "No options signals yet"}
              hint={signalsError ? undefined : "Run the Options Scanner to fill this rail."}
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
                {s.strategy && (
                  <div className="kicker" style={{ marginTop: 4 }}>
                    {String(s.strategy).replace(/_/g, " ")}
                  </div>
                )}
              </button>
            ))
          ))}

        {tab === "positions" &&
          (positions.length === 0 ? (
            <RailEmpty
              title="No open options positions"
              hint="Held spreads will appear here."
            />
          ) : (
            positions.map((p: any, i: number) => (
              <button
                key={`${p.symbol || p.underlying}-${i}`}
                type="button"
                onClick={() => onSelect(p.underlying || p.symbol)}
                className="instrument-card discovery-rail-row"
              >
                <div className="mono" style={{ fontWeight: 700, fontSize: 12, color: "var(--ink)" }}>
                  {p.underlying || p.symbol}
                </div>
                <div className="kicker" style={{ marginTop: 2 }}>
                  {(p.spread_type || p.option_type || "options").toString().replace(/_/g, " ")}
                </div>
              </button>
            ))
          ))}
      </div>
    </div>
  );
}
