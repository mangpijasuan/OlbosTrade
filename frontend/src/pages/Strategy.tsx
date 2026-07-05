import React, { useState } from "react";

const STRATEGIES = [
  { key: "bull_put_spread",       label: "Bull Put Spread",     type: "CREDIT", bias: "BULLISH", max_profit: "Net credit",   max_loss: "Width − credit",  legs: 2 },
  { key: "bear_call_spread",      label: "Bear Call Spread",    type: "CREDIT", bias: "BEARISH", max_profit: "Net credit",   max_loss: "Width − credit",  legs: 2 },
  { key: "iron_condor",           label: "Iron Condor",         type: "CREDIT", bias: "NEUTRAL", max_profit: "Net credit",   max_loss: "Width − credit",  legs: 4 },
  { key: "bull_call_debit_spread",label: "Bull Call Debit",     type: "DEBIT",  bias: "BULLISH", max_profit: "Width − debit",max_loss: "Net debit",       legs: 2 },
];

export default function Strategy() {
  const [selected, setSelected] = useState("bull_put_spread");
  const strat = STRATEGIES.find(s => s.key === selected)!;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", height: "100%", overflow: "hidden" }}>
      {/* List */}
      <div style={{ borderRight: "1px solid var(--line-dim)", background: "var(--bg-2)", overflowY: "auto" }}>
        <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
          <span className="panel-title">Strategies</span>
        </div>
        {STRATEGIES.map(s => (
          <button key={s.key} onClick={() => setSelected(s.key)}
            style={{
              width: "100%", padding: "13px 16px", textAlign: "left",
              background: selected === s.key ? "var(--cyan-dim)" : "transparent",
              border: "none", borderLeft: selected === s.key ? "2px solid var(--cyan)" : "2px solid transparent",
              borderBottom: "1px solid var(--line-dim)", cursor: "pointer",
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
            <div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: selected === s.key ? "var(--cyan)" : "var(--ink)" }}>
                {s.label}
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", marginTop: 2 }}>
                {s.legs} LEGS
              </div>
            </div>
            <span style={{
              fontFamily: "var(--mono)", fontSize: 9, padding: "1px 6px",
              background: s.type === "CREDIT" ? "rgba(212,175,55,0.1)" : "rgba(59,130,246,0.1)",
              color: s.type === "CREDIT" ? "var(--cyan)" : "var(--blue)",
              border: `1px solid ${s.type === "CREDIT" ? "rgba(212,175,55,0.3)" : "rgba(59,130,246,0.3)"}`,
            }}>{s.type}</span>
          </button>
        ))}
      </div>

      {/* Detail — Strategy Details promoted to the top; fills the freed space */}
      <div style={{ overflowY: "auto", padding: 20, display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Strategy Details (now the primary block at the top) */}
        <div>
          <div className="kicker" style={{ marginBottom: 8 }}>Strategy Details</div>
          <h2 style={{ fontFamily: "var(--mono)", fontSize: 24, fontWeight: 600, color: "var(--cyan)", marginBottom: 6 }}>
            {strat.label}
          </h2>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {[strat.type, strat.bias, `${strat.legs} LEGS`].map(tag => (
              <span key={tag} style={{
                fontFamily: "var(--mono)", fontSize: 10, padding: "2px 8px",
                border: "1px solid var(--line-dim)", color: "var(--ink-dim)",
              }}>{tag}</span>
            ))}
          </div>
        </div>

        {/* Key metrics — responsive grid (wraps cleanly, no fixed columns) */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 1, border: "1px solid var(--line-dim)" }}>
          {[
            { label: "Max Profit", val: strat.max_profit, color: "var(--green)" },
            { label: "Max Loss",   val: strat.max_loss,   color: "var(--red)" },
            { label: "Bias",       val: strat.bias,        color: "var(--amber)" },
          ].map(m => (
            <div key={m.label} style={{ padding: "18px 20px", background: "var(--bg-2)" }}>
              <div className="kicker" style={{ marginBottom: 6 }}>{m.label}</div>
              <div className="data-val sm" style={{ color: m.color }}>{m.val}</div>
            </div>
          ))}
        </div>

        {/* Current Signals — grows to fill the reclaimed vertical space */}
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--line-dim)", padding: 16, flex: 1, display: "flex", flexDirection: "column", minHeight: 200 }}>
          <div className="panel-title" style={{ marginBottom: 12 }}>Current Signals</div>
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
            NO SIGNALS — WAITING FOR 09:35 ET
          </div>
        </div>
      </div>
    </div>
  );
}
