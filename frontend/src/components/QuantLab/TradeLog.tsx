/**
 * TradeLog — paginated table of individual simulated trades.
 * Clearly labels all data as backtested.
 */

import React, { useState } from "react";

interface Trade {
  id:             string;
  entry_date:     string;
  exit_date:      string;
  entry_price:    number;
  exit_price:     number;
  shares:         number;
  direction:      string;
  exit_reason:    string;
  pnl:            number;
  pnl_pct:        number;
  commission_paid: number;
  hold_days:      number;
  mfe?:           number;
  mae?:           number;
}

interface Props {
  trades: Trade[];
}

const PAGE_SIZE = 20;

const cell: React.CSSProperties = {
  padding: "5px 8px", fontFamily: "var(--mono)", fontSize: 11,
  borderBottom: "1px solid var(--line-dim)",
};

const hdr: React.CSSProperties = {
  ...cell, fontSize: 9, color: "var(--ink-dim)", letterSpacing: "0.08em",
  textTransform: "uppercase", background: "var(--bg-2)", borderBottom: "2px solid var(--line-dim)",
};

export default function TradeLog({ trades }: Props) {
  const [page, setPage] = useState(0);
  const totalPages = Math.ceil(trades.length / PAGE_SIZE);
  const visible    = trades.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  if (!trades.length) {
    return (
      <div style={{ color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11, textAlign: "center", padding: 24 }}>
        No trades in this backtest.
      </div>
    );
  }

  return (
    <div>
      <div style={{
        fontFamily: "var(--mono)", fontSize: 9, color: "var(--amber, #ffb800)",
        letterSpacing: "0.08em", marginBottom: 8, textTransform: "uppercase",
      }}>
        Trade Log — BACKTESTED — NOT LIVE PERFORMANCE ({trades.length} trades)
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {["Entry", "Exit", "Dir", "Entry $", "Exit $", "Shares", "P&L", "P&L %", "Reason", "Days", "Commission"].map(h => (
                <th key={h} style={{ ...hdr, textAlign: "left" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map(t => {
              const pnlColor = t.pnl >= 0 ? "var(--green)" : "var(--red)";
              return (
                <tr key={t.id} style={{ background: "var(--bg-1)" }}>
                  <td style={cell}>{t.entry_date}</td>
                  <td style={cell}>{t.exit_date}</td>
                  <td style={{ ...cell, color: t.direction === "LONG" ? "var(--green)" : "var(--red)" }}>{t.direction}</td>
                  <td style={cell}>${t.entry_price.toFixed(2)}</td>
                  <td style={cell}>${t.exit_price.toFixed(2)}</td>
                  <td style={cell}>{t.shares}</td>
                  <td style={{ ...cell, color: pnlColor, fontWeight: 600 }}>${t.pnl.toFixed(2)}</td>
                  <td style={{ ...cell, color: pnlColor }}>{(t.pnl_pct * 100).toFixed(2)}%</td>
                  <td style={{ ...cell, color: "var(--ink-dim)" }}>{t.exit_reason}</td>
                  <td style={cell}>{t.hold_days}</td>
                  <td style={{ ...cell, color: "var(--ink-faint)" }}>${t.commission_paid.toFixed(2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, fontFamily: "var(--mono)", fontSize: 11 }}>
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} style={{
            background: "var(--bg-3)", border: "1px solid var(--line-dim)", color: "var(--ink)",
            padding: "4px 10px", cursor: page === 0 ? "default" : "pointer", fontFamily: "var(--mono)", fontSize: 11,
          }}>←</button>
          <span style={{ color: "var(--ink-dim)" }}>Page {page + 1} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1} style={{
            background: "var(--bg-3)", border: "1px solid var(--line-dim)", color: "var(--ink)",
            padding: "4px 10px", cursor: page === totalPages - 1 ? "default" : "pointer", fontFamily: "var(--mono)", fontSize: 11,
          }}>→</button>
        </div>
      )}
    </div>
  );
}
