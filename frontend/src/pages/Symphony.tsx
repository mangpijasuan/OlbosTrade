/**
 * Symphony — Composer-style no-code strategy backtester.
 *
 * Pick an example (or edit the JSON tree), choose a rebalance cadence + capital,
 * and run an instant backtest → equity curve + metrics + final target weights.
 * Backed by GET /api/symphony/examples and POST /api/symphony/backtest.
 */
import React, { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui";

type Pt = { date: string; value: number };
interface Example { name: string; description: string; cadence: string; tree: any }
interface Metrics {
  total_return_pct: number; cagr_pct: number; max_drawdown_pct: number;
  sharpe: number; volatility_pct: number;
}
interface BacktestResult {
  equity_curve: Pt[]; final_weights: Record<string, number>;
  rebalances: number; metrics: Metrics; tickers: string[];
  missing_tickers: string[]; start: string; end: string; error?: string;
}

// ── Equity curve canvas ──────────────────────────────────────────────────────
function Curve({ points }: { points: Pt[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv || points.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    cv.width = w * dpr; cv.height = h * dpr;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const vals = points.map(p => p.value);
    const min = Math.min(...vals), max = Math.max(...vals);
    const pad = 8;
    const x = (i: number) => pad + (i / (points.length - 1)) * (w - pad * 2);
    const y = (v: number) => h - pad - ((v - min) / (max - min || 1)) * (h - pad * 2);
    const up = vals[vals.length - 1] >= vals[0];
    const col = up ? "#22c55e" : "#ef4444";

    // area fill
    ctx.beginPath();
    ctx.moveTo(x(0), y(vals[0]));
    points.forEach((p, i) => ctx.lineTo(x(i), y(p.value)));
    ctx.lineTo(x(points.length - 1), h - pad);
    ctx.lineTo(x(0), h - pad);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, up ? "rgba(34,197,94,0.20)" : "rgba(239,68,68,0.20)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = grad; ctx.fill();

    // line
    ctx.beginPath();
    ctx.moveTo(x(0), y(vals[0]));
    points.forEach((p, i) => ctx.lineTo(x(i), y(p.value)));
    ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.stroke();
  }, [points]);
  return <canvas ref={ref} style={{ width: "100%", height: 200, display: "block" }} />;
}

function Tile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: "var(--bg-2)", padding: "11px 13px" }}>
      <div className="kicker" style={{ fontSize: 8.5, marginBottom: 5 }}>{label}</div>
      <div className="mono" style={{ fontSize: 16, fontWeight: 600, color: color || "var(--ink)" }}>{value}</div>
    </div>
  );
}

