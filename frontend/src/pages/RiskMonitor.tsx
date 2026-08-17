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

// Stress/VaR/exposure — same shapes ExecutiveSummary.tsx already polls; this
// page shows the meters/margin/Greeks side of risk, ExecutiveSummary only
// surfaces these behind its advanced-analytics toggle, so they're duplicated
// here rather than shared, matching this file's existing local-interface style.
interface ScenarioRow { scenario: string; portfolio_pnl: number; portfolio_pnl_pct: number | null; }
interface ScenariosResp {
  scenarios: ScenarioRow[]; worst_scenario: string | null; worst_pnl: number;
  excluded_symbols?: { ticker: string; reason: string }[];
}
interface VarResp {
  available?: boolean; reason?: string;
  var: number | null; expected_shortfall: number | null; var_pct: number | null; es_pct: number | null;
  confidence: number; spot_price?: number; spot_source?: string; spot_data_status?: string;
}
interface HeatInfo {
  portfolio_heat_pct: number; heat_status: "ok" | "elevated" | "high";
  largest_underlying: string | null; largest_underlying_pct: number;
  largest_sector: string | null; largest_sector_pct: number;
  concentration_flags: string[];
  capital: number;
  // Full per-symbol/per-sector risk-dollar breakdown, sorted descending by
  // the backend (portfolio_engine.py) — previously computed but only ever
  // the single largest of each was ever rendered; the rest silently dropped.
  exposure_by_underlying?: Record<string, number>;
  exposure_by_sector?: Record<string, number>;
}

interface CorrelationCluster {
  tickers: string[];
  avg_correlation: number;
  combined_risk_dollars: number;
  pct_of_capital: number;
}
interface CorrelationResp {
  status: "ok" | "insufficient_data" | "error";
  reason?: string;
  error?: string;
  tickers: string[];
  correlation_matrix: Record<string, Record<string, number>> | null;
  clusters: CorrelationCluster[];
  concentration_flags: string[];
  excluded_symbols: { ticker: string; reason: string }[];
  threshold: number;
}

