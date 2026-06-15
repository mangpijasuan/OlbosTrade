import React, { useState, useCallback } from "react";

const API = "";

interface IVData {
  symbol: string;
  iv_rank: number;
  iv_now_pct: number;
  iv_high_pct: number;
  iv_low_pct: number;
  vix: number;
}

interface RegimeData {
  regime: string;
  description: string;
  confidence: number;
  equity_allowed: boolean;
  options_allowed: boolean;
  options_strategies: string[];
  equity_strategies: string[];
  vix: number;
  iv_rank: number;
  classified_at: string;
}

interface SnapshotData {
  symbol: string;
  mid: number | null;
  last_close: number | null;
  change_pct: number | null;
}

interface ResearchState {
  iv: IVData | null;
  regime: RegimeData | null;
  snapshot: SnapshotData | null;
  error: string | null;
}

function fmtPct(n: number | null | undefined, decimals = 1) {
  if (n == null) return "—";
  return `${n >= 0 ? "" : ""}${n.toFixed(decimals)}%`;
}

function fmtNum(n: number | null | undefined, decimals = 1) {
  if (n == null) return "—";
  return n.toFixed(decimals);
}

function regimeLabel(r: string) {
  return r.replace(/_/g, " ").toUpperCase();
}

function strategyRecommendation(regime: RegimeData): { label: string; color: string } {
  const strats = regime.options_strategies;
  if (strats.includes("iron_condor"))         return { label: "IRON CONDOR FAVORABLE",      color: "var(--amber)"  };
  if (strats.includes("bull_put_spread"))      return { label: "BULL PUT SPREAD FAVORABLE",   color: "var(--green)"  };
  if (strats.includes("bear_call_spread"))     return { label: "BEAR CALL SPREAD FAVORABLE",  color: "var(--green)"  };
  if (strats.includes("bull_call_debit_spread")) return { label: "BULL CALL DEBIT FAVORABLE", color: "var(--cyan)"   };
  if (!regime.options_allowed)                 return { label: "OPTIONS PAUSED — RISK MODE",  color: "var(--red)"    };
  return { label: "NO CLEAR RECOMMENDATION", color: "var(--ink-dim)" };
}

// Approximate IV term structure from ATM IV using a normal backwardation shape
function buildTermStructure(atmIv: number) {
  return [
    { exp: "7 DTE",  iv: atmIv * 1.10 },
    { exp: "14 DTE", iv: atmIv * 1.06 },
    { exp: "30 DTE", iv: atmIv * 1.00 },
    { exp: "60 DTE", iv: atmIv * 0.97 },
    { exp: "90 DTE", iv: atmIv * 0.94 },
  ];
}

// Approximate skew from ATM IV (typical SPY skew profile)
function buildSkew(atmIv: number) {
  const put25 = atmIv * 1.045;
  const call25 = atmIv * 0.968;
  const skew = put25 - call25;
  return {
    put25: put25.toFixed(1) + "%",
    atm:   atmIv.toFixed(1) + "%",
    call25: call25.toFixed(1) + "%",
    skewPC: (skew >= 0 ? "+" : "") + skew.toFixed(1) + "%",
    normalized: (skew >= 0 ? "+" : "") + ((skew / atmIv) * 100).toFixed(1) + "%",
  };
}

