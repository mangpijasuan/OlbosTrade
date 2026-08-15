import React, { useState } from "react";
import { api } from "../api/client";
import TradeMarkerChart from "../components/TradeMarkerChart";
import { Panel, Button } from "../components/ui";

const WATCHLIST = ["AAPL", "NVDA", "MSFT", "META", "AMZN", "QQQ", "SPY"];

const inputStyle: React.CSSProperties = {
  width: "100%", background: "var(--bg-3)", border: "1px solid var(--line-dim)",
  color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12,
  padding: "7px 10px", outline: "none",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="kicker" style={{ marginBottom: 6 }}>{label}</div>
      {children}
    </div>
  );
}

function pct(v: number | undefined) {
  return typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—";
}

export default function StrategyComparison() {
  const [symbol, setSymbol] = useState("AAPL");
  const [start, setStart] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 6);
    return d.toISOString().slice(0, 10);
  });
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [chartModel, setChartModel] = useState("Ours");

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const data: any = await api.getBaselineComparison(symbol, start, end);
      setResult(data);
      setChartModel("Ours");
    } catch (e: any) {
      setError(e?.message || "Comparison failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const models: any[] = result?.models || [];
  const bestPerColumn: Record<string, number> = {};
  const columns = [
    { key: "cumulative_return_pct", label: "CR%" },
    { key: "annual_return_pct", label: "ARR%" },
    { key: "sharpe_ratio", label: "SR" },
    // max_drawdown_pct is stored negative (e.g. -5.6) -- least-bad is the
    // value closest to zero, i.e. the numeric max, same rule as the other
    // three columns where bigger is unambiguously better.
    { key: "max_drawdown_pct", label: "MDD%" },
  ];
  for (const col of columns) {
    bestPerColumn[col.key] = Math.max(...models.map((m) => m.metrics[col.key]));
  }

  const selected = models.find((m) => m.name === chartModel);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", height: "100%", overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--line-dim)", padding: 16, overflowY: "auto", background: "var(--bg-2)" }}>
        <div className="panel-title" style={{ marginBottom: 16 }}>Strategy Comparison</div>
        <div style={{ fontSize: 11, color: "var(--ink-dim)", marginBottom: 16, lineHeight: 1.6 }}>
          Research only — runs our real equity signal engine alongside simple
          rule-based baselines over the same window, using one shared
          long/flat trading rule so the comparison is about signal quality,
          not execution. Not a trade recommendation.
        </div>
        <Field label="Symbol">
          <select style={inputStyle} value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {WATCHLIST.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="Start Date">
          <input type="date" style={inputStyle} value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
        <Field label="End Date">
          <input type="date" style={inputStyle} value={end} onChange={(e) => setEnd(e.target.value)} />
        </Field>
        <Button onClick={run} disabled={loading}
          style={{ width: "100%", marginTop: 8, padding: "10px", justifyContent: "center", display: "flex" }}>
          {loading ? "Running…" : "Run comparison ↗"}
        </Button>
        {error && (
          <div style={{ marginTop: 12, fontSize: 11, color: "var(--red)", fontFamily: "var(--mono)" }}>
            ⚠ {error}
          </div>
        )}
      </div>

      <div style={{ overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
        {!result ? (
          <div style={{
            height: 200, display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 12, color: "var(--ink-dim)",
          }}>
            Pick a symbol and date range, then run a comparison.
          </div>
        ) : (
          <>
            <Panel padding={0} title={`${result.symbol} · ${result.start} to ${result.end}`}>
              <table className="t-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    {columns.map((c) => <th key={c.key}>{c.label}</th>)}
                    <th>Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.name}
                      onClick={() => setChartModel(m.name)}
                      style={{ cursor: "pointer", background: chartModel === m.name ? "rgba(24,195,126,0.08)" : undefined }}>
                      <td className="mono" style={{ color: m.name === "Ours" ? "var(--cyan)" : "var(--ink)", fontWeight: m.name === "Ours" ? 700 : 400 }}>
                        {m.name}
                      </td>
                      {columns.map((c) => {
                        const val = m.metrics[c.key];
                        const isBest = val === bestPerColumn[c.key];
                        // Sharpe from a single (or zero) closed trade is undefined,
                        // not a genuine "0.00" — say so instead of showing a
                        // misleadingly precise number.
                        const display = c.key === "sharpe_ratio" && m.trades.length < 2
                          ? "n/a"
                          : c.key === "sharpe_ratio" ? val.toFixed(2) : pct(val);
                        return (
                          <td key={c.key} className="mono" style={{ color: isBest ? "var(--green)" : "var(--ink)" }}>
                            {display}
                          </td>
                        );
                      })}
                      <td className="mono" style={{ color: "var(--ink-dim)" }}>{m.trades.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            <Panel
              padding={12}
              title={`Trade History — ${chartModel}`}
              action={<span style={{ fontSize: 10, color: "var(--ink-faint)" }}>click a row above to switch model</span>}
            >
              {selected && (
                <TradeMarkerChart bars={result.bars} markers={selected.markers} equityCurve={selected.equity_curve} />
              )}
            </Panel>

            <div style={{ fontSize: 10, color: "var(--ink-faint)", fontFamily: "var(--mono)" }}>
              {result.disclaimer}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
