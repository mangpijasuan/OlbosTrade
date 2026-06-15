import React from "react";
import { useRisk } from "../hooks/useRisk";

export default function RiskMonitor() {
  const { guardrailStatus, riskState } = useRisk();

  const Section = ({ title, children }: any) => (
    <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)", marginBottom: 16 }}>
      <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
        <span className="panel-title">{title}</span>
      </div>
      <div>{children}</div>
    </div>
  );

  const Meter = ({ label, val, max, unit = "", warn = 0.6, crit = 0.85 }: any) => {
    const ratio = Math.min(val / max, 1);
    const color = ratio < warn ? "var(--green)" : ratio < crit ? "var(--amber)" : "var(--red)";
    return (
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--line-dim)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
          <span className="kicker">{label}</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 12, color }}>
            {typeof val === "number" ? val.toFixed(val < 10 ? 2 : 0) : val}{unit}
            <span style={{ color: "var(--ink-faint)" }}> / {max}{unit}</span>
          </span>
        </div>
        <div className="bar-track" style={{ height: 4 }}>
          <div className="bar-fill" style={{ width: `${ratio * 100}%`, background: color }} />
        </div>
      </div>
    );
  };

  const Stat = ({ label, value, color }: any) => (
    <div style={{
      padding: "16px 18px",
      borderRight: "1px solid var(--line-dim)",
      borderBottom: "1px solid var(--line-dim)",
    }}>
      <div className="kicker" style={{ marginBottom: 6 }}>{label}</div>
      <div className="data-val" style={{ color: color || "var(--ink)" }}>{value}</div>
    </div>
  );

  const daily_loss  = Math.abs(guardrailStatus?.daily_loss_pct  || 0) * 100;
  const weekly_loss = Math.abs(guardrailStatus?.weekly_loss_pct || 0) * 100;
  // riskState comes from /api/risk/portfolio-state → response.state (IBKR account + DB P&L windows)
  const pv          = riskState?.state?.account_value ?? riskState?.portfolio_value ?? 25000;
  const daily_pnl   = riskState?.state?.daily_pnl ?? 0;

  return (
    <div style={{ padding: 16, overflowY: "auto", height: "100%" }}>

      {/* Header stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", marginBottom: 16, background: "var(--bg-2)", border: "1px solid var(--line-dim)" }}>
        <Stat label="Portfolio Value" value={`$${(pv/1000).toFixed(2)}k`} color="var(--cyan)" />
        <Stat label="Daily P&L"
          value={`${daily_pnl >= 0 ? "+" : ""}$${Math.abs(daily_pnl).toFixed(0)}`}
          color={daily_pnl >= 0 ? "var(--green)" : "var(--red)"} />
        <Stat label="Open Positions" value={riskState?.state?.open_positions || 0} />
        <Stat label="Status"
          value={guardrailStatus?.trading_allowed ? "ACTIVE" : "SUSPENDED"}
          color={guardrailStatus?.trading_allowed ? "var(--green)" : "var(--red)"} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <Section title="Loss Limits">
            <Meter label="Daily Loss" val={daily_loss} max={2} unit="%" />
            <Meter label="Weekly Loss" val={weekly_loss} max={5} unit="%" />
            <Meter label="Monthly Loss" val={Math.abs(guardrailStatus?.monthly_loss_pct||0)*100} max={10} unit="%" />
          </Section>
          <Section title="Position Limits">
            <Meter label="Trades Today" val={guardrailStatus?.trades_today||0} max={3} unit="" warn={0.5} crit={0.85} />
            <Meter label="Consecutive Losses" val={guardrailStatus?.consecutive_losses||0} max={3} unit="" warn={0.4} crit={0.7} />
            <Meter label="Open Positions" val={riskState?.state?.open_positions||0} max={5} unit="" />
          </Section>
        </div>
        <div>
          <Section title="Portfolio Greeks">
            {[
              { label: "Net Delta",  val: (riskState?.net_delta || 0).toFixed(4), warn: 0.30 },
              { label: "Net Gamma",  val: (riskState?.net_gamma || 0).toFixed(4), warn: null },
              { label: "Net Vega",   val: (riskState?.net_vega  || 0).toFixed(4), warn: null },
              { label: "Net Theta",  val: (riskState?.net_theta || 0).toFixed(4), warn: null },
            ].map(g => (
              <div key={g.label} style={{
                padding: "14px 16px",
                borderBottom: "1px solid var(--line-dim)",
                display: "flex", justifyContent: "space-between", alignItems: "center",
              }}>
                <span className="kicker">{g.label}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 14, color: "var(--ink)" }}>{g.val}</span>
              </div>
            ))}
          </Section>
          <Section title="Kill Switch">
            <div style={{ padding: 16, display: "flex", gap: 12, flexDirection: "column" }}>
              <p style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                Immediately cancel all open orders, flatten all positions,
                and halt the signal cycle. Cannot be undone without manual reset.
              </p>
              <button className="btn-t danger" style={{ padding: "10px 0", justifyContent: "center", display: "flex" }}>
                ⚡ ENGAGE KILL SWITCH
              </button>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
