import React, { useEffect, useState } from "react";
import TradingModeSelector from "../components/TradingModeSelector";
import { api } from "../api/client";

const STRATEGIES = [
  { key: "bull_put_spread",       label: "Bull Put Spread",     type: "CREDIT", bias: "BULLISH", max_profit: "Net credit",   max_loss: "Width − credit",  legs: 2 },
  { key: "bear_call_spread",      label: "Bear Call Spread",    type: "CREDIT", bias: "BEARISH", max_profit: "Net credit",   max_loss: "Width − credit",  legs: 2 },
  { key: "iron_condor",           label: "Iron Condor",         type: "CREDIT", bias: "NEUTRAL", max_profit: "Net credit",   max_loss: "Width − credit",  legs: 4 },
  { key: "bull_call_debit_spread",label: "Bull Call Debit",     type: "DEBIT",  bias: "BULLISH", max_profit: "Width − debit",max_loss: "Net debit",       legs: 2 },
];

export default function Strategy() {
  const [selected, setSelected] = useState("bull_put_spread");
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [recMeta, setRecMeta] = useState<any>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [recError, setRecError] = useState<string | null>(null);
  const strat = STRATEGIES.find(s => s.key === selected)!;

  const loadRecommendations = async () => {
    setRecLoading(true);
    setRecError(null);
    try {
      const data = await api.getOptionsRecommendations({ limit: 5 }) as any;
      setRecommendations(data.recommendations || []);
      setRecMeta(data);
    } catch (e: any) {
      setRecError(e.message || "Failed to load option recommendations.");
    } finally {
      setRecLoading(false);
    }
  };

  useEffect(() => {
    loadRecommendations();
  }, []);

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

      {/* Detail */}
      <div style={{ overflowY: "auto", padding: 20 }}>

        {/* Trading Mode Selector — controls DTE, sizing, signal threshold */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ padding: "9px 0", marginBottom: 12, borderBottom: "1px solid var(--line-dim)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span className="panel-title">Trading Mode</span>
            <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)" }}>
              AFFECTS DTE · SIZING · SIGNAL THRESHOLD · ALLOWED STRATEGIES
            </span>
          </div>
          <TradingModeSelector />
        </div>
        <div style={{ marginBottom: 20 }}>
          <div className="kicker" style={{ marginBottom: 8 }}>Strategy Details</div>
          <h2 style={{ fontFamily: "var(--mono)", fontSize: 22, fontWeight: 600, color: "var(--cyan)", marginBottom: 4 }}>
            {strat.label}
          </h2>
          <div style={{ display: "flex", gap: 10 }}>
            {[strat.type, strat.bias, `${strat.legs} LEGS`].map(tag => (
              <span key={tag} style={{
                fontFamily: "var(--mono)", fontSize: 10, padding: "2px 8px",
                border: "1px solid var(--line-dim)", color: "var(--ink-dim)",
              }}>{tag}</span>
            ))}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 1, border: "1px solid var(--line-dim)", marginBottom: 20 }}>
          {[
            { label: "Max Profit", val: strat.max_profit, color: "var(--green)" },
            { label: "Max Loss",   val: strat.max_loss,   color: "var(--red)" },
            { label: "Bias",       val: strat.bias,        color: "var(--amber)" },
          ].map(m => (
            <div key={m.label} style={{ padding: "16px 18px", background: "var(--bg-2)", borderRight: "1px solid var(--line-dim)" }}>
              <div className="kicker" style={{ marginBottom: 6 }}>{m.label}</div>
              <div className="data-val sm" style={{ color: m.color }}>{m.val}</div>
            </div>
          ))}
        </div>

        <div style={{ background: "var(--bg-2)", border: "1px solid var(--line-dim)", marginBottom: 20 }}>
          <div style={{
            padding: "10px 14px", borderBottom: "1px solid var(--line-dim)",
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <span className="panel-title">Top 5 Buying Setups</span>
            {recMeta?.dte_window && (
              <span className="kicker">
                DTE {recMeta.dte_window.min}-{recMeta.dte_window.max} · TARGET {recMeta.dte_window.target}
              </span>
            )}
            <div style={{ flex: 1 }} />
            <button className="btn-t" onClick={loadRecommendations} disabled={recLoading} style={{ fontSize: 10 }}>
              {recLoading ? "LOADING..." : "REFRESH"}
            </button>
          </div>
          {recError ? (
            <div style={{ padding: 16, fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>
              {recError}
            </div>
          ) : recLoading && recommendations.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
              BUILDING OPTION SETUPS...
            </div>
          ) : recommendations.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
              NO BUYING SETUPS AVAILABLE — CHECK MARKET DATA / WATCHLIST
            </div>
          ) : (
            <table className="t-table">
              <thead>
                <tr>
                  {["Rank","Symbol","Setup","DTE / Exp","Strikes","Debit","Risk / Reward","Contracts","Why"].map(h => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recommendations.map((r: any) => (
                  <tr key={`${r.rank}-${r.symbol}-${r.strategy}`}>
                    <td className="mono" style={{ color: "var(--cyan)" }}>#{r.rank}</td>
                    <td className="mono" style={{ color: "var(--ink)", fontWeight: 600 }}>
                      {r.symbol}
                      <div style={{ color: "var(--ink-faint)", fontSize: 10 }}>${r.underlying_price?.toFixed?.(2) ?? r.underlying_price}</div>
                    </td>
                    <td className="mono" style={{ fontSize: 10 }}>
                      <span style={{ color: r.direction === "bullish" ? "var(--green)" : "var(--red)" }}>
                        {r.direction?.toUpperCase()}
                      </span>
                      <div style={{ color: "var(--ink-dim)" }}>{r.strategy?.replace(/_/g, " ").toUpperCase()}</div>
                    </td>
                    <td className="mono">
                      {r.dte}d
                      <div style={{ color: "var(--ink-faint)", fontSize: 10 }}>{r.expiration}</div>
                    </td>
                    <td className="mono">
                      BUY {r.option_type?.toUpperCase()} {r.strikes?.buy}
                      <div style={{ color: "var(--ink-dim)", fontSize: 10 }}>
                        SELL {r.option_type?.toUpperCase()} {r.strikes?.sell} · W {r.strikes?.width}
                      </div>
                    </td>
                    <td className="mono">
                      ${r.estimated_debit?.toFixed?.(2) ?? r.estimated_debit}
                      <div style={{ color: r.chain_source === "live_chain" ? "var(--green)" : "var(--amber)", fontSize: 10 }}>
                        {r.chain_source === "live_chain" ? "LIVE MID" : "ESTIMATE"}
                      </div>
                    </td>
                    <td className="mono">
                      -${r.max_risk?.toFixed?.(0) ?? r.max_risk} / +${r.max_profit?.toFixed?.(0) ?? r.max_profit}
                      <div style={{ color: "var(--ink-faint)", fontSize: 10 }}>R:R {r.risk_reward}</div>
                    </td>
                    <td className="mono">{r.suggested_contracts}</td>
                    <td style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)", lineHeight: 1.5 }}>
                      {(r.rationale || []).slice(0, 2).join(" · ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div style={{ background: "var(--bg-2)", border: "1px solid var(--line-dim)", padding: 16 }}>
          <div className="panel-title" style={{ marginBottom: 12 }}>Current Signals</div>
          <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)", padding: 24, textAlign: "center" }}>
            NO SIGNALS — WAITING FOR 09:35 ET
          </div>
        </div>
      </div>
    </div>
  );
}