function ExposureBreakdown({ title, exposure, capital }: {
  title: string; exposure: Record<string, number> | undefined; capital: number;
}) {
  const entries = Object.entries(exposure || {});
  if (entries.length === 0) return null;
  return (
    <div style={{ marginTop: 14 }}>
      <div className="kicker" style={{ marginBottom: 6 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {entries.map(([name, dollars]) => {
          const pct = capital > 0 ? (dollars / capital) * 100 : 0;
          return (
            <div key={name} style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--mono)", fontSize: 10.5 }}>
              <span style={{ color: "var(--ink)", minWidth: 90, flexShrink: 0 }}>{name}</span>
              <div className="bar-track" style={{ flex: 1, height: 3 }}>
                <div className="bar-fill" style={{ width: `${Math.min(pct, 100)}%`, background: "var(--cyan)" }} />
              </div>
              <span style={{ color: "var(--ink-dim)", minWidth: 40, textAlign: "right", flexShrink: 0 }}>{pct.toFixed(1)}%</span>
              <span style={{ color: "var(--ink-faint)", minWidth: 70, textAlign: "right", flexShrink: 0 }}>${dollars.toFixed(0)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
function ClusterBreakdown({ clusters }: { clusters: CorrelationCluster[] }) {
  if (clusters.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {clusters.map(c => (
        <div key={c.tickers.join("+")} style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--mono)", fontSize: 10.5 }}>
          <span style={{ color: "var(--ink)", minWidth: 130, flexShrink: 0 }}>{c.tickers.join(" + ")}</span>
          <div className="bar-track" style={{ flex: 1, height: 3 }}>
            <div className="bar-fill" style={{ width: `${Math.min(c.pct_of_capital, 100)}%`, background: "var(--cyan)" }} />
          </div>
          <span style={{ color: "var(--ink-dim)", minWidth: 40, textAlign: "right", flexShrink: 0 }}>{c.pct_of_capital.toFixed(1)}%</span>
          <span style={{ color: "var(--ink-faint)", minWidth: 70, textAlign: "right", flexShrink: 0 }}>${c.combined_risk_dollars.toFixed(0)}</span>
          <span style={{ color: "var(--ink-faint)", minWidth: 46, textAlign: "right", flexShrink: 0 }}>r={c.avg_correlation.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

function CorrelationMatrix({ matrix, threshold }: { matrix: Record<string, Record<string, number>>; threshold: number }) {
  const tickers = Object.keys(matrix);
  if (tickers.length === 0) return null;
  return (
    <div style={{ overflowX: "auto", marginTop: 12 }}>
      <table className="mono" style={{ fontSize: 10, borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", padding: "3px 6px", color: "var(--ink-faint)" }} />
            {tickers.map(t => (
              <th key={t} style={{ textAlign: "right", padding: "3px 6px", color: "var(--ink-faint)" }}>{t}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tickers.map(row => (
            <tr key={row}>
              <td style={{ padding: "3px 6px", color: "var(--ink-dim)" }}>{row}</td>
              {tickers.map(col => {
                const v = matrix[row]?.[col] ?? 0;
                const strong = row !== col && v >= threshold;
                return (
                  <td key={col} style={{
                    textAlign: "right", padding: "3px 6px",
                    color: row === col ? "var(--ink-faint)" : strong ? "var(--amber)" : "var(--ink)",
                    fontWeight: strong ? 600 : 400,
                  }}>
                    {v.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const HEAT_COLOR = { ok: "var(--green)", elevated: "var(--amber)", high: "var(--red)" } as const;

export default function RiskMonitor() {
  const { guardrailStatus, riskState, portfolioStateError } = useRisk();

  const [margin, setMargin] = useState<MarginInfo | null>(null);
  const [recon, setRecon] = useState<any>(null);
  const [scen, setScen] = useState<ScenariosResp | null>(null);
  const [varRep, setVarRep] = useState<VarResp | null>(null);
  const [heat, setHeat] = useState<HeatInfo | null>(null);
  const [corr, setCorr] = useState<CorrelationResp | null>(null);
  const [corrError, setCorrError] = useState(false);
  const [ks, setKs] = useState<any>(null);
  const [ksBusy, setKsBusy] = useState(false);
  const [ksError, setKsError] = useState<string | null>(null);
  const [resetCode, setResetCode] = useState("");
  const [operatorKey, setOperatorKey] = useState(() => getOperatorApiKey());
  const [sectionsError, setSectionsError] = useState(false);

  const loadKs = () =>
    api.getKillSwitchStatus().then(setKs).catch(() => {});

  useEffect(() => {
    const load = () => {
      // Fetch failure must not render identically to "still loading" — a
      // panel stuck on "Loading…" forever after a broker/DB outage looks
      // like a hung page, not a real signal something is wrong.
      Promise.allSettled([
        fetch("/api/risk/margin").then(r => r.json()).then(setMargin),
        fetch("/api/risk/reconciliation").then(r => r.json()).then(setRecon),
        fetch("/api/risk/scenarios").then(r => r.json()).then(setScen),
        fetch("/api/risk/var").then(r => r.json()).then(setVarRep),
        fetch("/api/portfolio/heat").then(r => r.json()).then(setHeat),
      ]).then(results => {
        setSectionsError(results.some(r => r.status === "rejected"));
      });
      loadKs();
    };
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  // Own poll loop, not folded into the shared Promise.allSettled above: this
  // fetch does a live yfinance call per ticker (slow/occasionally flaky),
  // and it would be wrong to mark the cheap DB-only sections as errored
  // whenever yfinance is merely slow. 2 minutes matches how slowly
  // correlation actually changes.
  useEffect(() => {
    const loadCorr = () => {
      fetch("/api/portfolio/correlation")
        .then(r => r.json())
        .then(d => { setCorr(d); setCorrError(false); })
        .catch(() => setCorrError(true));
    };
    loadCorr();
    const t = setInterval(loadCorr, 120000);
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

  const Section = ({ title, action, children }: any) => (
    <Panel padding={0} sectionStyle={{ marginBottom: 16 }} title={title} action={action}>{children}</Panel>
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
  // riskState comes from /api/risk/portfolio-state → response.state (IBKR account + DB P&L windows).
  // Never fall back to a fabricated value — see Dashboard.tsx's pvDisplay
  // for the same principle applied to the same underlying data.
  const pvAvailable = riskState?.state?.account_value != null || riskState?.portfolio_value != null;
  const pv          = riskState?.state?.account_value ?? riskState?.portfolio_value ?? 0;
  const pvDisplay   = pvAvailable ? `$${(pv/1000).toFixed(2)}k` : (portfolioStateError ? "UNAVAILABLE" : "—");
  const daily_pnl   = riskState?.state?.daily_pnl ?? 0;

  return (
    <div style={{ padding: 16, overflowY: "auto", height: "100%" }}>

      {/* Header stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", marginBottom: 16, background: "var(--bg-2)", border: "1px solid var(--line-dim)" }}>
        <Stat label="Portfolio Value" value={pvDisplay} color="var(--cyan)" />
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
            <Meter label="Drawdown" val={Math.max(0, (guardrailStatus?.drawdown_pct || 0)) * 100} max={15} unit="%" />
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
              <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: sectionsError && !margin ? "var(--red)" : "var(--ink-faint)" }}>
                Margin figures unavailable {margin ? "(broker not reporting)" : sectionsError ? "(fetch failed)" : "…"}
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
              <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: sectionsError ? "var(--red)" : "var(--ink-faint)" }}>
                {sectionsError ? "Failed to load reconciliation status." : "Loading…"}
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

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Section title="Stress & VaR" action={varRep && varRep.available !== false && (
          <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-dim)" }}>
            VaR {Math.round((varRep.confidence ?? 0) * 100)}%: <b style={{ color: "var(--red)" }}>${Math.round(varRep.var ?? 0).toLocaleString()}</b>
            {varRep.var_pct != null ? ` (${varRep.var_pct}%)` : ""} · ES ${Math.round(varRep.expected_shortfall ?? 0).toLocaleString()}
          </span>
        )}>
          {varRep && varRep.available === false && (
            <div style={{ padding: "10px 16px", fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--amber)", borderBottom: "1px solid var(--line-dim)" }}>
              VaR unavailable{varRep.reason ? ` — ${varRep.reason}` : ""}.
            </div>
          )}
          {scen && (scen.scenarios?.length ?? 0) > 0 ? (
            scen.scenarios.map(r => (
              <div key={r.scenario} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 16px", borderBottom: "1px solid var(--line-dim)" }}>
                <span className="mono" style={{ fontSize: 11.5, color: "var(--ink)", minWidth: 150 }}>{r.scenario}</span>
                <span className="mono" style={{ flex: 1, fontSize: 12, fontWeight: 600, color: r.portfolio_pnl < 0 ? "var(--red)" : "var(--green)" }}>
                  {r.portfolio_pnl < 0 ? "-" : "+"}${Math.abs(r.portfolio_pnl).toLocaleString()}
                  {r.portfolio_pnl_pct !== null ? `  (${r.portfolio_pnl_pct}%)` : ""}
                </span>
              </div>
            ))
          ) : (
            <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: sectionsError && !scen ? "var(--red)" : "var(--ink-faint)" }}>
              {scen ? "No open positions to stress." : sectionsError ? "Failed to load stress scenarios." : "Loading…"}
            </div>
          )}
          {scen?.excluded_symbols && scen.excluded_symbols.length > 0 && (
            <div style={{ padding: "8px 16px", display: "flex", flexDirection: "column", gap: 3 }}>
              {scen.excluded_symbols.map(x => (
                <div key={x.ticker} className="mono" style={{ fontSize: 10, color: "var(--amber)" }}>
                  {x.ticker} excluded — {x.reason}
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="Portfolio Exposure">
          {heat ? (
            <div style={{ padding: "14px 16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                <span className="kicker">Portfolio Heat</span>
                <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: HEAT_COLOR[heat.heat_status] }}>
                  {heat.portfolio_heat_pct?.toFixed(1)}%
                </span>
              </div>
              <div className="bar-track" style={{ height: 4, marginBottom: 14 }}>
                <div className="bar-fill" style={{ width: `${Math.min(heat.portfolio_heat_pct, 100)}%`, background: HEAT_COLOR[heat.heat_status] }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", marginBottom: 8 }}>
                <span>Top name: <b style={{ color: "var(--ink)" }}>{heat.largest_underlying || "—"}</b></span>
                <span>{heat.largest_underlying_pct != null ? `${heat.largest_underlying_pct.toFixed(1)}%` : "—"}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
                <span>Sector: <b style={{ color: "var(--ink)" }}>{heat.largest_sector || "—"}</b></span>
                <span>{heat.largest_sector_pct != null ? `${heat.largest_sector_pct.toFixed(1)}%` : "—"}</span>
              </div>
              <ExposureBreakdown title="By Symbol" exposure={heat.exposure_by_underlying} capital={heat.capital} />
              <ExposureBreakdown title="By Sector" exposure={heat.exposure_by_sector} capital={heat.capital} />
              {heat.concentration_flags?.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
                  {heat.concentration_flags.map(f => (
                    <span key={f} className="mono" style={{ fontSize: 10, color: "var(--amber)", border: "1px solid rgba(245,158,11,0.4)", borderRadius: 3, padding: "2px 8px" }}>{f}</span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: sectionsError ? "var(--red)" : "var(--ink-faint)" }}>
              {sectionsError ? "Failed to load portfolio exposure." : "Loading…"}
            </div>
          )}
        </Section>
      </div>

      <Section title="Correlation Clusters" action={corr && (
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-dim)" }}>
          threshold {(corr.threshold ?? 0.7).toFixed(2)} · 60d lookback
        </span>
      )}>
        {corr ? (
          corr.status === "ok" ? (
            <div style={{ padding: "14px 16px" }}>
              {corr.clusters.length > 0 ? (
                <ClusterBreakdown clusters={corr.clusters} />
              ) : (
                <div className="mono" style={{ fontSize: 11, color: "var(--ink-faint)" }}>
                  No clusters at or above the {(corr.threshold ?? 0.7).toFixed(2)} threshold — positions are not
                  meaningfully correlated.
                </div>
              )}
              {corr.concentration_flags.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
                  {corr.concentration_flags.map(f => (
                    <span key={f} className="mono" style={{ fontSize: 10, color: "var(--amber)", border: "1px solid rgba(245,158,11,0.4)", borderRadius: 3, padding: "2px 8px" }}>{f}</span>
                  ))}
                </div>
              )}
              {corr.correlation_matrix && <CorrelationMatrix matrix={corr.correlation_matrix} threshold={corr.threshold ?? 0.7} />}
              {corr.excluded_symbols.length > 0 && (
                <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 3 }}>
                  {corr.excluded_symbols.map(x => (
                    <div key={x.ticker} className="mono" style={{ fontSize: 10, color: "var(--amber)" }}>
                      {x.ticker} excluded — {x.reason}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : corr.status === "insufficient_data" ? (
            <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
              Not enough data for correlation clustering{corr.reason ? ` (${corr.reason})` : ""}.
            </div>
          ) : (
            <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>
              Failed to load correlation data{corr.error ? `: ${corr.error}` : ""}.
            </div>
          )
        ) : (
          <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: corrError ? "var(--red)" : "var(--ink-faint)" }}>
            {corrError ? "Failed to load correlation data." : "Loading…"}
          </div>
        )}
      </Section>
    </div>
  );
}