export default function Symphony() {
  const [examples, setExamples] = useState<Example[]>([]);
  const [name, setName] = useState("");
  const [json, setJson] = useState("");
  const [cadence, setCadence] = useState("weekly");
  const [capital, setCapital] = useState(10000);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/symphony/examples").then(r => r.json()).then(d => {
      const ex: Example[] = d.examples || [];
      setExamples(ex);
      if (ex.length) loadExample(ex[0]);
    }).catch(() => {});
  }, []);

  const loadExample = (e: Example) => {
    setName(e.name);
    setCadence(e.cadence || "weekly");
    setJson(JSON.stringify(e.tree, null, 2));
    setResult(null); setError(null);
  };

  const run = async () => {
    setError(null);
    let tree: any;
    try { tree = JSON.parse(json); }
    catch { setError("Strategy JSON is not valid."); return; }
    setRunning(true);
    try {
      const r = await fetch("/api/symphony/backtest", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tree, cadence, starting_capital: capital }),
      });
      const d: BacktestResult = await r.json();
      if (d.error) { setError(d.error); setResult(null); }
      else setResult(d);
    } catch (e: any) {
      setError(String(e));
    } finally { setRunning(false); }
  };

  const m = result?.metrics;
  const pct = (n: number) => `${n >= 0 ? "+" : ""}${n}%`;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "380px 1fr", height: "100%", overflow: "hidden" }}>
      {/* ── Builder ── */}
      <div style={{ borderRight: "1px solid var(--line-dim)", overflow: "auto", padding: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <span style={{ width: 3, height: 16, background: "var(--cyan)", boxShadow: "0 0 10px var(--cyan-glow)" }} />
          <span className="mono" style={{ fontSize: 13, fontWeight: 700, letterSpacing: "0.14em" }}>SYMPHONY</span>
        </div>

        <div className="kicker" style={{ marginBottom: 8 }}>Examples</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 18 }}>
          {examples.map(e => (
            <Button key={e.name} onClick={() => loadExample(e)}
              active={name === e.name}
              style={{ textAlign: "left", fontSize: 10, lineHeight: 1.4, padding: "8px 10px" }}>
              {e.name}
            </Button>
          ))}
        </div>

        <div className="kicker" style={{ marginBottom: 8 }}>Strategy (JSON tree)</div>
        <textarea value={json} onChange={e => setJson(e.target.value)} spellCheck={false}
          style={{ width: "100%", height: 240, background: "var(--bg-3)", color: "var(--ink)",
            border: "1px solid var(--line-dim)", fontFamily: "var(--mono)", fontSize: 11,
            padding: 10, resize: "vertical", outline: "none", boxSizing: "border-box" }} />

        <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
          <div style={{ flex: 1 }}>
            <div className="kicker" style={{ marginBottom: 6 }}>Cadence</div>
            <select value={cadence} onChange={e => setCadence(e.target.value)}
              style={{ width: "100%", background: "var(--bg-3)", color: "var(--ink)",
                border: "1px solid var(--line-dim)", fontFamily: "var(--mono)", fontSize: 11, padding: "7px 8px" }}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <div className="kicker" style={{ marginBottom: 6 }}>Capital</div>
            <input type="number" value={capital} onChange={e => setCapital(Number(e.target.value) || 0)}
              style={{ width: "100%", background: "var(--bg-3)", color: "var(--ink)",
                border: "1px solid var(--line-dim)", fontFamily: "var(--mono)", fontSize: 11, padding: "7px 8px", boxSizing: "border-box" }} />
          </div>
        </div>

        <Button active onClick={run} disabled={running}
          style={{ width: "100%", marginTop: 14, padding: "10px" }}>
          {running ? "RUNNING BACKTEST…" : "▶ RUN BACKTEST"}
        </Button>
        {error && <div className="mono" style={{ marginTop: 10, fontSize: 10, color: "var(--red)" }}>{error}</div>}
      </div>

      {/* ── Results ── */}
      <div style={{ overflow: "auto", padding: 16 }}>
        {!result ? (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-faint)" }}>
            {running ? "Running backtest…" : "Pick a strategy and run a backtest."}
          </div>
        ) : (
          <>
            {result.missing_tickers?.length > 0 && (
              <div className="mono" style={{ fontSize: 10, color: "var(--amber)", marginBottom: 10 }}>
                No data for: {result.missing_tickers.join(", ")}
              </div>
            )}
            <div className="exec-card" style={{ marginBottom: 14 }}>
              <div className="panel-head"><span className="panel-title">Equity Curve</span>
                <span className="mono" style={{ fontSize: 10, color: "var(--ink-dim)" }}>
                  {result.start} → {result.end} · {result.rebalances} rebalances
                </span>
              </div>
              <div style={{ padding: 8 }}><Curve points={result.equity_curve} /></div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 1,
              background: "var(--line-dim)", marginBottom: 14 }}>
              <Tile label="Total Return" value={m ? pct(m.total_return_pct) : "—"}
                color={m && m.total_return_pct >= 0 ? "var(--green)" : "var(--red)"} />
              <Tile label="CAGR" value={m ? pct(m.cagr_pct) : "—"}
                color={m && m.cagr_pct >= 0 ? "var(--green)" : "var(--red)"} />
              <Tile label="Max DD" value={m ? `${m.max_drawdown_pct}%` : "—"}
                color={m && m.max_drawdown_pct > 15 ? "var(--red)" : "var(--ink)"} />
              <Tile label="Sharpe" value={m ? m.sharpe.toFixed(2) : "—"}
                color={m && m.sharpe >= 1 ? "var(--cyan)" : "var(--ink)"} />
              <Tile label="Volatility" value={m ? `${m.volatility_pct}%` : "—"} />
            </div>

            <div className="exec-card">
              <div className="panel-head"><span className="panel-title">Final Target Weights</span></div>
              <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
                {Object.entries(result.final_weights || {}).length === 0 ? (
                  <span className="mono" style={{ fontSize: 11, color: "var(--ink-faint)" }}>In cash / no allocation.</span>
                ) : Object.entries(result.final_weights).sort((a, b) => b[1] - a[1]).map(([t, w]) => (
                  <div key={t} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span className="mono" style={{ fontSize: 11, width: 56, color: "var(--cyan)" }}>{t}</span>
                    <div style={{ flex: 1, height: 6, background: "var(--bg-4)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${w * 100}%`, background: "var(--cyan)", borderRadius: 3 }} />
                    </div>
                    <span className="mono" style={{ fontSize: 11, width: 48, textAlign: "right", color: "var(--ink)" }}>
                      {(w * 100).toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
