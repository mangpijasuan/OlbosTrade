/**
 * Dashboard — Bloomberg terminal style.
 * 4-panel grid: equity curve, portfolio stats, positions, Greeks.
 *
 * Equity curve sources (in priority order):
 *  1. Real closed-trade P&L from DB  (/api/paper-trade/history)
 *  2. Latest backtest equity_curve    (/api/backtest/history)
 *  3. Flat line at current account value (no data yet)
 * Time-range buttons filter the curve by calendar window.
 */

import React, { useEffect, useRef, useState, useCallback } from "react";
import { api }           from "../api/client";
import { usePaperTrade } from "../hooks/usePaperTrade";
import { useRisk }       from "../hooks/useRisk";
import ExecutiveSummary  from "../components/ExecutiveSummary";
import ErrorBoundary     from "../components/ErrorBoundary";
import { useIsMobile }   from "../hooks/useIsMobile";

// ── Equity chart canvas ───────────────────────────────────────────────────────
interface ChartPoint { date: string; value: number; }

function EquityChart({ points, loading }: { points: ChartPoint[]; loading: boolean }) {
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
    ctx.clearRect(0, 0, W, H);

    if (loading) {
      ctx.fillStyle = "rgba(100,116,139,0.4)";
      ctx.font = "11px 'JetBrains Mono'";
      ctx.textAlign = "center";
      ctx.fillText("LOADING…", W / 2, H / 2);
      return;
    }

    const pts = points.map(p => p.value);

    if (pts.length < 2) {
      ctx.fillStyle = "rgba(100,116,139,0.4)";
      ctx.font = "11px 'JetBrains Mono'";
      ctx.textAlign = "center";
      ctx.fillText("NO TRADE DATA YET — START TRADING TO SEE CURVE", W / 2, H / 2);
      return;
    }

    const minV = Math.min(...pts);
    const maxV = Math.max(...pts);
    const range = maxV - minV || 1;
    const pad = { t: 12, b: 28, l: 62, r: 12 };
    const cW = W - pad.l - pad.r;
    const cH = H - pad.t - pad.b;

    // Grid
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + (cH / 4) * i;
      ctx.strokeStyle = "rgba(255,255,255,0.04)";
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
      ctx.setLineDash([]);
      const val = maxV - (range / 4) * i;
      ctx.fillStyle = "rgba(100,116,139,0.8)";
      ctx.font = "10px 'JetBrains Mono'";
      ctx.textAlign = "right";
      ctx.fillText("$" + (val >= 1000 ? (val / 1000).toFixed(1) + "k" : val.toFixed(0)), pad.l - 4, y + 3.5);
    }

    // Date labels (3 evenly spaced)
    const labelIdxs = [0, Math.floor(pts.length / 2), pts.length - 1];
    labelIdxs.forEach(idx => {
      if (idx >= points.length) return;
      const x = pad.l + (cW * idx) / (pts.length - 1);
      ctx.fillStyle = "rgba(100,116,139,0.6)";
      ctx.font = "9px 'JetBrains Mono'";
      ctx.textAlign = "center";
      const d = new Date(points[idx].date);
      ctx.fillText(d.toLocaleDateString("en-US", { month: "short", day: "numeric" }), x, H - 6);
    });

    const X = (i: number) => pad.l + (cW * i) / (pts.length - 1);
    const Y = (v: number) => pad.t + cH - (cH * (v - minV)) / range;

    // Determine color: green if end > start, red if not
    const trending = pts[pts.length - 1] >= pts[0];
    const lineColor   = trending ? "#22c55e" : "#ef4444";
    const fillColor0  = trending ? "rgba(34,197,94,0.18)"  : "rgba(239,68,68,0.18)";
    const fillColor1  = trending ? "rgba(34,197,94,0.03)"  : "rgba(239,68,68,0.03)";

    // Fill
    ctx.beginPath();
    ctx.moveTo(X(0), H - pad.b);
    pts.forEach((v, i) => ctx.lineTo(X(i), Y(v)));
    ctx.lineTo(X(pts.length - 1), H - pad.b);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
    grad.addColorStop(0, fillColor0);
    grad.addColorStop(0.7, fillColor1);
    grad.addColorStop(1, "transparent");
    ctx.fillStyle = grad;
    ctx.fill();

    // Line
    ctx.beginPath();
    pts.forEach((v, i) => i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)));
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.8;
    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Dot at end
    const lx = X(pts.length - 1), ly = Y(pts[pts.length - 1]);
    ctx.beginPath();
    ctx.arc(lx, ly, 3, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.shadowColor = lineColor;
    ctx.shadowBlur = 10;
    ctx.fill();
    ctx.shadowBlur = 0;
  }, [points, loading]);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
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

