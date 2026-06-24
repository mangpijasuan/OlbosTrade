/**
 * ExecutiveSummary — dashboard header.
 *
 * Three KPI cards (Total Equity, Total P&L, Day P&L) over a System Health
 * checklist (broker, DB, agent, market hours, kill switch, config) with an
 * issue count. Data from GET /api/dashboard/summary (polled every 15s).
 */
import React, { useEffect, useState } from "react";

type Health = { name: string; status: "ok" | "warn" | "error"; detail: string };
type Summary = {
  total_equity: number;
  total_pnl: number;
  total_pnl_pct: number;
  day_pnl: number;
  day_pnl_pct: number;
  health: Health[];
  issues: number;
};

const money = (n: number) =>
  (n >= 0 ? "+" : "-") + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const plain = (n: number) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const STATUS_COLOR: Record<string, string> = {
  ok: "var(--green)", warn: "var(--amber)", error: "var(--red)",
};

function Card({ label, value, sub, valueColor, icon }: {
  label: string; value: string; sub?: string; valueColor?: string; icon: string;
}) {
  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--line-dim)",
      padding: "14px 18px", flex: 1, minWidth: 220,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.12em",
          color: "var(--ink-faint)", textTransform: "uppercase" }}>{label}</span>
        <span style={{ color: "var(--ink-faint)", fontSize: 13 }}>{icon}</span>
      </div>
      <div style={{ fontFamily: "var(--mono)", fontSize: 26, fontWeight: 700,
        color: valueColor || "var(--ink)", lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", marginTop: 7 }}>{sub}</div>}
    </div>
  );
}

function HealthRow({ h }: { h: Health }) {
  const color = STATUS_COLOR[h.status] || "var(--ink-dim)";
  const glyph = h.status === "ok" ? "✓" : h.status === "warn" ? "⚠" : "✕";
  const tint = h.status === "ok" ? "rgba(34,197,94,0.06)"
             : h.status === "warn" ? "rgba(245,158,11,0.07)"
             : "rgba(239,68,68,0.07)";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, padding: "9px 14px",
      background: tint, borderLeft: `2px solid ${color}`,
      borderBottom: "1px solid var(--line-dim)",
    }}>
      <span style={{ color, fontSize: 13, width: 16, textAlign: "center" }}>{glyph}</span>
      <span style={{ fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600, color: "var(--ink)", minWidth: 130 }}>
        {h.name}
      </span>
      <span style={{ fontFamily: "var(--mono)", fontSize: 12, color }}>{h.detail}</span>
    </div>
  );
}

export default function ExecutiveSummary() {
  const [s, setS] = useState<Summary | null>(null);

  useEffect(() => {
    const load = () =>
      fetch("/api/dashboard/summary").then(r => r.json()).then(setS).catch(() => {});
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  const pnlColor = (n: number) => (n >= 0 ? "var(--green)" : "var(--red)");

  return (
    <div style={{ padding: "16px 16px 8px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <span style={{ width: 3, height: 16, background: "var(--cyan)" }} />
        <span style={{ fontFamily: "var(--mono)", fontSize: 14, fontWeight: 700,
          letterSpacing: "0.14em", color: "var(--ink)" }}>EXECUTIVE SUMMARY</span>
      </div>

      {/* KPI cards */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 18 }}>
        <Card label="Total Equity" icon="$"
          value={s ? plain(s.total_equity) : "—"} />
        <Card label="Total P&L" icon="▦"
          value={s ? money(s.total_pnl) : "—"}
          valueColor={s ? pnlColor(s.total_pnl) : undefined}
          sub={s ? `${s.total_pnl_pct >= 0 ? "+" : ""}${s.total_pnl_pct}% since open` : undefined} />
        <Card label="Day P&L" icon="↗"
          value={s ? money(s.day_pnl) : "—"}
          valueColor={s ? pnlColor(s.day_pnl) : undefined}
          sub={s ? `${s.day_pnl_pct >= 0 ? "+" : ""}${s.day_pnl_pct}% today` : undefined} />
      </div>

      {/* System health */}
      <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)" }}>
        <div className="panel-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
          <span className="panel-title">⚡ System Health</span>
          {s && (
            <span style={{ fontFamily: "var(--mono)", fontSize: 11,
              color: s.issues === 0 ? "var(--green)" : "var(--amber)" }}>
              {s.issues === 0 ? "All systems nominal" : `${s.issues} issue${s.issues > 1 ? "s" : ""} detected`}
            </span>
          )}
        </div>
        {s ? s.health.map(h => <HealthRow key={h.name} h={h} />)
           : <div style={{ padding: 16, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>Loading…</div>}
      </div>
    </div>
  );
}
