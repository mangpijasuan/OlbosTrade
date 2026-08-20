/**
 * Equity intelligence rail — market panels + eligibility from backend evaluate + setup scanner.
 */

import React, { useEffect, useState } from "react";
import MarketBiasPanel from "../../components/MarketBiasPanel";
import TimeframeAlignmentPanel from "../../components/TimeframeAlignmentPanel";
import MarketStructurePanel from "../../components/MarketStructurePanel";
import { api } from "../../api/client";

export interface EligibilitySnapshot {
  final_status: string;
  block_reasons: string[];
  warnings: string[];
  environment?: string;
  execution_mode?: string;
  evaluated_at?: string;
}

export default function EquityIntelligenceRail({
  symbol,
  eligibility,
}: {
  symbol: string;
  eligibility: EligibilitySnapshot | null;
}) {
  const [heat, setHeat] = useState<string>("—");
  const [setup, setSetup] = useState<any | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/portfolio/heat")
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (typeof d.portfolio_heat_pct === "number") setHeat(`${d.portfolio_heat_pct.toFixed(1)}%`);
        else if (typeof d.heat_pct === "number") setHeat(`${(d.heat_pct * 100).toFixed(1)}%`);
        else setHeat(d.error ? "Unavailable" : "—");
      })
      .catch(() => { if (alive) setHeat("Unavailable"); });

    (api.getSetupScanner() as Promise<{ results: any[] }>)
      .then((d) => {
        if (!alive) return;
        const row = (d.results || []).find((r) => r.symbol === symbol) || null;
        setSetup(row);
      })
      .catch(() => { if (alive) setSetup(null); });

    return () => { alive = false; };
  }, [symbol]);

  const status = eligibility?.final_status || "UNKNOWN";
  const statusColor =
    status === "BLOCKED" ? "var(--red)" :
    status === "MANUAL_ELIGIBLE" || status === "COPILOT_REVIEW_REQUIRED" ? "var(--green)" :
    status === "INFORMATIONAL" ? "var(--cyan)" :
    "var(--amber)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 8, overflow: "auto", height: "100%" }}>
      <div
        className="instrument-card"
        style={{ border: `1px solid ${statusColor}55`, padding: "10px 12px" }}
      >
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 9,
            letterSpacing: "0.1em",
            color: "var(--ink-faint)",
            marginBottom: 6,
          }}
        >
          ELIGIBILITY (BACKEND)
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 13, fontWeight: 700, color: statusColor }}>
          {status.replace(/_/g, " ")}
        </div>
        {eligibility?.environment && (
          <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)", marginTop: 4 }}>
            Env {eligibility.environment} · Mode {eligibility.execution_mode || "—"}
          </div>
        )}
        {(eligibility?.block_reasons || []).map((r, i) => (
          <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)", marginTop: 4 }}>
            ■ {r}
          </div>
        ))}
        {(eligibility?.warnings || []).map((r, i) => (
          <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--amber)", marginTop: 4 }}>
            · {r}
          </div>
        ))}
        {!eligibility && (
          <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", marginTop: 6 }}>
            Run Evaluate in the order composer for a current decision.
          </div>
        )}
      </div>

      <div className="instrument-card" style={{ padding: "10px 12px" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", color: "var(--ink-faint)" }}>
          PORTFOLIO HEAT
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 14, color: "var(--ink)", marginTop: 4 }}>{heat}</div>
      </div>

      {setup && (
        <div className="instrument-card" style={{ padding: "10px 12px" }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", color: "var(--ink-faint)" }}>
            SETUP READINESS · {symbol}
          </div>
          <div
            style={{
              fontFamily: "var(--mono)",
              fontSize: 12,
              marginTop: 4,
              color:
                setup.status === "eligible" ? "var(--green)" :
                setup.status === "blocked" ? "var(--red)" : "var(--amber)",
              textTransform: "uppercase",
            }}
          >
            {setup.status}
          </div>
          {(setup.blocked_reasons || []).map((b: string, i: number) => (
            <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)", marginTop: 4 }}>
              ■ {b}
            </div>
          ))}
        </div>
      )}

      <MarketBiasPanel symbol={symbol} />
      <TimeframeAlignmentPanel symbol={symbol} />
      <MarketStructurePanel symbol={symbol} timeframe="1d" />
    </div>
  );
}
