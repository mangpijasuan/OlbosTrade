/**
 * Trade Desk — unified execution hub covering paper + live trading.
 * Tabs: SIGNALS | POSITIONS | APPROVALS | P&L BREAKDOWN | MODE
 * Execution modes: MANUAL (signals only) · COPILOT (you approve) · AUTOPILOT (auto-execute)
 */
import React, { useState, useEffect, useCallback } from "react";
import { usePaperTrade } from "../hooks/usePaperTrade";
import TradingModeSelector from "../components/TradingModeSelector";
import { api } from "../api/client";

type ExecMode = "manual" | "copilot" | "autopilot";
type Tab = "signals" | "positions" | "approvals" | "pnl" | "mode";

const Badge = ({ text, color }: { text: string; color: string }) => (
  <span style={{
    fontFamily: "var(--mono)", fontSize: 10, padding: "2px 8px",
    border: `1px solid ${color}40`, background: `${color}15`,
    color, letterSpacing: "0.08em",
  }}>{text}</span>
);

// ── Execution Mode Selector ───────────────────────────────────────────────────
function ExecModeBar() {
  const [mode, setMode]     = useState<ExecMode>("manual");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (api.getExecutionMode() as any)
      .then((d: any) => setMode(d.mode || "manual"))
      .catch(() => {});
  }, []);

  const select = async (m: ExecMode) => {
    if (m === mode) return;
    setSaving(true);
    try {
      await (api.setExecutionMode(m) as any);
      setMode(m);
    } finally {
      setSaving(false);
    }
  };

  const modes: { key: ExecMode; label: string; desc: string; color: string }[] = [
    { key: "manual",    label: "MANUAL",    desc: "Signals displayed only — you decide when to trade",  color: "var(--ink-dim)" },
    { key: "copilot",   label: "COPILOT",   desc: "System queues trades — you approve each one first",   color: "var(--cyan)" },
    { key: "autopilot", label: "AUTOPILOT", desc: "Fully automatic — executes within guardrail limits",  color: "var(--orange)" },
  ];

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "6px 16px", background: "var(--bg-3)",
      borderBottom: "1px solid var(--line-dim)",
    }}>
      <span className="kicker" style={{ marginRight: 4 }}>EXECUTION:</span>
      {modes.map(m => (
        <button
          key={m.key}
          className={`btn-t ${mode === m.key ? "active" : ""}`}
          style={{
            borderRadius: 0, fontSize: 10,
            ...(mode === m.key ? { borderColor: m.color, color: m.color, background: `${m.color}15` } : {}),
          }}
          onClick={() => select(m.key)}
          disabled={saving}
          title={m.desc}
        >
          {m.label}
          {mode === m.key && <span style={{ marginLeft: 4, opacity: 0.6 }}>●</span>}
        </button>
      ))}
      {mode === "autopilot" && (
        <span style={{
          fontFamily: "var(--mono)", fontSize: 10, color: "var(--orange)",
          padding: "2px 8px", border: "1px solid rgba(249,115,22,0.4)",
          background: "rgba(249,115,22,0.08)", marginLeft: 8,
        }}>
          ⚡ AUTO-EXECUTING WITHIN GUARDRAILS
        </span>
      )}
      {mode === "copilot" && (
        <span style={{
          fontFamily: "var(--mono)", fontSize: 10, color: "var(--cyan)",
          padding: "2px 8px", border: "1px solid rgba(212,175,55,0.4)",
          background: "rgba(212,175,55,0.08)", marginLeft: 8,
        }}>
          👁 APPROVAL REQUIRED PER TRADE
        </span>
      )}
      {mode === "manual" && (
        <span style={{
          fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)",
          marginLeft: 8,
        }}>
          SIGNALS ONLY — NO AUTO EXECUTION
        </span>
      )}
      <div style={{ flex: 1 }} />
      {saving && <span className="kicker">SAVING…</span>}
    </div>
  );
}

