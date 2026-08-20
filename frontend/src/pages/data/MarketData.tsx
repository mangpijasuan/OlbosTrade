/**
 * Market Data — feed & session status from /api/market/status and /api/market/regime.
 * Confirms the desk is looking at a live, correctly-classified session.
 */
import React, { useEffect, useState } from "react";

export default function MarketData() {
  const [status, setStatus] = useState<any>(null);
  const [regime, setRegime] = useState<any>(null);

  const load = () => {
    fetch("/api/market/status").then(r => r.json()).then(setStatus).catch(() => setStatus({ error: true }));
    fetch("/api/market/regime").then(r => r.json()).then(setRegime).catch(() => {});
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const open = !!status?.is_open;

  const cards: { label: string; value: string; color?: string }[] = [
    { label: "Session", value: open ? "OPEN" : "CLOSED", color: open ? "var(--green)" : "var(--ink-dim)" },
    { label: "Execution gate", value: status?.execution_gated ? "market hours" : "always", color: status?.execution_gated ? "var(--amber)" : "var(--cyan)" },
    { label: "Regime", value: (regime?.regime ?? "—").replace(/_/g, " ").toUpperCase(),
      color: regime?.regime === "crisis" ? "var(--red)" : String(regime?.regime).includes("high_vol") ? "var(--amber)" : "var(--cyan)" },
    { label: "VIX", value: regime?.vix != null ? String(regime.vix) : "—" },
    { label: "IV rank", value: regime?.iv_rank != null ? `${regime.iv_rank}` : "—" },
  ];

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Market Data</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          session & feed health · polls every 15s
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 10, maxWidth: 720 }}>
        {cards.map(c => (
          <div key={c.label} className="instrument-card" style={{ padding: "12px 14px" }}>
            <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              {c.label}
            </div>
            <div style={{ fontFamily: "var(--mono)", fontSize: 17, fontWeight: 600, color: c.color ?? "var(--ink)" }}>
              {c.value}
            </div>
          </div>
        ))}
      </div>

      {regime?.description && (
        <div style={{ marginTop: 14, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)", borderLeft: "2px solid var(--line-dim)", paddingLeft: 10, maxWidth: 720 }}>
          {regime.description}
        </div>
      )}
    </div>
  );
}
