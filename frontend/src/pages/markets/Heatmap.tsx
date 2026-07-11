/**
 * Heatmaps — watchlist universe tiled and colored by daily % change.
 * Reads the same /api/market/snapshot endpoint that feeds the ticker strip.
 */
import React, { useEffect, useState } from "react";
import { UNIVERSE, Snap, fetchSnap } from "./universe";

// Background tint by magnitude of move (green up / red down), terminal-flat.
function tileBg(pct: number | null): { bg: string; fg: string } {
  if (pct === null) return { bg: "var(--bg-3)", fg: "var(--ink-faint)" };
  const mag = Math.min(Math.abs(pct), 3) / 3; // 0..1
  const alpha = 0.12 + mag * 0.33;
  if (pct >= 0) return { bg: `rgba(34,197,94,${alpha.toFixed(2)})`, fg: "var(--ink)" };
  return { bg: `rgba(239,68,68,${alpha.toFixed(2)})`, fg: "var(--ink)" };
}

export default function Heatmap() {
  const [snaps, setSnaps] = useState<Record<string, Snap>>({});
  const [loading, setLoading] = useState(true);

  const load = () => {
    const jobs = UNIVERSE.flatMap(g =>
      g.symbols.map(s => fetchSnap(s.api ?? s.sym).then(snap => [s.sym, snap] as const))
    );
    Promise.all(jobs).then(pairs => {
      setSnaps(Object.fromEntries(pairs));
      setLoading(false);
    });
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Market Heatmap</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          daily % change · snapshot refreshes every 60s
        </span>
        {loading && (
          <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
            loading…
          </span>
        )}
      </div>

      {UNIVERSE.map(group => (
        <div key={group.label} style={{ marginBottom: 20 }}>
          <div style={{
            fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em",
            textTransform: "uppercase", color: "var(--ink-dim)", marginBottom: 8,
          }}>
            {group.label}
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
            gap: 8,
          }}>
            {group.symbols.map(s => {
              const snap = snaps[s.sym];
              const pct = snap?.change_pct ?? null;
              const { bg, fg } = tileBg(pct);
              return (
                <div key={s.sym} style={{
                  background: bg, color: fg, border: "1px solid var(--line-dim)",
                  padding: "10px 12px", minHeight: 62, display: "flex", flexDirection: "column",
                  justifyContent: "space-between",
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <span style={{ fontFamily: "var(--mono)", fontWeight: 600, fontSize: 13 }}>{s.sym}</span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
                      {snap?.last_close != null ? snap.last_close.toFixed(2) : "—"}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <span style={{ fontSize: 9, color: "var(--ink-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.name}
                    </span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600 }}>
                      {pct != null ? `${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%` : "—"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