// ── Approvals Queue (Copilot mode) ────────────────────────────────────────────
function ApprovalsQueue() {
  const [pending, setPending]   = useState<any[]>([]);
  const [log, setLog]           = useState<any[]>([]);
  const [loading, setLoading]   = useState(true);
  const [acting, setActing]     = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    Promise.all([
      (api.getPendingApprovals() as any).catch(() => ({ pending: [] })),
      (api.getExecutionLog()    as any).catch(() => ({ log: [] })),
    ]).then(([p, l]) => {
      setPending((p as any).pending || []);
      setLog((l as any).log || []);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  const act = async (id: string, action: "approve" | "reject") => {
    setActing(id);
    try {
      if (action === "approve") await (api.approveSignal(id) as any);
      else                      await (api.rejectSignal(id) as any);
      refresh();
    } finally {
      setActing(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Pending approvals */}
      <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--line-dim)", background: "var(--bg-3)" }}>
        <span className="panel-title">
          PENDING APPROVAL
          {pending.length > 0 && (
            <span style={{
              marginLeft: 8, fontFamily: "var(--mono)", fontSize: 10,
              padding: "1px 6px", background: "rgba(249,115,22,0.2)",
              color: "var(--orange)", border: "1px solid rgba(249,115,22,0.4)",
            }}>{pending.length}</span>
          )}
        </span>
      </div>

      {loading ? (
        <div style={{ padding: 40, textAlign: "center", fontFamily: "var(--mono)", color: "var(--ink-faint)", fontSize: 11 }}>LOADING…</div>
      ) : pending.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", fontFamily: "var(--mono)", color: "var(--ink-faint)", fontSize: 11 }}>
          NO PENDING APPROVALS — QUEUE IS CLEAR
          <div style={{ marginTop: 8, color: "var(--ink-faint)", fontSize: 10 }}>
            Switch to COPILOT mode to route new signals here for approval.
          </div>
        </div>
      ) : (
        <div style={{ overflowY: "auto", flex: "0 0 auto" }}>
          {pending.map((s: any) => (
            <div key={s.id} style={{
              display: "flex", alignItems: "center", gap: 16,
              padding: "12px 16px", borderBottom: "1px solid var(--line-dim)",
              background: "var(--bg-2)",
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 4 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>
                    {s.ticker}
                  </span>
                  <Badge text={s.asset_type?.toUpperCase() || "EQUITY"} color="var(--cyan)" />
                  <Badge text={s.action || s.strategy?.toUpperCase() || "BUY"} color={
                    (s.action === "BUY" || s.action === "SELL_SPREAD") ? "var(--green)" : "var(--red)"
                  } />
                  <Badge text={s.regime?.toUpperCase() || "—"} color="var(--amber)" />
                  <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                    confidence: {((s.confidence || 0) * 100).toFixed(1)}%
                  </span>
                </div>
                {s.spread && (
                  <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                    {s.spread.option_type?.toUpperCase()} spread &nbsp;
                    {s.spread.short_strike}/{s.spread.long_strike} exp {s.spread.expiration} &nbsp;
                    credit: <span style={{ color: "var(--green)" }}>${s.spread.net_credit?.toFixed(2)}</span> &nbsp;
                    max loss: <span style={{ color: "var(--red)" }}>${s.spread.max_loss?.toFixed(2)}</span>
                  </div>
                )}
                {!s.spread && (
                  <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                    Equity signal · queued at {s.queued_at ? new Date(s.queued_at).toLocaleTimeString() : "—"}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  className="btn-t"
                  disabled={acting === s.id}
                  onClick={() => act(s.id, "approve")}
                  style={{ color: "var(--green)", borderColor: "rgba(34,197,94,0.5)", fontSize: 11 }}
                >
                  ✓ APPROVE
                </button>
                <button
                  className="btn-t danger"
                  disabled={acting === s.id}
                  onClick={() => act(s.id, "reject")}
                  style={{ fontSize: 11 }}
                >
                  ✗ REJECT
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Execution log */}
      <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--line-dim)", borderTop: "1px solid var(--line-dim)", background: "var(--bg-3)" }}>
        <span className="panel-title">EXECUTION LOG</span>
      </div>
      <div style={{ flex: 1, overflowY: "auto" }}>
        {log.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", fontFamily: "var(--mono)", color: "var(--ink-faint)", fontSize: 11 }}>
            NO EXECUTION HISTORY
          </div>
        ) : (
          <table className="t-table">
            <thead><tr>
              {["Time","Ticker","Type","Action","Confidence","Executed By","Status"].map(h => <th key={h}>{h}</th>)}
            </tr></thead>
            <tbody>
              {log.map((e: any, i: number) => (
                <tr key={i}>
                  <td className="mono" style={{ fontSize: 10, color: "var(--ink-dim)" }}>
                    {e.executed_at ? new Date(e.executed_at).toLocaleTimeString() : "—"}
                  </td>
                  <td className="mono" style={{ color: "var(--cyan)" }}>{e.ticker || "—"}</td>
                  <td><Badge text={e.asset_type?.toUpperCase() || "EQ"} color="var(--cyan)" /></td>
                  <td className="mono" style={{ fontSize: 10 }}>{e.action || e.strategy || "—"}</td>
                  <td className="mono">{((e.confidence || 0) * 100).toFixed(1)}%</td>
                  <td className="mono" style={{ fontSize: 10, color: "var(--amber)" }}>{e.executed_by || "—"}</td>
                  <td>
                    <Badge
                      text={e.status?.toUpperCase() || "SENT"}
                      color={e.status === "rejected" ? "var(--red)" : "var(--green)"}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── P&L Breakdown ─────────────────────────────────────────────────────────────
function PnLBreakdown() {
  const [trades, setTrades]   = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [sort, setSort]       = useState<"date"|"pnl"|"commission">("date");

  useEffect(() => {
    setLoading(true);
    (api.getTradeHistory() as any)
      .then((h: any) => setTrades(h.trades || []))
      .finally(() => setLoading(false));
  }, []);

  const closed    = trades.filter((t: any) => t.status === "closed");
  const totalPnl  = closed.reduce((s: number, t: any) => s + (t.pnl || 0), 0);
  const totalComm = closed.reduce((s: number, t: any) => s + (t.commission_paid || 1.30), 0);
  const totalSlip = closed.reduce((s: number, t: any) => s + Math.abs((t.credit_received || 0) * 100 * 0.15), 0);
  const grossPnl  = totalPnl + totalComm + totalSlip;
  const wins      = closed.filter((t: any) => (t.pnl || 0) > 0);
  const losses    = closed.filter((t: any) => (t.pnl || 0) < 0);

  const sorted = [...trades].sort((a: any, b: any) => {
    if (sort === "pnl")        return (b.pnl || 0) - (a.pnl || 0);
    if (sort === "commission") return (b.commission_paid || 0) - (a.commission_paid || 0);
    return new Date(b.entry_date || 0).getTime() - new Date(a.entry_date || 0).getTime();
  });

  const StatBox = ({ label, value, color }: any) => (
    <div style={{ background: "var(--bg-3)", padding: "14px 18px", flex: 1, borderRight: "1px solid var(--line-dim)" }}>
      <div className="kicker" style={{ marginBottom: 6 }}>{label}</div>
      <div className="data-val sm" style={{ color: color || "var(--ink)" }}>{value}</div>
    </div>
  );

  return (
    <div style={{ padding: 16, overflowY: "auto", height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <span className="panel-title">Trade Execution Summary</span>
        <Badge text="COMMISSIONS + SLIPPAGE INCLUDED" color="var(--amber)" />
      </div>

      <div style={{ display: "flex", gap: 0, marginBottom: 16, border: "1px solid var(--line-dim)" }}>
        <StatBox label="Net P&L"         value={`${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`}  color={totalPnl >= 0 ? "var(--green)" : "var(--red)"} />
        <StatBox label="Gross P&L"       value={`$${grossPnl.toFixed(2)}`}    color="var(--ink)" />
        <StatBox label="Commission Drag" value={`-$${totalComm.toFixed(2)}`}  color="var(--amber)" />
        <StatBox label="Est. Slippage"   value={`-$${totalSlip.toFixed(2)}`}  color="var(--amber)" />
        <StatBox label="Closed Trades"   value={String(closed.length)}        color="var(--ink)" />
        <StatBox label="Win / Loss"      value={`${wins.length} / ${losses.length}`} color="var(--ink)" />
      </div>

      <div style={{
        fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)",
        padding: "8px 12px", background: "var(--bg-3)", marginBottom: 14,
        border: "1px solid var(--line-dim)", lineHeight: 1.7,
      }}>
        Commission: $0.65/contract · $1.30 per spread (IBKR standard) ·
        Slippage: VIX-adjusted est. ~15% of bid-ask spread at VIX 17, widens at higher VIX ·
        Switch broker to LIVE when ready to trade real capital.
      </div>

      <div style={{ display: "flex", gap: 1, marginBottom: 12 }}>
        {(["date","pnl","commission"] as const).map(s => (
          <button key={s} className={`btn-t ${sort === s ? "active" : ""}`}
            style={{ borderRadius: 0, fontSize: 10 }} onClick={() => setSort(s)}>
            SORT: {s === "commission" ? "COMMISSION" : s.toUpperCase()}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 40, fontFamily: "var(--mono)", color: "var(--ink-faint)", fontSize: 11 }}>LOADING...</div>
      ) : sorted.length === 0 ? (
        <div style={{ textAlign: "center", padding: 40, fontFamily: "var(--mono)", color: "var(--ink-faint)", fontSize: 11 }}>
          NO CLOSED TRADES YET — P&L BREAKDOWN APPEARS AFTER FIRST TRADE CLOSES
        </div>
      ) : (
        <table className="t-table">
          <thead><tr>
            {["Symbol","Strategy","Entry","Exit","Hold","Credit","Net P&L","Commission","Slip Est.","Exit Reason"].map(h => (
              <th key={h}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {sorted.map((t: any, i: number) => {
              const pnl  = t.pnl || 0;
              const comm = t.commission_paid || 1.30;
              const slip = Math.abs((t.credit_received || 0) * 100 * 0.15);
              return (
                <tr key={i}>
                  <td className="mono" style={{ color: "var(--cyan)" }}>{t.underlying || t.symbol || "—"}</td>
                  <td className="mono" style={{ fontSize: 10 }}>{t.strategy?.replace(/_/g," ").toUpperCase() || "—"}</td>
                  <td className="mono" style={{ color: "var(--ink-dim)", fontSize: 10 }}>{t.entry_date?.slice(0,10) || "—"}</td>
                  <td className="mono" style={{ color: "var(--ink-dim)", fontSize: 10 }}>{t.exit_date?.slice(0,10) || "—"}</td>
                  <td className="mono">{t.hold_days != null ? `${t.hold_days}d` : "—"}</td>
                  <td className="mono">${(t.credit_received || 0).toFixed(2)}</td>
                  <td className="mono" style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
                    {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                  </td>
                  <td className="mono" style={{ color: "var(--amber)" }}>-${comm.toFixed(2)}</td>
                  <td className="mono" style={{ color: "var(--amber)" }}>~-${slip.toFixed(2)}</td>
                  <td className="mono" style={{ color: "var(--ink-dim)", fontSize: 10 }}>{t.exit_reason?.replace(/_/g," ").toUpperCase() || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Main Trade Desk ────────────────────────────────────────────────────────────
export default function TradeDesk() {
  const { positions, lastSignal, cycleLog, loading, runCycle } = usePaperTrade();
  const [tab, setTab] = useState<Tab>("signals");

  const tabs: { key: Tab; label: string }[] = [
    { key: "signals",   label: "SIGNALS" },
    { key: "positions", label: "POSITIONS" },
    { key: "approvals", label: "APPROVALS" },
    { key: "pnl",       label: "P&L BREAKDOWN" },
    { key: "mode",      label: "TRADING MODE" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>

      {/* Execution mode bar — always visible */}
      <ExecModeBar />

      {/* Tab bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "6px 16px", borderBottom: "1px solid var(--line-dim)",
        background: "var(--bg-2)",
      }}>
        <div style={{ display: "flex", gap: 1 }}>
          {tabs.map(t => (
            <button key={t.key} className={`btn-t ${tab === t.key ? "active" : ""}`}
              onClick={() => setTab(t.key)} style={{ borderRadius: 0 }}>
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button className="btn-t" onClick={runCycle}
          style={{ color: "var(--cyan)", borderColor: "var(--cyan)" }}>
          {loading ? "RUNNING..." : "▶ RUN SIGNAL CYCLE"}
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto" }}>
        {/* SIGNALS */}
        {tab === "signals" && (
          <div>
            {lastSignal && (
              <div style={{
                padding: "12px 16px", borderBottom: "1px solid var(--line-dim)",
                background: "var(--bg-3)", display: "flex", gap: 24, alignItems: "center",
              }}>
                <span className="panel-title">LAST SIGNAL</span>
                <Badge text={lastSignal.strategy?.toUpperCase() || "—"} color="var(--cyan)" />
                <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
                  Score: <span style={{ color: "var(--ink)" }}>{lastSignal.signal_score?.toFixed(3) || "—"}</span>
                </span>
                <Badge text={lastSignal.approved ? "APPROVED" : "PENDING"}
                  color={lastSignal.approved ? "var(--green)" : "var(--amber)"} />
              </div>
            )}
            <table className="t-table">
              <thead><tr>
                {["Date","Symbol","Strategy","Status","Credit","P&L","Hold Days","Exit Reason"].map(h => <th key={h}>{h}</th>)}
              </tr></thead>
              <tbody>
                {(cycleLog || []).length === 0 ? (
                  <tr><td colSpan={8} style={{ textAlign: "center", padding: 40, color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11 }}>
                    NO TRADE HISTORY — RUN A CYCLE OR WAIT FOR NEXT SCAN
                  </td></tr>
                ) : (cycleLog || []).map((l: any, i: number) => {
                  const pnl = l.pnl || 0;
                  return (
                    <tr key={i}>
                      <td className="mono" style={{ color: "var(--ink-dim)", fontSize: 10 }}>{l.entry_date?.slice(0,10) || "—"}</td>
                      <td className="mono" style={{ color: "var(--cyan)" }}>{l.underlying || l.symbol || "SPY"}</td>
                      <td className="mono" style={{ fontSize: 10 }}>{l.strategy?.replace(/_/g," ").toUpperCase() || "—"}</td>
                      <td><Badge text={l.status?.toUpperCase() || "OPEN"}
                        color={l.status === "closed" ? "var(--green)" : "var(--cyan)"} /></td>
                      <td className="mono">${(l.credit_received || 0).toFixed(2)}</td>
                      <td className="mono" style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                        {pnl !== 0 ? `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}` : "—"}
                      </td>
                      <td className="mono">{l.hold_days != null ? `${l.hold_days}d` : "—"}</td>
                      <td className="mono" style={{ color: "var(--ink-dim)", fontSize: 10 }}>{l.exit_reason?.replace(/_/g," ").toUpperCase() || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* POSITIONS */}
        {tab === "positions" && (
          <table className="t-table">
            <thead><tr>
              {["Symbol","Type","Strategy","Entry Credit","Unreal P&L","Hold Days","Status","Mode"].map(h => <th key={h}>{h}</th>)}
            </tr></thead>
            <tbody>
              {(positions || []).length === 0 ? (
                <tr><td colSpan={8} style={{ textAlign: "center", padding: 40, color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11 }}>
                  NO OPEN POSITIONS
                </td></tr>
              ) : (positions || []).map((p: any, i: number) => {
                const pnl = p.unrealized_pnl || 0;
                return (
                  <tr key={i}>
                    <td className="mono" style={{ color: "var(--cyan)" }}>{p.symbol || p.underlying || "—"}</td>
                    <td><Badge text={p.asset_type?.toUpperCase() || "OPTIONS"} color="var(--cyan)" /></td>
                    <td className="mono" style={{ fontSize: 10 }}>{p.strategy?.replace(/_/g," ").toUpperCase() || "—"}</td>
                    <td className="mono">${(p.credit_received || p.entry_credit || 0).toFixed(2)}</td>
                    <td className="mono" style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                      {pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}
                    </td>
                    <td className="mono">{p.hold_days != null ? `${p.hold_days}d` : "—"}</td>
                    <td><Badge text="OPEN" color="var(--cyan)" /></td>
                    <td><span className={`mode-badge ${p.trading_mode || "balanced"}`}>{p.trading_mode || "balanced"}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {/* APPROVALS */}
        {tab === "approvals" && <ApprovalsQueue />}

        {/* P&L BREAKDOWN */}
        {tab === "pnl" && <PnLBreakdown />}

        {/* TRADING MODE */}
        {tab === "mode" && (
          <div style={{ padding: 20, maxWidth: 720 }}>
            <div className="panel-title" style={{ marginBottom: 16 }}>Market Regime & Risk Mode</div>
            <div style={{
              fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)",
              padding: "8px 12px", background: "var(--bg-3)", marginBottom: 20,
              border: "1px solid var(--line-dim)", lineHeight: 1.7,
            }}>
              Trading Mode controls position sizing, strategy selection, and risk budget.<br />
              Execution Mode (bar above) controls whether trades need your approval.<br />
              In AUTOPILOT, both must be set — the system will trade within your guardrail limits.
            </div>
            <TradingModeSelector />
          </div>
        )}
      </div>
    </div>
  );
}
