import React, { useState } from "react";
import { useBacktest } from "../hooks/useBacktest";

export default function Backtest() {
  const { results, loading, runBacktest } = useBacktest();
  const [form, setForm] = useState({
    strategy: "bull_put_spread", start_date: "2022-01-01",
    end_date: "2024-12-31", mode: "balanced",
  });

  const Panel = ({ title, children }: any) => (
    <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)" }}>
      <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)", display: "flex", alignItems: "center", gap: 8 }}>
        <span className="panel-title">{title}</span>
      </div>
      <div style={{ padding: 16 }}>{children}</div>
    </div>
  );

  const Field = ({ label, children }: any) => (
    <div style={{ marginBottom: 14 }}>
      <div className="kicker" style={{ marginBottom: 6 }}>{label}</div>
      {children}
    </div>
  );

  const inputStyle = {
    width: "100%", background: "var(--bg-3)", border: "1px solid var(--line-dim)",
    color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12,
    padding: "7px 10px", outline: "none",
  };

  const selectStyle = { ...inputStyle };

  const metrics = [
    { label: "Total Return",   val: results ? `${(results.total_return * 100).toFixed(1)}%` : "—",   color: results?.total_return >= 0 ? "var(--green)" : "var(--red)" },
    { label: "Sharpe Ratio",   val: results ? results.sharpe_ratio.toFixed(2) : "—",                 color: results?.sharpe_ratio >= 1 ? "var(--green)" : "var(--ink)" },
    { label: "Win Rate",       val: results ? `${(results.win_rate * 100).toFixed(1)}%` : "—",        color: "var(--ink)" },
    { label: "Max Drawdown",   val: results ? `${(results.max_drawdown * 100).toFixed(1)}%` : "—",    color: "var(--red)" },
    { label: "Profit Factor",  val: results ? results.profit_factor?.toFixed(2) : "—",               color: "var(--ink)" },
    { label: "Total Trades",   val: results ? results.total_trades : "—",                            color: "var(--ink)" },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", height: "100%", overflow: "hidden" }}>
      {/* Left: config */}
      <div style={{ borderRight: "1px solid var(--line-dim)", padding: 16, overflowY: "auto", background: "var(--bg-2)" }}>
        <div className="panel-title" style={{ marginBottom: 16 }}>Configuration</div>
        <Field label="Strategy">
          <select style={selectStyle} value={form.strategy}
            onChange={e => setForm({ ...form, strategy: e.target.value })}>
            <option value="bull_put_spread">Bull Put Spread</option>
            <option value="bear_call_spread">Bear Call Spread</option>
            <option value="iron_condor">Iron Condor</option>
            <option value="bull_call_debit_spread">Bull Call Debit</option>
          </select>
        </Field>
        <Field label="Mode">
          <select style={selectStyle} value={form.mode}
            onChange={e => setForm({ ...form, mode: e.target.value })}>
            {["conservative","balanced","aggressive","scalper"].map(m => (
              <option key={m} value={m}>{m.charAt(0).toUpperCase() + m.slice(1)}</option>
            ))}
          </select>
        </Field>
        <Field label="Start Date">
          <input type="date" style={inputStyle} value={form.start_date}
            onChange={e => setForm({ ...form, start_date: e.target.value })} />
        </Field>
        <Field label="End Date">
          <input type="date" style={inputStyle} value={form.end_date}
            onChange={e => setForm({ ...form, end_date: e.target.value })} />
        </Field>
        <button className="btn-t" onClick={() => runBacktest(form)}
          style={{ width: "100%", marginTop: 8, padding: "10px", justifyContent: "center", display: "flex" }}>
          {loading ? "Running…" : "Run backtest ↗"}
        </button>
      </div>

      {/* Right: results */}
      <div style={{ overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Metrics ribbon — tight single row to maximise chart space below. */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(6, 1fr)",
          border: "1px solid var(--line-dim)", borderRadius: 6,
          background: "var(--bg-2)", overflow: "hidden",
        }}>
          {metrics.map((m, i) => (
            <div key={m.label} style={{
              padding: "8px 12px",
              borderRight: i < 5 ? "1px solid var(--line-dim)" : "none",
              display: "flex", flexDirection: "column", gap: 3,
            }}>
              <div className="kicker">{m.label}</div>
              <div className="data-val sm" style={{ color: m.color }}>{m.val}</div>
            </div>
          ))}
        </div>

        {/* Equity curve placeholder */}
        <Panel title="Equity Curve">
          <div style={{
            height: 200, background: "var(--bg-3)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {results
              ? <span style={{ fontSize: 12, color: "var(--green)" }}>
                  Backtest complete — <span className="tnum">{results.total_trades}</span> trades
                </span>
              : <span style={{ fontSize: 12, color: "var(--ink-dim)" }}>
                  Configure and run a backtest
                </span>
            }
          </div>
        </Panel>

        {/* Trade log */}
        {results?.trades && (
          <Panel title="Trade Log">
            <table className="t-table">
              <thead><tr>
                {["Entry","Exit","Strategy","Credit","P&L","Exit Reason"].map(h => <th key={h}>{h}</th>)}
              </tr></thead>
              <tbody>
                {results.trades.slice(0, 20).map((t: any, i: number) => (
                  <tr key={i}>
                    <td className="mono">{t.entry_date}</td>
                    <td className="mono">{t.exit_date || "—"}</td>
                    <td className="mono" style={{ color: "var(--ink)" }}>{t.strategy}</td>
                    <td className="mono">${t.credit_received?.toFixed(2) || "—"}</td>
                    <td className="mono" style={{ color: t.pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                      {t.pnl >= 0 ? "+" : ""}${t.pnl?.toFixed(0) || 0}
                    </td>
                    <td className="mono" style={{ color: "var(--ink-dim)" }}>{t.exit_reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
      </div>
    </div>
  );
}
