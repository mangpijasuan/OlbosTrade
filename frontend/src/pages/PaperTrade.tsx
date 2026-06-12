import React, { useState } from "react";
import { usePaperTrade } from "../hooks/usePaperTrade";
import TradingModeSelector from "../components/TradingModeSelector";

export default function PaperTrade() {
  const { positions, lastSignal, cycleLog, loading, runCycle } = usePaperTrade();
  const [tab, setTab] = useState<"signals"|"positions"|"mode">("signals");

  const Badge = ({ text, color }: { text: string; color: string }) => (
    <span style={{
      fontFamily: "var(--mono)", fontSize: 10, padding: "2px 8px",
      border: `1px solid ${color}40`, background: `${color}15`,
      color, letterSpacing: "0.08em",
    }}>{text}</span>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Toolbar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "8px 16px", borderBottom: "1px solid var(--line-dim)",
        background: "var(--bg-2)",
      }}>
        <div style={{ display: "flex", gap: 1 }}>
          {(["signals","positions","mode"] as const).map(t => (
            <button key={t} className={`btn-t ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}
              style={{ borderRadius: 0 }}>
              {t.toUpperCase()}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button className="btn-t" onClick={runCycle} style={{ color: "var(--cyan)", borderColor: "var(--cyan)" }}>
          {loading ? "RUNNING..." : "▶ RUN SIGNAL CYCLE"}
        </button>
        <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          NEXT: 09:35 ET
        </div>
      </div>

      <div style={{ flex: 1, overflow: "auto" }}>
        {tab === "signals" && (
          <div>
            {/* Last signal */}
            {lastSignal && (
              <div style={{
                padding: "12px 16px",
                borderBottom: "1px solid var(--line-dim)",
                background: "var(--bg-3)",
                display: "flex", gap: 24, alignItems: "center",
              }}>
                <span className="panel-title">LAST SIGNAL</span>
                <Badge text={lastSignal.strategy?.toUpperCase() || "—"} color="var(--cyan)" />
                <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
                  Score: <span style={{ color: "var(--ink)" }}>{lastSignal.signal_score?.toFixed(3) || "—"}</span>
                </span>
                <Badge
                  text={lastSignal.approved ? "APPROVED" : "REJECTED"}
                  color={lastSignal.approved ? "var(--green)" : "var(--red)"}
                />
              </div>
            )}

            {/* Cycle log */}
            <table className="t-table">
              <thead><tr>
                {["Time","Action","Strategy","IV Rank","Score","Regime","Result"].map(h => <th key={h}>{h}</th>)}
              </tr></thead>
              <tbody>
                {(cycleLog || []).length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: "center", padding: 40, color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11 }}>
                      NO SIGNAL HISTORY — RUN A CYCLE OR WAIT FOR 09:35 ET
                    </td>
                  </tr>
                ) : (
                  (cycleLog || []).map((l: any, i: number) => (
                    <tr key={i}>
                      <td className="mono" style={{ color: "var(--ink-dim)" }}>{l.time || "—"}</td>
                      <td className="mono" style={{ color: "var(--cyan)" }}>{l.action?.toUpperCase() || "—"}</td>
                      <td className="mono">{l.strategy || "—"}</td>
                      <td className="mono">{l.iv_rank?.toFixed(1) || "—"}</td>
                      <td className="mono">{l.signal_score?.toFixed(3) || "—"}</td>
                      <td className="mono" style={{ color: "var(--amber)" }}>{l.regime || "—"}</td>
                      <td>
                        <Badge
                          text={l.action === "filled" ? "FILLED" : l.action === "rejected" ? "REJECTED" : l.action?.toUpperCase() || "—"}
                          color={l.action === "filled" ? "var(--green)" : l.action === "rejected" ? "var(--red)" : "var(--ink-dim)"}
                        />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {tab === "positions" && (
          <table className="t-table">
            <thead><tr>
              {["Symbol","Strategy","Legs","Entry Credit","Current Value","P&L","DTE","Mode"].map(h => <th key={h}>{h}</th>)}
            </tr></thead>
            <tbody>
              {(positions || []).length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ textAlign: "center", padding: 40, color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11 }}>
                    NO OPEN POSITIONS
                  </td>
                </tr>
              ) : (
                (positions || []).map((p: any, i: number) => {
                  const pnl = p.unrealized_pnl || 0;
                  return (
                    <tr key={i}>
                      <td className="mono" style={{ color: "var(--cyan)" }}>{p.symbol || "SPY"}</td>
                      <td className="mono">{p.strategy || "—"}</td>
                      <td className="mono">{p.legs || 2}</td>
                      <td className="mono">${p.entry_credit?.toFixed(2) || "—"}</td>
                      <td className="mono">${p.current_value?.toFixed(2) || "—"}</td>
                      <td className="mono" style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                        {pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}
                      </td>
                      <td className="mono">{p.dte || "—"}d</td>
                      <td><span className={`mode-badge ${p.trading_mode || "balanced"}`}>{p.trading_mode || "balanced"}</span></td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}

        {tab === "mode" && (
          <div style={{ padding: 20, maxWidth: 680 }}>
            <div className="panel-title" style={{ marginBottom: 16 }}>Trading Mode</div>
            <TradingModeSelector />
          </div>
        )}
      </div>
    </div>
  );
}
