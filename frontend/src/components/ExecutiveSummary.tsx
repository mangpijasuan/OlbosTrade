/**
 * ExecutiveSummary — Bloomberg-style dashboard header.
 *
 *   KPI cards (Total Equity / Total P&L / Day P&L)
 *   Performance panel (Sharpe, Sortino, Calmar, win rate, profit factor, …)
 *   Portfolio Heat gauge (capital at risk + exposures + concentration flags)
 *   System Health checklist
 *
 * Data: /api/dashboard/summary, /api/analytics/performance, /api/portfolio/heat
 * (polled every 15s).
 */
import React, { useEffect, useState } from "react";

// ── Inline icon set ─────────────────────────────────────────────────────────
const ICON: Record<string, string> = {
  dollar:   "M12 1v22 M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6",
  pnl:      "M3 3v18h18 M7 16v2 M12 11v7 M17 7v11",
  trend:    "M23 6l-9.5 9.5-5-5L1 18 M17 6h6v6",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  gauge:    "M12 14a2 2 0 100-4 2 2 0 000 4z M12 14l4-4 M3.5 18a9 9 0 1117 0",
  perf:     "M3 3v18h18 M7 14l3-3 3 3 5-6",
  check:    "M22 11.08V12a10 10 0 11-5.93-9.14 M22 4L12 14.01l-3-3",
  warn:     "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z M12 9v4 M12 17h.01",
  cross:    "M12 22a10 10 0 100-20 10 10 0 000 20z M15 9l-6 6 M9 9l6 6",
};

const Icon = ({ name, size = 14, color = "currentColor" }: { name: string; size?: number; color?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
    strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
    {ICON[name].split(" M").map((seg, i) => <path key={i} d={(i ? "M" : "") + seg} />)}
  </svg>
);

// ── Types ───────────────────────────────────────────────────────────────────
type Health = { name: string; status: "ok" | "warn" | "error"; detail: string };
interface Summary {
  total_equity: number; total_pnl: number; total_pnl_pct: number;
  day_pnl: number; day_pnl_pct: number; health: Health[]; issues: number;
}
interface Performance {
  total_trades: number; win_rate: number; profit_factor: number; expectancy: number;
  payoff_ratio: number; avg_hold_days: number; sharpe: number; sortino: number;
  calmar: number; max_drawdown_pct: number; cagr_pct: number;
  current_drawdown_pct: number; rolling_max_dd_30_pct: number; sample_size_warning: boolean;
}
interface Heat {
  portfolio_heat_pct: number; heat_status: "ok" | "elevated" | "high";
  total_risk_dollars: number; position_count: number;
  largest_underlying: string | null; largest_underlying_pct: number;
  largest_sector: string | null; largest_sector_pct: number;
  exposure_by_underlying: Record<string, number>; concentration_flags: string[];
}
interface StratHealth {
  strategy: string; status: "healthy" | "watch" | "degraded" | "insufficient_data";
  action: "none" | "reduce" | "suspend"; sample_size: number;
  win_rate: number; expectancy: number; drawdown_pct: number;
  expectancy_ratio: number | null; reasons: string[];
}
interface StratHealthResp { strategies: StratHealth[]; suspended: string[]; total_strategies: number; }

// ── Formatters ──────────────────────────────────────────────────────────────
const money = (n: number) =>
  (n >= 0 ? "+" : "-") + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const plain = (n: number) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const STATUS = { ok: "var(--green)", warn: "var(--amber)", error: "var(--red)" } as const;
const HEAT = { ok: "var(--green)", elevated: "var(--amber)", high: "var(--red)" } as const;
const STRAT_STATUS: Record<string, { color: string; tint: string; icon: string; label: string }> = {
  healthy:           { color: "var(--green)", tint: "rgba(34,197,94,0.05)", icon: "check", label: "HEALTHY" },
  watch:             { color: "var(--amber)", tint: "rgba(245,158,11,0.06)", icon: "warn",  label: "WATCH" },
  degraded:          { color: "var(--red)",   tint: "rgba(239,68,68,0.06)",  icon: "cross", label: "SUSPENDED" },
  insufficient_data: { color: "var(--ink-dim)", tint: "transparent",         icon: "activity", label: "NO DATA" },
};

// ── KPI card ────────────────────────────────────────────────────────────────
function Kpi({ label, value, sub, color, icon }:
  { label: string; value: string; sub?: string; color?: string; icon: string }) {
  return (
    <div className="exec-card" style={{ flex: 1, minWidth: 210, padding: "16px 18px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span className="kicker">{label}</span>
        <span style={{ color: "var(--cyan)", opacity: 0.7 }}><Icon name={icon} size={15} /></span>
      </div>
      <div className="mono" style={{ fontSize: 27, fontWeight: 700, color: color || "var(--ink)", lineHeight: 1, letterSpacing: "-0.02em" }}>
        {value}
      </div>
      {sub && <div className="mono" style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: 8 }}>{sub}</div>}
    </div>
  );
}

// ── Small metric tile ───────────────────────────────────────────────────────
function Tile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "var(--bg-2)", padding: "11px 13px" }}>
      <div className="kicker" style={{ fontSize: 8.5, marginBottom: 5 }}>{label}</div>
      <div className="mono" style={{ fontSize: 15, fontWeight: 600, color: color || "var(--ink)" }}>{value}</div>
    </div>
  );
}