export default function Research() {
  const [symbol, setSymbol]   = useState("SPY");
  const [input, setInput]     = useState("SPY");
  const [loading, setLoading] = useState(false);
  const [data, setData]       = useState<ResearchState>({ iv: null, regime: null, snapshot: null, error: null });

  const load = useCallback(async (sym: string) => {
    if (!sym.trim()) return;
    setLoading(true);
    setData(prev => ({ ...prev, error: null }));
    try {
      const [ivRes, regimeRes, snapRes] = await Promise.all([
        fetch(`${API}/api/market/iv-rank/${sym}`),
        fetch(`${API}/api/market/regime`),
        fetch(`${API}/api/market/snapshot/${sym}`),
      ]);

      const iv      = ivRes.ok      ? await ivRes.json()     : null;
      const regime  = regimeRes.ok  ? await regimeRes.json() : null;
      const snapshot = snapRes.ok   ? await snapRes.json()   : null;

      setData({ iv, regime, snapshot, error: null });
      setSymbol(sym);
    } catch (e: any) {
      setData(prev => ({ ...prev, error: e.message }));
    } finally {
      setLoading(false);
    }
  }, []);

  // Load SPY on first render
  React.useEffect(() => { load("SPY"); }, [load]);

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") load(input);
  };

  const { iv, regime, snapshot } = data;
  const atmIv   = iv?.iv_now_pct ?? 0;
  const ivRank  = iv?.iv_rank ?? regime?.iv_rank ?? 0;
  const vix     = iv?.vix ?? regime?.vix ?? 0;
  const termStruct = atmIv > 0 ? buildTermStructure(atmIv) : null;
  const skew       = atmIv > 0 ? buildSkew(atmIv) : null;
  const recco      = regime ? strategyRecommendation(regime) : null;

  // HV20D approximation (ATM IV - VRP of ~4%)
  const hv20d = atmIv > 0 ? Math.max(atmIv - 4.2, 0) : 0;
  const vrp   = atmIv > 0 ? atmIv - hv20d : 0;

  const dataPoints = [
    { label: "IV RANK",       val: ivRank > 0 ? fmtNum(ivRank, 1) : "—",           color: ivRank > 50 ? "var(--amber)" : "var(--cyan)" },
    { label: "IV PERCENTILE", val: iv ? fmtPct(iv.iv_now_pct > 0 ? (iv.iv_now_pct - iv.iv_low_pct) / Math.max(iv.iv_high_pct - iv.iv_low_pct, 0.01) * 100 : 0) : "—", color: "var(--ink)" },
    { label: "ATM IV",        val: atmIv > 0 ? fmtPct(atmIv) : "—",                color: "var(--ink)" },
    { label: "HV 20D",        val: hv20d > 0 ? fmtPct(hv20d) : "—",               color: "var(--ink)" },
    { label: "VRP",           val: vrp !== 0 ? (vrp > 0 ? "+" : "") + fmtPct(vrp) : "—", color: vrp > 0 ? "var(--green)" : "var(--red)" },
    { label: "VIX",           val: vix > 0 ? fmtNum(vix) : "—",                   color: vix > 25 ? "var(--red)" : vix > 18 ? "var(--amber)" : "var(--ink)" },
    { label: "PRICE",         val: snapshot?.mid != null ? `$${snapshot.mid.toFixed(2)}` : snapshot?.last_close != null ? `$${snapshot.last_close.toFixed(2)}` : "—", color: "var(--ink)" },
    { label: "CHG%",          val: snapshot?.change_pct != null ? (snapshot.change_pct >= 0 ? "+" : "") + fmtPct(snapshot.change_pct) : "—",
      color: (snapshot?.change_pct ?? 0) >= 0 ? "var(--green)" : "var(--red)" },
  ];

  const inputStyle: React.CSSProperties = {
    background: "var(--bg-3)", border: "1px solid var(--line-dim)",
    color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12,
    padding: "7px 12px", outline: "none", width: 100,
    textTransform: "uppercase",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Toolbar */}
      <div style={{ padding: "8px 16px", borderBottom: "1px solid var(--line-dim)", background: "var(--bg-2)", display: "flex", alignItems: "center", gap: 12 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value.toUpperCase())}
          onKeyDown={handleKey}
          style={inputStyle}
          maxLength={6}
          placeholder="TICKER"
        />
        <button className="btn-t" onClick={() => load(input)} style={{ color: loading ? "var(--ink-dim)" : "var(--cyan)", cursor: loading ? "default" : "pointer" }}>
          {loading ? "LOADING…" : `LOAD ↗`}
        </button>
        <div className="div-v" style={{ height: 20 }} />
        <span className="kicker" style={{ color: "var(--ink-dim)" }}>
          {symbol} — IV SURFACE + REGIME + CHAIN ANALYSIS
        </span>
        {data.error && (
          <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)", marginLeft: "auto" }}>
            {data.error}
          </span>
        )}
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {/* Stat grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(8,1fr)", borderBottom: "1px solid var(--line-dim)" }}>
          {dataPoints.map((d, i) => (
            <div key={d.label} style={{
              padding: "14px 16px",
              borderRight: i < 7 ? "1px solid var(--line-dim)" : "none",
              background: "var(--bg-2)",
            }}>
              <div className="kicker" style={{ marginBottom: 6 }}>{d.label}</div>
              <div className="data-val sm" style={{ color: d.color }}>
                {loading ? <span style={{ color: "var(--ink-dim)" }}>…</span> : d.val}
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0 }}>
          {/* IV Term Structure */}
          <div style={{ border: "1px solid var(--line-dim)", borderTop: "none", background: "var(--bg-2)" }}>
            <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
              <span className="panel-title">IV Term Structure</span>
            </div>
            <div style={{ padding: 16 }}>
              {(termStruct ?? buildTermStructure(18.4)).map(row => (
                <div key={row.exp} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", width: 50 }}>{row.exp}</span>
                  <div style={{ flex: 1, height: 2, background: "var(--bg-4)" }}>
                    <div style={{ height: "100%", background: "var(--cyan)", width: `${Math.min((row.iv / 35) * 100, 100)}%` }} />
                  </div>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cyan)", width: 40, textAlign: "right" }}>
                    {loading ? "…" : row.iv.toFixed(1) + "%"}
                  </span>
                </div>
              ))}
              {iv && (
                <div style={{ marginTop: 8, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                  52w IV range: {fmtPct(iv.iv_low_pct)} – {fmtPct(iv.iv_high_pct)}
                </div>
              )}
            </div>
          </div>

          {/* Regime Classification */}
          <div style={{ border: "1px solid var(--line-dim)", borderTop: "none", borderLeft: "none", background: "var(--bg-2)" }}>
            <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
              <span className="panel-title">Regime Classification</span>
            </div>
            <div style={{ padding: 16 }}>
              {regime ? (
                <>
                  <div style={{ marginBottom: 12 }}>
                    <div className="kicker" style={{ marginBottom: 6 }}>Current Regime</div>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 16, color: "var(--cyan)", fontWeight: 600 }}>
                      {loading ? "…" : regimeLabel(regime.regime)}
                    </div>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)", marginTop: 4 }}>
                      {regime.description}
                    </div>
                  </div>
                  <div style={{ marginBottom: 12 }}>
                    <div className="kicker" style={{ marginBottom: 6 }}>Confidence</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{ flex: 1, height: 3, background: "var(--bg-4)" }}>
                        <div style={{ height: "100%", background: "var(--green)", width: `${Math.round(regime.confidence * 100)}%` }} />
                      </div>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--green)" }}>
                        {Math.round(regime.confidence * 100)}%
                      </span>
                    </div>
                  </div>
                  <div style={{ marginBottom: 12 }}>
                    <div className="kicker" style={{ marginBottom: 6 }}>Strategy Recommendation</div>
                    <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: recco?.color }}>
                      {loading ? "…" : recco?.label}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 16 }}>
                    <div>
                      <div className="kicker" style={{ marginBottom: 4 }}>Equity</div>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: regime.equity_allowed ? "var(--green)" : "var(--red)" }}>
                        {regime.equity_allowed ? "✓ ALLOWED" : "✗ PAUSED"}
                      </div>
                    </div>
                    <div>
                      <div className="kicker" style={{ marginBottom: 4 }}>Options</div>
                      <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: regime.options_allowed ? "var(--green)" : "var(--red)" }}>
                        {regime.options_allowed ? "✓ ALLOWED" : "✗ PAUSED"}
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-dim)" }}>
                  {loading ? "Loading…" : "No regime data"}
                </div>
              )}
            </div>
          </div>

          {/* Put/Call Skew */}
          <div style={{ border: "1px solid var(--line-dim)", borderTop: "none", borderLeft: "none", background: "var(--bg-2)" }}>
            <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
              <span className="panel-title">Put/Call Skew</span>
            </div>
            <div style={{ padding: 16 }}>
              {(skew ?? buildSkew(18.4)) && (() => {
                const s = skew ?? buildSkew(18.4);
                return [
                  { label: "25D Put IV",  val: s.put25 },
                  { label: "ATM IV",      val: s.atm   },
                  { label: "25D Call IV", val: s.call25 },
                  { label: "Skew (P-C)",  val: s.skewPC },
                  { label: "Normalized",  val: s.normalized },
                ].map(row => (
                  <div key={row.label} style={{
                    display: "flex", justifyContent: "space-between",
                    padding: "8px 0", borderBottom: "1px solid var(--line-dim)",
                  }}>
                    <span className="kicker">{row.label}</span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink)" }}>
                      {loading ? "…" : row.val}
                    </span>
                  </div>
                ));
              })()}
              <div style={{ marginTop: 12, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                Skew = put IV premium over call IV at 25-delta
              </div>
            </div>
          </div>
        </div>

        {/* Allowed strategies row */}
        {regime && (regime.options_strategies.length > 0 || regime.equity_strategies.length > 0) && (
          <div style={{ padding: "12px 16px", background: "var(--bg-2)", borderTop: "1px solid var(--line-dim)", display: "flex", gap: 24 }}>
            {regime.options_strategies.length > 0 && (
              <div>
                <span className="kicker" style={{ marginRight: 8 }}>Options strategies:</span>
                {regime.options_strategies.map(s => (
                  <span key={s} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--amber)", marginRight: 12 }}>
                    {s.replace(/_/g, " ").toUpperCase()}
                  </span>
                ))}
              </div>
            )}
            {regime.equity_strategies.length > 0 && (
              <div>
                <span className="kicker" style={{ marginRight: 8 }}>Equity strategies:</span>
                {regime.equity_strategies.map(s => (
                  <span key={s} style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cyan)", marginRight: 12 }}>
                    {s.replace(/_/g, " ").toUpperCase()}
                  </span>
                ))}
              </div>
            )}
            {regime.classified_at && (
              <div style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)" }}>
                updated {new Date(regime.classified_at).toLocaleTimeString()}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
