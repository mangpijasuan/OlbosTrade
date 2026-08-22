/**
 * QuantLab/BacktestLab — Backtest Lab page.
 *
 * Users configure a backtest (symbol, dates, timeframe, costs), select a
 * saved strategy (or use an inline config), run the backtest, then view the
 * full metric suite, equity curve, drawdown curve, and trade log.
 *
 * All results are clearly labelled "BACKTESTED — NOT LIVE PERFORMANCE".
 */

import React, { useState, useEffect, useRef } from "react";
import { api } from "../../api/client";
import BacktestForm, { BacktestFormValues } from "../../components/QuantLab/BacktestForm";
import ResultsPanel from "../../components/QuantLab/ResultsPanel";
import EquityCurveChart from "../../components/QuantLab/EquityCurveChart";
import TradeLog from "../../components/QuantLab/TradeLog";
import TabBar from "../../components/TabBar";

const TABS = [
  { key: "metrics",   label: "Metrics" },
  { key: "equity",    label: "Equity Curve" },
  { key: "trades",    label: "Trade Log" },
  { key: "monthly",   label: "Monthly Returns" },
];

interface Strategy {
  strategy_id: string;
  name: string;
  current_version: number;
}

const sel: React.CSSProperties = {
  width: "100%", background: "var(--bg-3)", border: "1px solid var(--line-dim)",
  color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12,
  padding: "7px 10px", outline: "none", boxSizing: "border-box",
};

