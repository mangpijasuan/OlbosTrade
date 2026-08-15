import React, { useEffect, useState } from "react";
import { useRisk } from "../hooks/useRisk";
import { api, getOperatorApiKey, setOperatorApiKey } from "../api/client";
import HoldToConfirmButton from "../components/HoldToConfirmButton";
import { Panel, Button } from "../components/ui";

interface MarginInfo {
  available: boolean;
  status?: "ok" | "warn" | "critical";
  utilization_pct?: number;
  maintenance_margin?: number;
  excess_liquidity?: number;
  buying_power?: number;
  detail?: string;
}

export default function RiskMonitor() {
  const { guardrailStatus, riskState } = useRisk();

  const [margin, setMargin] = useState<MarginInfo | null>(null);
  const [recon, setRecon] = useState<any>(null);
  const [ks, setKs] = useState<any>(null);
  const [ksBusy, setKsBusy] = useState(false);
  const [ksError, setKsError] = useState<string | null>(null);
  const [resetCode, setResetCode] = useState("");
  const [operatorKey, setOperatorKey] = useState(() => getOperatorApiKey());

  const loadKs = () =>
    api.getKillSwitchStatus().then(setKs).catch(() => {});

  useEffect(() => {
    const load = () => {
      fetch("/api/risk/margin").then(r => r.json()).then(setMargin).catch(() => {});
      fetch("/api/risk/reconciliation").then(r => r.json()).then(setRecon).catch(() => {});
      loadKs();
    };
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const engageKs = async () => {
    setKsBusy(true); setKsError(null);
    try { await api.engageKillSwitch(); await loadKs(); }
    catch (e: any) { setKsError(e?.message || "Failed to engage kill switch"); }
    finally { setKsBusy(false); }
  };

  const resetKs = async () => {
    const code = resetCode.trim();
    if (!code) {
      setKsError("Enter the kill-switch reset authorization code.");
      return;
    }
    setKsBusy(true); setKsError(null);
    try {
      await api.resetKillSwitch(code);
      setResetCode("");
      await loadKs();
    } catch (e: any) {
      setKsError(e?.message || "Failed to reset kill switch");
    } finally {
      setKsBusy(false);
    }
  };

  const ksEngaged = !!(ks?.engaged ?? ks?.is_engaged);

  const Section = ({ title, children }: any) => (
    <Panel padding={0} sectionStyle={{ marginBottom: 16 }} title={title}>{children}</Panel>
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

  // daily/weekly/monthly_loss_pct are signed P&L ratios (positive on a gain
  // day). These meters represent "how much of the loss budget is used", so a
  // gain must clamp to 0 — Math.abs() would otherwise fill the bar on a
  // profitable day as if it were eating into the loss limit.
  const daily_loss  = Math.max(0, -(guardrailStatus?.daily_loss_pct  || 0)) * 100;
  const weekly_loss = Math.max(0, -(guardrailStatus?.weekly_loss_pct || 0)) * 100;
  const monthly_loss = Math.max(0, -(guardrailStatus?.monthly_loss_pct || 0)) * 100;
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
            <Meter label="Monthly Loss" val={monthly_loss} max={10} unit="%" />
          </Section>
          <Section title="Position Limits">
            <Meter label="Trades Today" val={guardrailStatus?.trades_today||0} max={3} unit="" warn={0.5} crit={0.85} />
            <Meter label="Consecutive Losses" val={guardrailStatus?.consecutive_losses||0} max={3} unit="" warn={0.4} crit={0.7} />
            <Meter label="Open Positions" val={riskState?.state?.open_positions||0} max={5} unit="" />
          </Section>
          <Section title="Margin & Buying Power">
            {margin?.available ? (
              <>
                <Meter label="Margin Utilization" val={margin.utilization_pct ?? 0} max={100} unit="%" warn={0.5} crit={0.8} />
                <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid var(--line-dim)" }}>
                  <span className="kicker">Excess Liquidity</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12,
                    color: (margin.excess_liquidity ?? 0) <= 0 ? "var(--red)" : "var(--ink)" }}>
                    ${Math.round(margin.excess_liquidity ?? 0).toLocaleString()}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid var(--line-dim)" }}>
                  <span className="kicker">Maint. Margin</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink)" }}>
                    ${Math.round(margin.maintenance_margin ?? 0).toLocaleString()}
                  </span>
                </div>
                <div style={{ padding: "10px 16px", fontFamily: "var(--mono)", fontSize: 10,
                  color: margin.status === "critical" ? "var(--red)" : margin.status === "warn" ? "var(--amber)" : "var(--ink-faint)" }}>
                  {margin.detail}
                </div>
              </>
            ) : (
              <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
                Margin figures unavailable {margin ? "(broker not reporting)" : "…"}
              </div>
            )}
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
          <Section title="Reconciliation">
            {recon ? (
              <div style={{ padding: "12px 16px", fontFamily: "var(--mono)", fontSize: 11 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <span className="kicker">Status</span>
                  <span style={{ color: recon.clean ? "var(--green)" : "var(--amber)", fontWeight: 600 }}>
                    {recon.clean ? "✓ IN SYNC" : "⚠ NEEDS REVIEW"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", color: "var(--ink-dim)", marginBottom: 4 }}>
                  <span>Broker positions</span><span>{recon.broker_position_count ?? 0}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", color: "var(--ink-dim)", marginBottom: 4 }}>
                  <span>DB open trades</span><span>{recon.db_open_trade_count ?? 0}</span>
                </div>
                {recon.untracked_at_broker?.length > 0 && (
                  <div style={{ color: "var(--amber)", marginTop: 6 }}>
                    Untracked at broker: {recon.untracked_at_broker.join(", ")}
                  </div>
                )}
                {recon.phantom_in_db?.length > 0 && (
                  <div style={{ color: "var(--red)", marginTop: 6 }}>
                    Phantom in DB: {recon.phantom_in_db.join(", ")}
                  </div>
                )}
                {recon.warnings?.map((w: string, i: number) => (
                  <div key={i} style={{ color: "var(--red)", marginTop: 6 }}>{w}</div>
                ))}
              </div>
            ) : (
              <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
                Loading…
              </div>
            )}
          </Section>
          <Section title="Operator API Key">
            <div style={{ padding: 16, display: "flex", gap: 12, flexDirection: "column" }}>
              <p style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                When SECRET_KEY is set on the server, paste it here once per browser
                session. Stored in sessionStorage only — never shipped in the bundle.
                Leave blank for local paper when SECRET_KEY is unset.
              </p>
              <input
                type="password"
                autoComplete="off"
                value={operatorKey}
                onChange={(e) => setOperatorKey(e.target.value)}
                placeholder="SECRET_KEY (session)"
                aria-label="Operator API key for this session"
                style={{
                  fontFamily: "var(--mono)", fontSize: 12,
                  padding: "8px 10px",
                  background: "var(--bg-3)", color: "var(--ink)",
                  border: "1px solid var(--line)", borderRadius: 4,
                }}
              />
              <Button
                type="button"
                onClick={() => setOperatorApiKey(operatorKey.trim())}
                style={{ padding: "10px 0", justifyContent: "center", display: "flex" }}
              >
                SAVE SESSION KEY
              </Button>
            </div>
          </Section>
          <Section title="Kill Switch">
            <div style={{ padding: 16, display: "flex", gap: 12, flexDirection: "column" }}>
              {ksEngaged ? (
                <>
                  <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--red)", fontWeight: 700, letterSpacing: "0.08em" }}>
                    ⚡ KILL SWITCH ENGAGED — TRADING HALTED
                  </div>
                  <p style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                    All orders were cancelled and positions flattened. Reset only
                    after manual review. Enter the server reset code
                    (KILL_SWITCH_RESET_CODE) — it is never stored in this app.
                  </p>
                  <input
                    type="password"
                    autoComplete="off"
                    value={resetCode}
                    onChange={(e) => setResetCode(e.target.value)}
                    placeholder="Authorization code"
                    aria-label="Kill switch reset authorization code"
                    style={{
                      fontFamily: "var(--mono)", fontSize: 12,
                      padding: "8px 10px",
                      background: "var(--bg-3)", color: "var(--ink)",
                      border: "1px solid var(--line)", borderRadius: 4,
                    }}
                  />
                  <Button
                    disabled={ksBusy || !resetCode.trim()}
                    onClick={resetKs}
                    style={{ padding: "10px 0", justifyContent: "center", display: "flex" }}
                  >
                    {ksBusy ? "RESETTING…" : "RESET KILL SWITCH"}
                  </Button>
                </>
              ) : (
                <>
                  <p style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.7 }}>
                    Immediately cancel all open orders, flatten all positions,
                    and halt the signal cycle. Cannot be undone without manual reset.
                    <br /><b style={{ color: "var(--amber)" }}>Press and hold to engage.</b>
                  </p>
                  <HoldToConfirmButton
                    label="⚡ ENGAGE KILL SWITCH"
                    confirmingLabel="HOLD TO ENGAGE"
                    onConfirm={engageKs}
                    disabled={ksBusy}
                  />
                </>
              )}
              {ksError && (
                <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)" }}>{ksError}</div>
              )}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
