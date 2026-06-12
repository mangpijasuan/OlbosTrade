/**
 * Dashboard — Bloomberg terminal style.
 * 4-panel grid: equity curve, portfolio stats, positions, Greeks.
 */

import React, { useEffect, useRef, useState } from "react";
import { usePaperTrade } from "../hooks/usePaperTrade";
import { useRisk }       from "../hooks/useRisk";

// ── Equity curve canvas ───────────────────────────────────────────────────────
function EquityChart({ data }: { data: number[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth;
    const H = canvas.offsetHeight;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const pts = data.length > 1 ? data : Array.from({ length: 120 }, (_, i) => {
      let v = 25000;
      for (let j = 0; j <= i; j++) v += Math.sin(j / 8) * 80 + (Math.random() - 0.38) * 200 + 45;
      return Math.max(v, 22000);
    });

    const minV = Math.min(...pts), maxV = Math.max(...pts);
    const pad = { t: 12, b: 24, l: 60, r: 12 };
    const cW = W - pad.l - pad.r;
    const cH = H - pad.t - pad.b;

    ctx.clearRect(0, 0, W, H);

    // Grid lines
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + (cH / 4) * i;
      ctx.strokeStyle = "rgba(255,255,255,0.04)";
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
      ctx.setLineDash([]);
      const val = maxV - ((maxV - minV) / 4) * i;
      ctx.fillStyle = "rgba(100,116,139,0.8)";
      ctx.font = "10px 'JetBrains Mono'";
      ctx.textAlign = "right";
      ctx.fillText("$" + Math.round(val / 1000) + "k", pad.l - 4, y + 3.5);
    }

    const X = (i: number) => pad.l + (cW * i) / (pts.length - 1);
    const Y = (v: number) => pad.t + cH - (cH * (v - minV)) / (maxV - minV);

    // Fill
    ctx.beginPath();
    ctx.moveTo(X(0), H - pad.b);
    pts.forEach((v, i) => ctx.lineTo(X(i), Y(v)));
    ctx.lineTo(X(pts.length - 1), H - pad.b);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
    grad.addColorStop(0, "rgba(0,212,170,0.18)");
    grad.addColorStop(0.6, "rgba(0,212,170,0.04)");
    grad.addColorStop(1, "rgba(0,212,170,0)");
    ctx.fillStyle = grad;
    ctx.fill();

    // Line
    ctx.beginPath();
    pts.forEach((v, i) => i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)));
    ctx.strokeStyle = "#00d4aa";
    ctx.lineWidth = 1.8;
    ctx.shadowColor = "rgba(0,212,170,0.5)";
    ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Dot at end
    const lx = X(pts.length - 1), ly = Y(pts[pts.length - 1]);
    ctx.beginPath();
    ctx.arc(lx, ly, 3, 0, Math.PI * 2);
    ctx.fillStyle = "#00d4aa";
    ctx.shadowColor = "#00d4aa";
    ctx.shadowBlur = 10;
    ctx.fill();
    ctx.shadowBlur = 0;
  }, [data]);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />;
}