export default function BacktestLab({ preselectedStrategyId }: { preselectedStrategyId?: string }) {
  const [form, setForm] = useState<BacktestFormValues>({
    symbol: "SPY",
    start_date: "2022-01-01",
    end_date: "2024-12-31",
    timeframe: "1d",
    starting_capital: 100000,
    commission_per_share: 0.005,
    spread_pct: 0.001,
    slippage_pct: 0.001,
  });

  const [strategies, setStrategies]       = useState<Strategy[]>([]);
  const [selectedStratId, setSelectedStratId] = useState<string>(preselectedStrategyId ?? "");
  const [runId, setRunId]                 = useState<string | null>(null);
  const [results, setResults]             = useState<Record<string, any> | null>(null);
  const [loading, setLoading]             = useState(false);
  const [error, setError]                 = useState<string | null>(null);
  const [tab, setTab]                     = useState("metrics");
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load saved strategies for the strategy picker
  useEffect(() => {
    api.get("/api/quant/strategies")
      .then(r => setStrategies(r.data.strategies ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (preselectedStrategyId) setSelectedStratId(preselectedStrategyId);
  }, [preselectedStrategyId]);

  // Poll for results when we have a run_id
  useEffect(() => {
    if (!runId) return;

    const poll = async () => {
      try {
        const res = await api.get(`/api/quant/backtest/${runId}`);
        const data = res.data;
        if (data.status === "completed" || data.status === "failed") {
          setResults(data);
          setLoading(false);
          if (data.status === "failed") setError(data.error ?? "Backtest failed");
        } else {
          pollRef.current = setTimeout(poll, 2000);
        }
      } catch (e: any) {
        setLoading(false);
        setError(String(e));
      }
    };

    pollRef.current = setTimeout(poll, 1000);
    return () => { if (pollRef.current) clearTimeout(pollRef.current); };
  }, [runId]);

  const handleRun = async () => {
    if (!selectedStratId) {
      setError("Select a saved strategy first, or go to Strategy Builder to create one.");
      return;
    }
    setLoading(true);
    setError(null);
    setResults(null);
    setRunId(null);
    try {
      const res = await api.post("/api/quant/backtest", {
        strategy_id: selectedStratId,
        ...form,
      });
      setRunId(res.data.run_id);
    } catch (e: any) {
      setLoading(false);
      setError(e?.response?.data?.detail ?? String(e));
    }
  };

  const handleExport = async () => {
    if (!runId) return;
    const res = await api.get(`/api/quant/backtest/${runId}/export`);
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url; a.download = `backtest-${runId.slice(0, 8)}.json`;
    a.click(); URL.revokeObjectURL(url);
  };

  const done = results?.status === "completed";

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", height: "100%", overflow: "hidden" }}>
      {/* Left: config */}
      <div style={{ borderRight: "1px solid var(--line-dim)", overflowY: "auto", padding: 16 }}>
        <div className="panel-title" style={{ marginBottom: 16 }}>Backtest Lab</div>

        <div style={{ marginBottom: 14 }}>
          <div className="kicker" style={{ marginBottom: 5 }}>Strategy</div>
          <select style={sel} value={selectedStratId} onChange={e => setSelectedStratId(e.target.value)}>
            <option value="">— Select a strategy —</option>
            {strategies.map(s => (
              <option key={s.strategy_id} value={s.strategy_id}>
                {s.name} v{s.current_version}
              </option>
            ))}
          </select>
          {strategies.length === 0 && (
            <div style={{ marginTop: 5, fontSize: 9, color: "var(--ink-faint)", fontFamily: "var(--mono)" }}>
              No strategies saved. Create one in the Strategy Builder tab.
            </div>
          )}
        </div>

        <BacktestForm values={form} onChange={setForm} onRun={handleRun} loading={loading} />

        {loading && (
          <div style={{ marginTop: 12, fontFamily: "var(--mono)", fontSize: 11, color: "var(--cyan)" }}>
            ⟳ Running backtest…
          </div>
        )}
        {error && (
          <div style={{ marginTop: 10, color: "var(--red)", fontFamily: "var(--mono)", fontSize: 11 }}>
            ✖ {error}
          </div>
        )}
      </div>

      {/* Right: results */}
      <div style={{ overflowY: "auto", display: "flex", flexDirection: "column" }}>
        {!done && !loading && (
          <div style={{
            flex: 1, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center",
            color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 12,
          }}>
            <div style={{ fontSize: 11, letterSpacing: "0.08em" }}>Configure and run a backtest</div>
            <div style={{ fontSize: 9, marginTop: 6, color: "var(--ink-faint)" }}>
              Results will appear here — labelled BACKTESTED — NOT LIVE PERFORMANCE
            </div>
          </div>
        )}

        {loading && (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cyan)" }}>
              ⟳ Running backtest — please wait…
            </div>
          </div>
        )}

        {done && results && (
          <div style={{ padding: 16, flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div className="panel-title">
                {results.symbol} · {results.start_date} → {results.end_date}
              </div>
              <button onClick={handleExport} style={{
                background: "none", border: "1px solid var(--line-dim)", color: "var(--ink-dim)",
                fontFamily: "var(--mono)", fontSize: 10, padding: "3px 10px", cursor: "pointer",
              }}>⬇ Export</button>
            </div>

            <TabBar tabs={TABS} active={tab} onChange={setTab} />

            <div style={{ marginTop: 12 }}>
              {tab === "metrics" && <ResultsPanel results={results} />}
              {tab === "equity" && (
                <EquityCurveChart
                  equityCurve={results.equity_curve ?? []}
                  drawdownCurve={results.drawdown_curve ?? []}
                  height={140}
                />
              )}
              {tab === "trades" && <TradeLog trades={results.trades ?? []} />}
              {tab === "monthly" && (
                <MonthlyHeatmap data={results.monthly_returns ?? []} />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Monthly Returns Heatmap ────────────────────────────────────────────────────

const MONTH_LABELS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function MonthlyHeatmap({ data }: { data: { year: number; month: number; return_pct: number }[] }) {
  if (!data.length) return (
    <div style={{ color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11, textAlign: "center", padding: 24 }}>
      No monthly data available.
    </div>
  );

  const years = Array.from(new Set(data.map(d => d.year))).sort();
  const byYM: Record<string, number> = {};
  data.forEach(d => { byYM[`${d.year}-${d.month}`] = d.return_pct; });

  const maxAbs = Math.max(...data.map(d => Math.abs(d.return_pct)), 0.01);

  const cellBg = (v: number | undefined) => {
    if (v === undefined) return "var(--bg-3)";
    const intensity = Math.min(Math.abs(v) / maxAbs, 1);
    if (v > 0) return `rgba(0,200,100,${0.15 + intensity * 0.55})`;
    return `rgba(220,50,50,${0.15 + intensity * 0.55})`;
  };

  return (
    <div>
      <div style={{ marginBottom: 8, fontFamily: "var(--mono)", fontSize: 9, color: "var(--amber, #ffb800)", letterSpacing: "0.08em" }}>
        MONTHLY RETURNS — BACKTESTED — NOT LIVE PERFORMANCE
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontFamily: "var(--mono)", fontSize: 10 }}>
          <thead>
            <tr>
              <th style={{ padding: "4px 10px", color: "var(--ink-dim)", textAlign: "left" }}>Year</th>
              {MONTH_LABELS.map(m => (
                <th key={m} style={{ padding: "4px 8px", color: "var(--ink-dim)", textAlign: "center", fontSize: 9 }}>{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {years.map(y => (
              <tr key={y}>
                <td style={{ padding: "4px 10px", color: "var(--ink-dim)", fontWeight: 600 }}>{y}</td>
                {[1,2,3,4,5,6,7,8,9,10,11,12].map(m => {
                  const v = byYM[`${y}-${m}`];
                  return (
                    <td key={m} style={{
                      padding: "5px 8px", background: cellBg(v),
                      color: v !== undefined ? (v >= 0 ? "var(--green)" : "var(--red)") : "var(--ink-faint)",
                      textAlign: "center", borderRadius: 2, fontSize: 10,
                    }}>
                      {v !== undefined ? `${v.toFixed(1)}%` : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
