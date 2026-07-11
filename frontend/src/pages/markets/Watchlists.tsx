/**
 * Watchlists — the market universe as a sortable price table, grouped by sector.
 * Same /api/market/snapshot source as the heatmap; complementary dense view.
 */
import React, { useEffect, useState } from "react";
import { UNIVERSE, Snap, fetchSnap, changeColor } from "./universe";

export default function Watchlists() {
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
        <span className="panel-title">Watchlists</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          {loading ? "loading…" : "close · change · refreshes every 60s"}
        </span>
      </div>

      <table className="t-table">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Symbol</th>
            <th style={{ textAlign: "left" }}>Name</th>
            <th style={{ textAlign: "right" }}>Last</th>
            <th style={{ textAlign: "right" }}>Prev</th>
            <th style={{ textAlign: "right" }}>Change</th>
          </tr>
        </thead>
        <tbody>
          {UNIVERSE.map(group => (
            <React.Fragment key={group.label}>
              <tr>
                <td colSpan={5} style={{
                  fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em",
                  textTransform: "uppercase", color: "var(--ink-dim)",
                  background: "var(--bg-3)", padding: "5px 8px",
                }}>
                  {group.label}
                </td>
              </tr>
              {group.symbols.map(s => {
                const snap = snaps[s.sym];
                const pct = snap?.change_pct ?? null;
                return (
                  <tr key={s.sym}>
                    <td className="mono" style={{ color: "var(--cyan)", fontWeight: 600 }}>{s.sym}</td>
                    <td style={{ color: "var(--ink-dim)", fontSize: 11 }}>{s.name}</td>
                    <td className="mono" style={{ textAlign: "right" }}>
                      {snap?.last_close != null ? snap.last_close.toFixed(2) : "—"}
                    </td>
                    <td className="mono" style={{ textAlign: "right", color: "var(--ink-dim)" }}>
                      {snap?.prev_close != null ? snap.prev_close.toFixed(2) : "—"}
                    </td>
                    <td className="mono" style={{ textAlign: "right", color: changeColor(pct), fontWeight: 600 }}>
                      {pct != null ? `${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(2)}%` : "—"}
                    </td>
                  </tr>
                );
              })}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