function PanelHead({ icon, title, right }: { icon: string; title: string; right?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "var(--cyan)" }}><Icon name={icon} size={13} /></span>
        <span className="panel-title">{title}</span>
      </span>
      {right}
    </div>
  );
}

function HealthRow({ h }: { h: Health }) {
  const color = STATUS[h.status];
  const tint = h.status === "ok" ? "rgba(34,197,94,0.05)"
    : h.status === "warn" ? "rgba(245,158,11,0.06)" : "rgba(239,68,68,0.06)";
  const icon = h.status === "ok" ? "check" : h.status === "warn" ? "warn" : "cross";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 14px",
      background: tint, borderLeft: `2px solid ${color}`, borderBottom: "1px solid var(--line-dim)" }}>
      <span style={{ color }}><Icon name={icon} size={13} /></span>
      <span className="mono" style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)", minWidth: 128 }}>{h.name}</span>
      <span className="mono" style={{ fontSize: 12, color }}>{h.detail}</span>
    </div>
  );
}

function StratRow({ h }: { h: StratHealth }) {
  const cfg = STRAT_STATUS[h.status] || STRAT_STATUS.insufficient_data;
  const ratio = h.expectancy_ratio !== null ? `${(h.expectancy_ratio * 100).toFixed(0)}% of base` : "—";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 14px",
      background: cfg.tint, borderLeft: `2px solid ${cfg.color}`, borderBottom: "1px solid var(--line-dim)" }}>
      <span style={{ color: cfg.color }}><Icon name={cfg.icon} size={13} /></span>
      <span className="mono" style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)", minWidth: 150 }}>
        {h.strategy}
      </span>
      <span className="mono" style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.08em",
        color: cfg.color, minWidth: 78 }}>{cfg.label}</span>
      <span className="mono" style={{ fontSize: 11, color: "var(--ink-dim)", display: "flex", gap: 14, flexWrap: "wrap" }}>
        <span>n={h.sample_size}</span>
        <span>win {(h.win_rate * 100).toFixed(0)}%</span>
        <span style={{ color: h.expectancy >= 0 ? "var(--green)" : "var(--red)" }}>
          exp {h.expectancy >= 0 ? "+" : ""}{h.expectancy.toFixed(0)}
        </span>
        <span>{ratio}</span>
      </span>
    </div>
  );
}

