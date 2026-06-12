import React, { useState } from "react";

export default function Research() {
  const [symbol, setSymbol] = useState("SPY");
  const [loading, setLoading] = useState(false);

  const inputStyle = {
    background: "var(--bg-3)", border: "1px solid var(--line-dim)",
    color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12,
    padding: "7px 12px", outline: "none", width: 100,
  };

  const dataPoints = [
    { label: "IV RANK",      val: "42.3",   color: "var(--cyan)"  },
    { label: "IV PERCENTILE",val: "38.1%",  color: "var(--ink)"   },
    { label: "ATM IV",       val: "18.4%",  color: "var(--ink)"   },
    { label: "HV 20D",       val: "14.2%",  color: "var(--ink)"   },
    { label: "VRP",          val: "+4.2%",  color: "var(--green)" },
    { label: "PUT/CALL",     val: "0.87",   color: "var(--ink)"   },
    { label: "SKEW 25D",     val: "+0.041", color: "var(--amber)"  },
    { label: "TERM SLOPE",   val: "-0.003", color: "var(--red)"   },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Toolbar */}
      <div style={{ padding: "8px 16px", borderBottom: "1px solid var(--line-dim)", background: "var(--bg-2)", display: "flex", alignItems: "center", gap: 12 }}>
        <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())}
          style={{ ...inputStyle, textTransform: "uppercase" }} maxLength={6} />
        <button className="btn-t" onClick={() => setLoading(!loading)} style={{ color: "var(--cyan)" }}>
          LOAD ↗
        </button>
        <div className="div-v" style={{ height: 20 }} />
        <span className="kicker">IV SURFACE + REGIME + CHAIN ANALYSIS</span>
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
              <div className="data-val sm" style={{ color: d.color }}>{d.val}</div>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0 }}>
          {/* IV Surface */}
          <div style={{ border: "1px solid var(--line-dim)", borderTop: "none", background: "var(--bg-2)" }}>
            <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
              <span className="panel-title">IV Term Structure</span>
            </div>
            <div style={{ padding: 16 }}>
              {[
                { exp: "7 DTE",  iv: 20.1 },
                { exp: "14 DTE", iv: 19.4 },
                { exp: "30 DTE", iv: 18.4 },
                { exp: "60 DTE", iv: 17.8 },
                { exp: "90 DTE", iv: 17.2 },
              ].map(row => (
                <div key={row.exp} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", width: 50 }}>{row.exp}</span>
                  <div style={{ flex: 1, height: 2, background: "var(--bg-4)" }}>
                    <div style={{ height: "100%", background: "var(--cyan)", width: `${(row.iv / 25) * 100}%` }} />
                  </div>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cyan)", width: 40, textAlign: "right" }}>
                    {row.iv.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Regime */}
          <div style={{ border: "1px solid var(--line-dim)", borderTop: "none", borderLeft: "none", background: "var(--bg-2)" }}>
            <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
              <span className="panel-title">Regime Classification</span>
            </div>
            <div style={{ padding: 16 }}>
              <div style={{ marginBottom: 12 }}>
                <div className="kicker" style={{ marginBottom: 6 }}>Current Regime</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 16, color: "var(--cyan)", fontWeight: 600 }}>
                  NORMAL MEAN REVERT
                </div>
              </div>
              <div style={{ marginBottom: 12 }}>
                <div className="kicker" style={{ marginBottom: 6 }}>Confidence</div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ flex: 1, height: 3, background: "var(--bg-4)" }}>
                    <div style={{ height: "100%", background: "var(--green)", width: "74%" }} />
                  </div>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--green)" }}>74%</span>
                </div>
              </div>
              <div>
                <div className="kicker" style={{ marginBottom: 6 }}>Strategy Recommendation</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--amber)" }}>IRON CONDOR FAVORABLE</div>
              </div>
            </div>
          </div>

          {/* Skew */}
          <div style={{ border: "1px solid var(--line-dim)", borderTop: "none", borderLeft: "none", background: "var(--bg-2)" }}>
            <div style={{ padding: "9px 14px", borderBottom: "1px solid var(--line-dim)" }}>
              <span className="panel-title">Put/Call Skew</span>
            </div>
            <div style={{ padding: 16 }}>
              {[
                { label: "25D Put IV",  val: "19.2%" },
                { label: "ATM IV",      val: "18.4%" },
                { label: "25D Call IV", val: "17.8%" },
                { label: "Skew (P-C)",  val: "+1.4%" },
                { label: "Normalized",  val: "+7.6%" },
              ].map(s => (
                <div key={s.label} style={{
                  display: "flex", justifyContent: "space-between",
                  padding: "8px 0", borderBottom: "1px solid var(--line-dim)",
                }}>
                  <span className="kicker">{s.label}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink)" }}>{s.val}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
