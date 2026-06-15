/**
 * PortfolioGreeks — real-time display of net delta, vega, theta.
 */

import React, { useEffect, useState } from "react";

interface Greeks {
  net_delta: number;
  net_vega: number;
  net_theta: number;
  equity_position_count: number;
  options_position_count: number;
  total_position_count: number;
  is_delta_neutral: boolean;
  needs_hedge: boolean;
}

function GreekCell({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  const color = warn ? "var(--amber)" : Math.abs(value) < 0.001 ? "var(--ink-faint)" :
                value > 0 ? "var(--green)" : "var(--red)";
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
      <span style={{ color: "var(--ink-dim)", fontSize: 9, letterSpacing: "0.1em" }}>
        {label}
      </span>
      <span style={{ color, fontWeight: 600, fontSize: 14, fontFamily: "var(--mono)" }}>
        {value >= 0 ? "+" : ""}{value.toFixed(4)}
      </span>
    </div>
  );
}

export default function PortfolioGreeks() {
  const [greeks, setGreeks] = useState<Greeks | null>(null);

  useEffect(() => {
    const load = () =>
      fetch("/api/market/greeks")
        .then(r => r.json())
        .then(setGreeks)
        .catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  if (!greeks) {
    return (
      <div style={{
        background: "var(--bg-2)", border: "1px solid var(--line-dim)",
        borderRadius: 4, padding: "12px 16px",
        fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)",
      }}>
        Loading Greeks...
      </div>
    );
  }

  return (
    <div style={{
      background: "var(--bg-2)",
      border: `1px solid ${greeks.needs_hedge ? "var(--amber)" : "var(--line-dim)"}`,
      borderRadius: 4,
      padding: "12px 20px",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 4,
        marginBottom: 10, fontFamily: "var(--mono)", fontSize: 10,
        color: "var(--ink-dim)", letterSpacing: "0.08em",
      }}>
        PORTFOLIO GREEKS
        {greeks.needs_hedge && (
          <span style={{
            color: "var(--amber)", border: "1px solid var(--amber)",
            borderRadius: 2, padding: "1px 5px", fontSize: 9, marginLeft: 8,
          }}>
            HEDGE NEEDED
          </span>
        )}
        {greeks.is_delta_neutral && (
          <span style={{
            color: "var(--green)", border: "1px solid var(--green)",
            borderRadius: 2, padding: "1px 5px", fontSize: 9, marginLeft: 8,
          }}>
            DELTA NEUTRAL
          </span>
        )}
      </div>

      <div style={{ display: "flex", gap: 32, marginBottom: 10 }}>
        <GreekCell label="NET Δ" value={greeks.net_delta} warn={greeks.needs_hedge} />
        <GreekCell label="NET V" value={greeks.net_vega} />
        <GreekCell label="NET Θ/DAY" value={greeks.net_theta} />
      </div>

      <div style={{
        display: "flex", gap: 16, fontFamily: "var(--mono)", fontSize: 10,
        color: "var(--ink-faint)",
      }}>
        <span>EQ: {greeks.equity_position_count}</span>
        <span>OPT: {greeks.options_position_count}</span>
        <span>TOTAL: {greeks.total_position_count}</span>
      </div>
    </div>
  );
}
