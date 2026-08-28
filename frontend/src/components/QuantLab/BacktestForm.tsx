/**
 * BacktestForm — input form for the Backtest Lab.
 * Renders symbol, date range, timeframe, capital, cost assumptions.
 */

import React from "react";
import { Button } from "../ui";

const TIMEFRAMES = ["1d", "1wk", "1h", "15m", "5m", "1m"];
const SYMBOLS    = ["SPY", "QQQ", "AAPL", "MSFT", "TSLA", "AMZN", "NVDA", "AMD", "META", "GOOGL"];

const inp: React.CSSProperties = {
  width: "100%", background: "var(--bg-3)", border: "1px solid var(--line-dim)",
  color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12,
  padding: "7px 10px", outline: "none", boxSizing: "border-box",
};

interface BacktestFormValues {
  symbol:               string;
  start_date:           string;
  end_date:             string;
  timeframe:            string;
  starting_capital:     number;
  commission_per_share: number;
  spread_pct:           number;
  slippage_pct:         number;
}

interface Props {
  values:   BacktestFormValues;
  onChange: (v: BacktestFormValues) => void;
  onRun:    () => void;
  loading:  boolean;
}

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div style={{ marginBottom: 12 }}>
    <div className="kicker" style={{ marginBottom: 5 }}>{label}</div>
    {children}
  </div>
);

export default function BacktestForm({ values, onChange, onRun, loading }: Props) {
  const set = (patch: Partial<BacktestFormValues>) => onChange({ ...values, ...patch });

  return (
    <div>
      <Field label="Symbol">
        <select style={inp} value={values.symbol} onChange={e => set({ symbol: e.target.value })}>
          {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </Field>
      <Field label="Timeframe">
        <select style={inp} value={values.timeframe} onChange={e => set({ timeframe: e.target.value })}>
          {TIMEFRAMES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </Field>
      <Field label="Start Date">
        <input type="date" style={inp} value={values.start_date}
          onChange={e => set({ start_date: e.target.value })} />
      </Field>
      <Field label="End Date">
        <input type="date" style={inp} value={values.end_date}
          onChange={e => set({ end_date: e.target.value })} />
      </Field>
      <Field label="Starting Capital ($)">
        <input type="number" style={inp} value={values.starting_capital}
          onChange={e => set({ starting_capital: parseFloat(e.target.value) || 100000 })} />
      </Field>

      <div style={{
        margin: "14px 0", borderTop: "1px solid var(--line-dim)", paddingTop: 12,
      }}>
        <div className="kicker" style={{ marginBottom: 8 }}>Execution Assumptions</div>
        <Field label="Commission / share ($)">
          <input type="number" step="0.001" style={inp} value={values.commission_per_share}
            onChange={e => set({ commission_per_share: parseFloat(e.target.value) || 0 })} />
        </Field>
        <Field label="Spread (%)">
          <input type="number" step="0.001" style={inp} value={values.spread_pct}
            onChange={e => set({ spread_pct: parseFloat(e.target.value) || 0 })} />
        </Field>
        <Field label="Slippage (%)">
          <input type="number" step="0.001" style={inp} value={values.slippage_pct}
            onChange={e => set({ slippage_pct: parseFloat(e.target.value) || 0 })} />
        </Field>
      </div>

      <Button onClick={onRun} style={{ width: "100%", justifyContent: "center", display: "flex", padding: "10px" }}>
        {loading ? "Running…" : "Run Backtest ↗"}
      </Button>

      <div style={{
        marginTop: 10, fontSize: 9, fontFamily: "var(--mono)", color: "var(--ink-faint)",
        textAlign: "center", letterSpacing: "0.06em",
      }}>
        BACKTESTED — NOT LIVE PERFORMANCE
      </div>
    </div>
  );
}

export type { BacktestFormValues };