function PositionRow({ pos }: { pos: any }) {
  const pnl = pos.unrealized_pnl ?? 0;
  // Untracked = a broker holding Olbos never opened (no DB record). Render
  // it muted and badged "UNTRACKED" so it is never mistaken for a managed trade.
  const untracked = pos.tracked === false;
  const pnlKnown = pos.unrealized_pnl != null;
  return (
    <tr style={untracked ? { opacity: 0.55 } : undefined}>
      <td className="mono" style={{ color: "var(--cyan)" }}>{pos.symbol || "—"}</td>
      <td className="mono">{pos.option_type?.toUpperCase() || pos.strategy || "EQUITY"}</td>
      <td className="mono">{pos.strike || pos.avg_cost?.toFixed(2) || "—"}</td>
      <td className="mono">{pos.expiration || pos.entry_date || "—"}</td>
      <td className="mono">{pos.quantity ?? 1}</td>
      <td className="mono" style={{ color: !pnlKnown ? "var(--ink-faint)" : pnl >= 0 ? "var(--green)" : "var(--red)" }}>
        {pnlKnown ? `${pnl >= 0 ? "+" : ""}$${Math.abs(pnl).toLocaleString("en-US", { maximumFractionDigits: 0 })}` : "—"}
      </td>
      <td>
        <span style={{
          fontFamily: "var(--mono)", fontSize: 10, padding: "2px 6px",
          background: untracked ? "rgba(245,158,11,0.1)" : "rgba(34,197,94,0.1)",
          color: untracked ? "var(--amber)" : "var(--green)",
          letterSpacing: "0.08em",
        }}>{untracked ? "UNTRACKED" : "OPEN"}</span>
      </td>
    </tr>
  );
}

// ── Build equity curve from trade history ────────────────────────────────────
function buildCurveFromTrades(trades: any[], startingCapital: number): ChartPoint[] {
  if (!trades || trades.length === 0) return [];
  const closed = trades
    .filter(t => t.status === "closed" && t.exit_date && t.pnl != null)
    .sort((a, b) => new Date(a.exit_date).getTime() - new Date(b.exit_date).getTime());
  if (closed.length === 0) return [];

  let equity = startingCapital;
  const points: ChartPoint[] = [{ date: closed[0].entry_date || closed[0].exit_date, value: equity }];
  for (const t of closed) {
    equity += Number(t.pnl);
    points.push({ date: t.exit_date, value: Math.max(equity, 0) });
  }
  return points;
}

