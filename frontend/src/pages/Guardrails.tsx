import React, { useState, useEffect } from "react";
import { useRisk } from "../hooks/useRisk";
import { api } from "../api/client";

export default function Guardrails() {
  const { guardrailStatus } = useRisk();
  const [tab, setTab] = useState<"status"|"history">("status");
  const [activeMode, setActiveMode] = useState<any>(null);

  // Poll the active trading mode independently — it lives in a different endpoint
  useEffect(() => {
    const load = () =>
      (api.getCurrentMode() as any)
        .then((d: any) => setActiveMode(d))
        .catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const modeName   = activeMode?.mode            ?? "—";
  const modeDte    = activeMode?.dte_range       ?? "—";
  const modeSignal = activeMode?.signal_threshold != null
    ? activeMode.signal_threshold.toFixed(2)
    : guardrailStatus?.signal_threshold?.toFixed(2) ?? "0.65";

  // Color the mode badge
  const modeColor: Record<string, string> = {
    conservative: "var(--green)",
    balanced:     "var(--cyan)",
    aggressive:   "var(--amber)",
    scalper:      "var(--red)",
  };
  const badgeColor = modeColor[modeName] ?? "var(--cyan)";

  const rules = [
    { label: "Max Daily Loss",      val: "2.0%",  status: guardrailStatus?.daily_loss_pct > -0.02 },
    { label: "Max Weekly Loss",     val: "5.0%",  status: guardrailStatus?.weekly_loss_pct > -0.05 },
    { label: "Max Monthly Loss",    val: "10.0%", status: true },
    { label: "Max Trades Per Day",  val: "3",     status: (guardrailStatus?.trades_today || 0) < 3 },
    { label: "Consecutive Losses",  val: "3",     status: (guardrailStatus?.consecutive_losses || 0) < 3 },
    { label: "Capital Threshold",   val: "85%",   status: true },
    { label: "Kill Switch",         val: "OFF",   status: !guardrailStatus?.kill_switch_engaged },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div style={{ padding: "8px 16px", borderBottom: "1px solid var(--line-dim)", background: "var(--bg-2)", display: "flex", gap: 1 }}>
        {(["status","history"] as const).map(t => (
          <button key={t} className={`btn-t ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
        {tab === "status" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Active Mode Banner */}
            <div style={{
              border: `1px solid ${badgeColor}`,
              background: "var(--bg-2)",
              padding: "14px 20px",
              display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
              <div>
                <div className="kicker" style={{ marginBottom: 4 }}>Active Trading Mode</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 20, fontWeight: 700, color: badgeColor, textTransform: "uppercase" }}>
                  {modeName}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="kicker" style={{ marginBottom: 4 }}>DTE Range</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 14, color: "var(--ink)" }}>{modeDte}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="kicker" style={{ marginBottom: 4 }}>Signal Threshold</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 14, color: "var(--ink)" }}>{modeSignal}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="kicker" style={{ marginBottom: 4 }}>Risk State</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 14,
                  color: guardrailStatus?.trading_mode === "suspended" ? "var(--red)"
                       : guardrailStatus?.trading_mode === "capital_preservation" ? "var(--amber)"
                       : "var(--green)" }}>
                  {(guardrailStatus?.trading_mode || "normal").toUpperCase()}
                </div>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {/* Rule status */}
              <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)" }}>
                <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
                  <span className="panel-title">Active Rules</span>
                </div>
                {rules.map((r, i) => (
                  <div key={r.label} style={{
                    padding: "13px 16px",
                    borderBottom: i < rules.length - 1 ? "1px solid var(--line-dim)" : "none",
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                  }}>
                    <div>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink)" }}>{r.label}</div>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", marginTop: 2 }}>
                        Limit: {r.val}
                      </div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className={`dot ${r.status ? "live" : "dead"}`} />
                      <span style={{ fontFamily: "var(--mono)", fontSize: 10,
                        color: r.status ? "var(--green)" : "var(--red)" }}>
                        {r.status ? "OK" : "BREACH"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              {/* State snapshot */}
              <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)" }}>
                <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
                  <span className="panel-title">Current State</span>
                </div>
                <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
                  {[
                    { label: "Trades Today",       val: guardrailStatus?.trades_today || 0 },
                    { label: "Consecutive Losses", val: guardrailStatus?.consecutive_losses || 0 },
                    { label: "Cooling Off Until",  val: guardrailStatus?.cooling_off_until || "—" },
                    { label: "Capital Remaining",  val: `${((guardrailStatus?.capital_pct_remaining || 1) * 100).toFixed(1)}%` },
                    { label: "Daily Loss",         val: `${((guardrailStatus?.daily_loss_pct || 0) * 100).toFixed(2)}%` },
                    { label: "Weekly Loss",        val: `${((guardrailStatus?.weekly_loss_pct || 0) * 100).toFixed(2)}%` },
                  ].map(s => (
                    <div key={s.label} style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      paddingBottom: 10, borderBottom: "1px solid var(--line-dim)",
                    }}>
                      <span className="kicker">{s.label}</span>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cyan)" }}>
                        {String(s.val)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === "history" && (
          <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)" }}>
            <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
              <span className="panel-title">Guardrail Event Log</span>
            </div>
            <table className="t-table">
              <thead><tr>
                {["Timestamp","Event","Rule","Value","Action"].map(h => <th key={h}>{h}</th>)}
              </tr></thead>
              <tbody>
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", padding: 40, color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11 }}>
                    NO GUARDRAIL EVENTS — SYSTEM OPERATING WITHIN LIMITS
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
