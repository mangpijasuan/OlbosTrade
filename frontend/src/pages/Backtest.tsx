import React, { useState } from "react";
import { useBacktest } from "../hooks/useBacktest";

export default function Backtest() {
  const { results, loading, error, runBacktest } = useBacktest();
  const [form, setForm] = useState({
    strategy: "bull_put_spread", start_date: "2022-01-01",
    end_date: "2024-12-31",
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
  const completed = results?.status === "completed";
  const pct = (value: unknown) =>
    typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
  const num = (value: unknown, digits = 2) =>
    typeof value === "number" ? value.toFixed(digits) : "—";

  const metrics = [
    { label: "Total Return",   val: completed ? pct(results.total_return_pct) : "—",                 color: (results?.total_return_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" },
    { label: "Sharpe Ratio",   val: completed ? num(results.sharpe_ratio) : "—",                     color: (results?.sharpe_ratio ?? 0) >= 1 ? "var(--cyan)" : "var(--ink)" },
    { label: "Win Rate",       val: completed ? pct(results.win_rate) : "—",                         color: "var(--ink)" },
    { label: "Max Drawdown",   val: completed ? pct(results.max_drawdown_pct) : "—",                 color: "var(--red)" },
    { label: "Profit Factor",  val: completed ? num(results.profit_factor) : "—",                    color: "var(--ink)" },
    { label: "Total Trades",   val: completed ? results.total_trades : "—",                          color: "var(--ink)" },
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
          {loading ? "RUNNING..." : "RUN BACKTEST ↗"}
        </button>
        {results?.status && (
          <div style={{ marginTop: 10, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
            STATUS: <span style={{ color: results.status === "failed" ? "var(--red)" : results.status === "completed" ? "var(--green)" : "var(--amber)" }}>
              {String(results.status).toUpperCase()}
            </span>
          </div>
        )}
        {error && (
          <div style={{
            marginTop: 10, padding: "8px 10px", fontFamily: "var(--mono)", fontSize: 11,
            color: "var(--red)", border: "1px solid rgba(239,68,68,0.35)",
            background: "rgba(239,68,68,0.08)",
          }}>
            {error}
          </div>
        )}
      </div>

      {/* Right: results */}
      <div style={{ overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Metrics */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)" }}>
          {metrics.map((m, i) => (
            <div key={m.label} style={{
              padding: "14px 16px",
              borderRight: i < 5 ? "1px solid var(--line-dim)" : "none",
              borderBottom: "1px solid var(--line-dim)",
              background: "var(--bg-2)",
            }}>
              <div className="kicker" style={{ marginBottom: 6 }}>{m.label}</div>
              <div className="data-val" style={{ color: m.color }}>{m.val}</div>
            </div>
          ))}
        </div>

        {/* Equity curve placeholder */}
        <Panel title="Equity Curve">
          <div style={{
            height: 200, background: "var(--bg-3)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {completed
              ? <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cyan)" }}>
                  BACKTEST COMPLETE — {results.total_trades} TRADES
                </span>
              : results
                ? <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--amber)" }}>
                    BACKTEST {String(results.status || "QUEUED").toUpperCase()}
                  </span>
              : <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
                  CONFIGURE AND RUN BACKTEST
                </span>
            }
          </div>
        </Panel>

        {/* Trade log */}
        {completed && results?.trades && (
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
                    <td className="mono" style={{ color: "var(--cyan)" }}>{t.strategy}</td>
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