// ── Stat cell ─────────────────────────────────────────────────────────────────
function StatCell({ label, value, sub, color }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div style={{ padding: "14px 16px", borderRight: "1px solid var(--line-dim)" }}>
      <div className="kicker" style={{ marginBottom: 6 }}>{label}</div>
      <div className="data-val" style={{ color: color || "var(--ink)" }}>{value}</div>
      {sub && <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)", marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

// ── Position row ──────────────────────────────────────────────────────────────
function PositionRow({ pos }: { pos: any }) {
  const pnl = pos.unrealized_pnl || 0;
  return (
    <tr>
      <td className="mono" style={{ color: "var(--cyan)" }}>{pos.symbol || "SPY"}</td>
      <td className="mono">{pos.option_type?.toUpperCase() || "PUT"}</td>
      <td className="mono">{pos.strike || "450.00"}</td>
      <td className="mono">{pos.expiration || "—"}</td>
      <td className="mono">{pos.quantity || 1}</td>
      <td className="mono" style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>
        {pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}
      </td>
      <td>
        <span style={{
          fontFamily: "var(--mono)", fontSize: 10, padding: "2px 6px",
          background: "rgba(0,212,170,0.1)", color: "var(--cyan)",
          letterSpacing: "0.08em",
        }}>OPEN</span>
      </td>
    </tr>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const { positions, portfolio, greeks } = usePaperTrade();
  const { guardrailStatus } = useRisk();
  const pv = portfolio?.net_liquidation || 25000;
  const daily = portfolio?.daily_pnl || 0;

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr auto", height: "100%", gap: 0 }}>

      {/* Top stat bar */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(6, 1fr)",
        borderBottom: "1px solid var(--line-dim)",
      }}>
        <StatCell label="Portfolio Value" value={`$${(pv/1000).toFixed(2)}k`} color="var(--cyan)" />
        <StatCell label="Day P&L" value={`${daily >= 0 ? "+" : ""}$${Math.abs(daily).toFixed(0)}`}
          color={daily >= 0 ? "var(--green)" : "var(--red)"} />
        <StatCell label="Open Positions" value={String(positions.length)} />
        <StatCell label="Net Delta" value={(greeks?.net_delta || 0).toFixed(3)} />
        <StatCell label="Net Theta" value={(greeks?.net_theta || 0).toFixed(3)} color="var(--cyan)" />
        <StatCell label="Net Vega" value={(greeks?.net_vega || 0).toFixed(3)} />
      </div>

      {/* Main panels */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", overflow: "hidden" }}>

        {/* Left: equity + positions */}
        <div style={{ display: "flex", flexDirection: "column", borderRight: "1px solid var(--line-dim)", overflow: "hidden" }}>

          {/* Equity curve */}
          <div style={{ flex: "0 0 220px", borderBottom: "1px solid var(--line-dim)" }}>
            <div className="panel-head">
              <span className="panel-title">Equity Curve</span>
              <div style={{ display: "flex", gap: 8 }}>
                {["1W","1M","3M","YTD","ALL"].map(t => (
                  <button key={t} className={`btn-t ${t === "3M" ? "active" : ""}`}
                    style={{ padding: "2px 8px", fontSize: 10 }}>{t}</button>
                ))}
              </div>
            </div>
            <div style={{ height: 175, padding: "8px 4px 4px" }}>
              <EquityChart data={[]} />
            </div>
          </div>

          {/* Positions table */}
          <div style={{ flex: 1, overflow: "auto" }}>
            <div className="panel-head">
              <span className="panel-title">Open Positions</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                {positions.length} active
              </span>
            </div>
            <table className="t-table">
              <thead>
                <tr>
                  {["Symbol","Type","Strike","Expiry","Qty","Unreal P&L","Status"].map(h => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: "center", color: "var(--ink-faint)", padding: 24 }}>
                      NO OPEN POSITIONS
                    </td>
                  </tr>
                ) : (
                  positions.map((p: any, i: number) => <PositionRow key={i} pos={p} />)
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right: status panels */}
        <div style={{ display: "flex", flexDirection: "column", overflow: "auto" }}>

          {/* Guardrail status */}
          <div style={{ borderBottom: "1px solid var(--line-dim)" }}>
            <div className="panel-head">
              <span className="panel-title">Guardrails</span>
              <span className={`dot ${guardrailStatus?.trading_allowed ? "live" : "dead"}`} />
            </div>
            <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { label: "Daily Loss", val: Math.abs(guardrailStatus?.daily_loss_pct || 0) * 100, max: 2, unit: "%" },
                { label: "Weekly Loss", val: Math.abs(guardrailStatus?.weekly_loss_pct || 0) * 100, max: 5, unit: "%" },
                { label: "Trades Today", val: guardrailStatus?.trades_today || 0, max: 3, unit: "" },
                { label: "Consecutive L", val: guardrailStatus?.consecutive_losses || 0, max: 3, unit: "" },
              ].map(g => {
                const pct = Math.min((g.val / g.max) * 100, 100);
                const color = pct < 60 ? "var(--green)" : pct < 85 ? "var(--amber)" : "var(--red)";
                return (
                  <div key={g.label}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>{g.label}</span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 10, color }}>
                        {g.val.toFixed(1)}{g.unit} / {g.max}{g.unit}
                      </span>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${pct}%`, background: color }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Active mode */}
          <div style={{ borderBottom: "1px solid var(--line-dim)" }}>
            <div className="panel-head">
              <span className="panel-title">Active Mode</span>
            </div>
            <div style={{ padding: "12px 14px" }}>
              <span className={`mode-badge ${guardrailStatus?.trading_mode || "balanced"}`}
                style={{ fontSize: 12, padding: "4px 12px" }}>
                {(guardrailStatus?.trading_mode || "balanced").toUpperCase()}
              </span>
              <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", marginTop: 8 }}>
                {guardrailStatus?.trading_allowed ? "TRADING ACTIVE" : "TRADING SUSPENDED"}
              </div>
            </div>
          </div>

          {/* Portfolio Greeks */}
          <div>
            <div className="panel-head">
              <span className="panel-title">Portfolio Greeks</span>
            </div>
            <div style={{ padding: "12px 14px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {[
                { label: "Δ DELTA",  val: (greeks?.net_delta || 0).toFixed(4) },
                { label: "Γ GAMMA",  val: (greeks?.net_gamma || 0).toFixed(4) },
                { label: "Θ THETA",  val: (greeks?.net_theta || 0).toFixed(4) },
                { label: "ν VEGA",   val: (greeks?.net_vega  || 0).toFixed(4) },
              ].map(g => (
                <div key={g.label} style={{
                  background: "var(--bg-3)",
                  padding: "10px 12px",
                }}>
                  <div className="kicker" style={{ marginBottom: 4 }}>{g.label}</div>
                  <div className="data-val sm mono">{g.val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