function filterByRange(points: ChartPoint[], range: string): ChartPoint[] {
  if (points.length === 0 || range === "ALL") return points;
  const now = Date.now();
  const ms: Record<string, number> = {
    "1W":  7  * 86400000,
    "1M":  30 * 86400000,
    "3M":  90 * 86400000,
    "YTD": now - new Date(new Date().getFullYear(), 0, 1).getTime(),
  };
  const cutoff = now - (ms[range] ?? 90 * 86400000);
  const filtered = points.filter(p => new Date(p.date).getTime() >= cutoff);
  // Always include at least the starting anchor
  if (filtered.length === 0) return points.slice(-2);
  // Prepend the last point before the cutoff as anchor
  const anchor = points.filter(p => new Date(p.date).getTime() < cutoff).slice(-1);
  return [...anchor, ...filtered];
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const isMobile = useIsMobile();
  const { positions, portfolio, greeks } = usePaperTrade();
  const { guardrailStatus, portfolioState } = useRisk();

  // Managed = Olbos-opened positions (tracked). Untracked = pre-existing
  // broker holdings in the (shared paper) account that we did not open.
  const managedPositions   = positions.filter((p: any) => p.tracked !== false);
  const untrackedPositions = positions.filter((p: any) => p.tracked === false);

  const pv      = portfolio?.account_value ?? portfolio?.net_liquidation ?? 25000;
  const daily   = guardrailStatus?.daily_pnl   ?? portfolioState?.state?.daily_pnl   ?? portfolio?.total_pnl ?? 0;
  const weekly  = guardrailStatus?.weekly_pnl  ?? 0;
  const monthly = guardrailStatus?.monthly_pnl ?? 0;

  const [range, setRange]           = useState("ALL");
  const [allPoints, setAllPoints]   = useState<ChartPoint[]>([]);
  const [curveLoading, setCurveLoading] = useState(true);
  const [curveSource, setCurveSource]   = useState<"trades" | "backtest" | "none">("none");

  // Load equity curve data
  const loadCurve = useCallback(async () => {
    setCurveLoading(true);
    try {
      // 1. Try real trade history from DB
      const tradeData: any = await api
        .getTradeHistory({ limit: 500, status: "closed" })
        .catch(() => null);
      if (tradeData) {
        const trades = tradeData.trades ?? [];
        const curve = buildCurveFromTrades(trades, portfolio?.starting_capital ?? 25000);
        if (curve.length >= 2) {
          setAllPoints(curve);
          setCurveSource("trades");
          setCurveLoading(false);
          return;
        }
      }

      // 2. Fall back to latest completed backtest equity_curve
      const histData: any = await api.getBacktestHistory(5).catch(() => null);
      if (histData) {
        const completed = (histData.runs ?? []).find((r: any) => r.status === "completed");
        if (completed) {
          // Fetch full result to get equity_curve array
          const runData: any = await api
            .getBacktestResults(completed.run_id)
            .catch(() => null);
          if (runData) {
            const ec: number[] = runData.equity_curve ?? [];
            if (ec.length >= 2) {
              // Generate synthetic dates for backtest curve
              const start = new Date(runData.start_date ?? "2023-01-01");
              const pts: ChartPoint[] = ec.map((v, i) => {
                const d = new Date(start);
                d.setDate(d.getDate() + Math.round((i / (ec.length - 1)) * 365 * 2));
                return { date: d.toISOString().slice(0, 10), value: v };
              });
              setAllPoints(pts);
              setCurveSource("backtest");
              setCurveLoading(false);
              return;
            }
          }
        }
      }

      // 3. No data — show empty state
      setAllPoints([]);
      setCurveSource("none");
    } catch {
      setAllPoints([]);
      setCurveSource("none");
    } finally {
      setCurveLoading(false);
    }
  }, [portfolio?.starting_capital]);

  useEffect(() => { loadCurve(); }, [loadCurve]);

  const visiblePoints = filterByRange(allPoints, range);

  // P&L delta for the visible range
  const rangePnl = visiblePoints.length >= 2
    ? visiblePoints[visiblePoints.length - 1].value - visiblePoints[0].value
    : 0;

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto auto 1fr auto", height: "100%", overflow: "auto", gap: 0 }}>

      {/* Executive summary header */}
      <ErrorBoundary label="Executive Summary">
        <ExecutiveSummary />
      </ErrorBoundary>

      {/* Top stat bar */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "repeat(2, 1fr)" : "repeat(8, 1fr)", borderBottom: "1px solid var(--line-dim)" }}>
        <StatCell
          label="Portfolio Value"
          value={`$${(pv / 1000).toFixed(2)}k`}
          sub={portfolio?.return_pct != null ? `${portfolio.return_pct >= 0 ? "+" : ""}${portfolio.return_pct.toFixed(2)}% all-time` : undefined}
        />
        <StatCell
          label="Day P&L"
          value={`${daily >= 0 ? "+" : ""}$${Math.abs(daily).toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
          sub={portfolio?.win_rate != null ? `Win rate: ${(portfolio.win_rate * 100).toFixed(1)}%` : undefined}
          color={daily >= 0 ? "var(--green)" : "var(--red)"}
        />
        <StatCell
          label="Week P&L"
          value={`${weekly >= 0 ? "+" : ""}$${Math.abs(weekly).toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
          color={weekly >= 0 ? "var(--green)" : "var(--red)"}
        />
        <StatCell
          label="Month P&L"
          value={`${monthly >= 0 ? "+" : ""}$${Math.abs(monthly).toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
          color={monthly >= 0 ? "var(--green)" : "var(--red)"}
        />
        <StatCell label="Buying Power"     value={portfolio?.buying_power != null ? `$${(portfolio.buying_power / 1000).toFixed(1)}k` : "—"} />
        <StatCell label="Net Delta"        value={(greeks?.net_delta || 0).toFixed(3)} />
        <StatCell label="Net Theta / day"  value={(greeks?.net_theta || 0).toFixed(3)} color="var(--cyan)" />
        <StatCell
          label="Open Positions"
          value={String(portfolio?.open_positions ?? managedPositions.length)}
          sub={untrackedPositions.length > 0 ? `+${untrackedPositions.length} untracked` : undefined}
        />
      </div>

      {/* Main panels */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 320px", overflow: isMobile ? "visible" : "hidden" }}>

        {/* Left: equity + positions */}
        <div style={{ display: "flex", flexDirection: "column", borderRight: isMobile ? "none" : "1px solid var(--line-dim)", overflow: "hidden" }}>

          {/* Equity curve */}
          <div style={{ flex: "0 0 220px", borderBottom: "1px solid var(--line-dim)" }}>
            <div className="panel-head">
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="panel-title">Equity Curve</span>
                {curveSource === "backtest" && (
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--amber)", padding: "1px 6px", border: "1px solid var(--amber)", opacity: 0.7 }}>
                    BACKTEST
                  </span>
                )}
                {curveSource === "trades" && (
                  <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--green)", padding: "1px 6px", border: "1px solid var(--green)", opacity: 0.7 }}>
                    LIVE
                  </span>
                )}
                {visiblePoints.length >= 2 && (
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: rangePnl >= 0 ? "var(--green)" : "var(--red)", marginLeft: 8 }}>
                    {rangePnl >= 0 ? "+" : ""}${rangePnl.toFixed(0)}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                {["1W","1M","3M","YTD","ALL"].map(t => (
                  <button
                    key={t}
                    className={`btn-t ${t === range ? "active" : ""}`}
                    style={{ padding: "2px 8px", fontSize: 10 }}
                    onClick={() => setRange(t)}
                  >{t}</button>
                ))}
              </div>
            </div>
            <div style={{ height: 175, padding: "8px 4px 4px" }}>
              <EquityChart points={visiblePoints} loading={curveLoading} />
            </div>
          </div>

          {/* Positions table */}
          <div style={{ flex: 1, overflow: "auto" }}>
            <div className="panel-head">
              <span className="panel-title">Open Positions</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                {managedPositions.length} managed
                {untrackedPositions.length > 0 && (
                  <span style={{ color: "var(--amber)" }}> · {untrackedPositions.length} untracked</span>
                )}
              </span>
            </div>
            {untrackedPositions.length > 0 && (
              <div style={{
                padding: "7px 14px", fontFamily: "var(--mono)", fontSize: 10,
                color: "var(--amber)", background: "rgba(245,158,11,0.06)",
                borderBottom: "1px solid var(--line-dim)",
              }}>
                ⚠ {untrackedPositions.length} broker holding{untrackedPositions.length > 1 ? "s" : ""} not opened by Olbos — review/reconcile in the paper account.
              </div>
            )}
            <table className="t-table">
              <thead>
                <tr>
                  {["Symbol","Type","Strike / Avg","Expiry / Entry","Qty","Unreal P&L","Status"].map(h => (
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
                  [...managedPositions, ...untrackedPositions].map((p: any, i: number) => <PositionRow key={i} pos={p} />)
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
                { label: "Daily Loss",    val: Math.abs(guardrailStatus?.daily_loss_pct || 0) * 100, max: 2,  unit: "%" },
                { label: "Weekly Loss",   val: Math.abs(guardrailStatus?.weekly_loss_pct || 0) * 100, max: 5, unit: "%" },
                { label: "Trades Today",  val: guardrailStatus?.trades_today || 0, max: 3, unit: "" },
                { label: "Consec. Loss",  val: guardrailStatus?.consecutive_losses || 0, max: 3, unit: "" },
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

          {/* Active risk profile */}
          <div style={{ borderBottom: "1px solid var(--line-dim)" }}>
            <div className="panel-head">
              <span className="panel-title">Active Risk Profile</span>
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
                { label: "Δ DELTA", val: (greeks?.net_delta || 0).toFixed(4) },
                { label: "Γ GAMMA", val: (greeks?.net_gamma || 0).toFixed(4) },
                { label: "Θ THETA", val: (greeks?.net_theta || 0).toFixed(4) },
                { label: "ν VEGA",  val: (greeks?.net_vega  || 0).toFixed(4) },
              ].map(g => (
                <div key={g.label} style={{ background: "var(--bg-3)", borderRadius: 4, padding: "8px 10px" }}>
                  <div className="kicker" style={{ marginBottom: 4 }}>{g.label}</div>
                  <div className="data-val sm">{g.val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