export default function ExecutiveSummary() {
  const [s, setS] = useState<Summary | null>(null);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [heat, setHeat] = useState<Heat | null>(null);
  const [strat, setStrat] = useState<StratHealthResp | null>(null);

  useEffect(() => {
    const j = (u: string) => fetch(u).then(r => r.json()).catch(() => null);
    const load = async () => {
      setS(await j("/api/dashboard/summary"));
      setPerf(await j("/api/analytics/performance"));
      setHeat(await j("/api/portfolio/heat"));
      setStrat(await j("/api/strategy/health"));
    };
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  const pnlColor = (n: number) => (n >= 0 ? "var(--green)" : "var(--red)");
  const pct = (n: number) => `${n >= 0 ? "+" : ""}${n}%`;

  return (
    <div style={{ padding: "18px 16px 10px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ width: 3, height: 17, background: "var(--cyan)", boxShadow: "0 0 10px var(--cyan-glow)" }} />
        <span className="mono" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.16em", color: "var(--ink)" }}>
          EXECUTIVE SUMMARY
        </span>
      </div>

      {/* KPI cards */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        <Kpi label="Total Equity" icon="dollar" value={s ? plain(s.total_equity) : "—"} />
        <Kpi label="Total P&L" icon="pnl"
          value={s ? money(s.total_pnl) : "—"} color={s ? pnlColor(s.total_pnl) : undefined}
          sub={s ? `${pct(s.total_pnl_pct)} since open` : undefined} />
        <Kpi label="Day P&L" icon="trend"
          value={s ? money(s.day_pnl) : "—"} color={s ? pnlColor(s.day_pnl) : undefined}
          sub={s ? `${pct(s.day_pnl_pct)} today` : undefined} />
      </div>

      {/* Performance + Portfolio Heat */}
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 12, marginBottom: 14 }}>
        {/* Performance */}
        <div className="exec-card">
          <PanelHead icon="perf" title="Performance"
            right={perf && perf.sample_size_warning
              ? <span className="mono" style={{ fontSize: 9.5, color: "var(--amber)" }}>
                  {perf.total_trades} trades · low sample
                </span>
              : perf && <span className="mono" style={{ fontSize: 9.5, color: "var(--ink-dim)" }}>{perf.total_trades} trades</span>} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 1, background: "var(--line-dim)" }}>
            <Tile label="Win Rate" value={perf ? `${(perf.win_rate * 100).toFixed(0)}%` : "—"}
              color={perf && perf.win_rate >= 0.5 ? "var(--green)" : "var(--ink)"} />
            <Tile label="Profit Factor" value={perf ? perf.profit_factor.toFixed(2) : "—"}
              color={perf && perf.profit_factor >= 1.5 ? "var(--green)" : "var(--ink)"} />
            <Tile label="Sharpe" value={perf ? perf.sharpe.toFixed(2) : "—"}
              color={perf && perf.sharpe >= 1 ? "var(--cyan)" : "var(--ink)"} />
            <Tile label="Sortino" value={perf ? perf.sortino.toFixed(2) : "—"}
              color={perf && perf.sortino >= 1 ? "var(--cyan)" : "var(--ink)"} />
            <Tile label="Calmar" value={perf ? perf.calmar.toFixed(2) : "—"} />
            <Tile label="Max DD" value={perf ? `${perf.max_drawdown_pct}%` : "—"}
              color={perf && perf.max_drawdown_pct > 15 ? "var(--red)" : "var(--ink)"} />
            <Tile label="Current DD" value={perf ? `${perf.current_drawdown_pct}%` : "—"}
              color={perf && perf.current_drawdown_pct > 8 ? "var(--red)" : "var(--ink)"} />
            <Tile label="Rolling DD (30)" value={perf ? `${perf.rolling_max_dd_30_pct}%` : "—"}
              color={perf && perf.rolling_max_dd_30_pct > 10 ? "var(--amber)" : "var(--ink)"} />
            <Tile label="Expectancy" value={perf ? money(perf.expectancy) : "—"}
              color={perf ? pnlColor(perf.expectancy) : undefined} />
            <Tile label="Avg Hold" value={perf ? `${perf.avg_hold_days}d` : "—"} />
          </div>
        </div>

        {/* Portfolio Heat */}
        <div className="exec-card">
          <PanelHead icon="gauge" title="Portfolio Heat"
            right={heat && <span className="mono" style={{ fontSize: 9.5, color: "var(--ink-dim)" }}>{heat.position_count} open</span>} />
          <div style={{ padding: "14px" }}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8 }}>
              <span className="mono" style={{ fontSize: 24, fontWeight: 700,
                color: heat ? HEAT[heat.heat_status] : "var(--ink)" }}>
                {heat ? `${heat.portfolio_heat_pct}%` : "—"}
              </span>
              <span className="kicker">{heat ? `${plain(heat.total_risk_dollars)} at risk` : ""}</span>
            </div>
            <div style={{ height: 8, background: "var(--bg-4)", borderRadius: 4, overflow: "hidden", marginBottom: 12 }}>
              <div style={{ height: "100%", borderRadius: 4, transition: "width .5s ease",
                width: `${heat ? Math.min(100, heat.portfolio_heat_pct) : 0}%`,
                background: heat ? HEAT[heat.heat_status] : "var(--ink-faint)" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-dim)" }}>
              <span>Top name: <b style={{ color: "var(--ink)" }}>{heat?.largest_underlying || "—"}</b> {heat ? `${heat.largest_underlying_pct}%` : ""}</span>
              <span>Sector: <b style={{ color: "var(--ink)" }}>{heat?.largest_sector || "—"}</b></span>
            </div>
            {heat && heat.concentration_flags.length > 0 && (
              <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
                {heat.concentration_flags.map((f, i) => (
                  <span key={i} className="mono" style={{ fontSize: 9, padding: "2px 8px", borderRadius: 10,
                    background: "rgba(239,68,68,0.12)", border: "1px solid rgba(239,68,68,0.3)", color: "var(--red)" }}>
                    {f.split(" ")[0]}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Strategy health */}
      <div className="exec-card" style={{ marginBottom: 14 }}>
        <PanelHead icon="check" title="Strategy Health"
          right={strat && <span className="mono" style={{ fontSize: 10.5,
            color: strat.suspended.length === 0 ? "var(--green)" : "var(--red)" }}>
            {strat.suspended.length === 0
              ? `${strat.total_strategies} tracked · none suspended`
              : `${strat.suspended.length} suspended`}
          </span>} />
        {strat && strat.strategies.length > 0
          ? strat.strategies.map(h => <StratRow key={h.strategy} h={h} />)
          : <div style={{ padding: 14, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
              {strat ? "No closed trades yet — collecting data." : "Loading…"}
            </div>}
      </div>

      {/* System health */}
      <div className="exec-card">
        <PanelHead icon="activity" title="System Health"
          right={s && <span className="mono" style={{ fontSize: 10.5,
            color: s.issues === 0 ? "var(--green)" : "var(--amber)" }}>
            {s.issues === 0 ? "All systems nominal" : `${s.issues} issue${s.issues > 1 ? "s" : ""} detected`}
          </span>} />
        {s ? s.health.map(h => <HealthRow key={h.name} h={h} />)
          : <div style={{ padding: 16, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>Loading…</div>}
      </div>
    </div>
  );
}
