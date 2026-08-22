/**
 * ResultsPanel — displays backtest metric tiles with the BACKTESTED disclaimer.
 */

import React from "react";

interface Props {
  results: Record<string, any>;
}

function MetricTile({ label, value, color = "var(--ink)" }: {
  label: string; value: string; color?: string;
}) {
  return (
    <div style={{
      background: "var(--bg-3)", border: "1px solid var(--line-dim)",
      padding: "10px 12px", display: "flex", flexDirection: "column", gap: 3,
    }}>
      <div style={{ fontSize: 9, fontFamily: "var(--mono)", color: "var(--ink-dim)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ fontSize: 16, fontFamily: "var(--mono)", fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

export default function ResultsPanel({ results }: Props) {
  const pct  = (v: any) => typeof v === "number" ? `${v.toFixed(2)}%` : "—";
  const num  = (v: any, d = 2) => typeof v === "number" ? v.toFixed(d) : "—";
  const int  = (v: any) => typeof v === "number" ? v.toFixed(0) : "—";
  const usd  = (v: any) => typeof v === "number" ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2 })}` : "—";

  const totalRet = results.total_return_pct ?? 0;
  const sharpe   = results.sharpe_ratio ?? 0;

  const RETURN_METRICS = [
    { label: "Total Return",         value: pct(results.total_return_pct),  color: totalRet >= 0 ? "var(--green)" : "var(--red)" },
    { label: "CAGR",                 value: pct(results.cagr_pct),          color: (results.cagr_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" },
    { label: "Ending Capital",       value: usd(results.ending_capital),    color: "var(--ink)" },
    { label: "Avg Return / Trade",   value: usd(results.avg_return_per_trade), color: "var(--ink)" },
  ];

  const RISK_METRICS = [
    { label: "Sharpe Ratio",         value: num(results.sharpe_ratio),      color: sharpe >= 1 ? "var(--cyan)" : "var(--ink)" },
    { label: "Sortino Ratio",        value: num(results.sortino_ratio),     color: "var(--ink)" },
    { label: "Max Drawdown",         value: pct(results.max_drawdown_pct),  color: "var(--red)" },
    { label: "Consec. Losses",       value: int(results.consecutive_losses), color: "var(--ink)" },
  ];

  const TRADE_METRICS = [
    { label: "Win Rate",             value: pct(results.win_rate),          color: "var(--ink)" },
    { label: "Profit Factor",        value: num(results.profit_factor),     color: "var(--ink)" },
    { label: "Expectancy",           value: usd(results.expectancy),        color: "var(--ink)" },
    { label: "Total Trades",         value: int(results.total_trades),      color: "var(--ink)" },
    { label: "Avg Duration (days)",  value: num(results.avg_trade_duration, 1), color: "var(--ink)" },
    { label: "Avg MFE",             value: pct(results.avg_mfe),           color: "var(--green)" },
    { label: "Avg MAE",             value: pct(results.avg_mae),           color: "var(--red)" },
    { label: "Winning / Losing",     value: `${int(results.winning_trades)} / ${int(results.losing_trades)}`, color: "var(--ink)" },
  ];

  const section = (title: string, metrics: { label: string; value: string; color?: string }[]) => (
    <div style={{ marginBottom: 16 }}>
      <div className="kicker" style={{ marginBottom: 8 }}>{title}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
        {metrics.map(m => <MetricTile key={m.label} {...m} />)}
      </div>
    </div>
  );

  return (
    <div>
      <div style={{
        padding: "6px 12px", background: "var(--amber, #ffb800)22",
        border: "1px solid var(--amber, #ffb800)",
        fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em",
        color: "var(--amber, #ffb800)", marginBottom: 16, textAlign: "center",
      }}>
        ⚠ BACKTESTED — NOT LIVE PERFORMANCE
      </div>

      {section("Return Metrics",      RETURN_METRICS)}
      {section("Risk Metrics",        RISK_METRICS)}
      {section("Trade Quality",       TRADE_METRICS)}
    </div>
  );
}
