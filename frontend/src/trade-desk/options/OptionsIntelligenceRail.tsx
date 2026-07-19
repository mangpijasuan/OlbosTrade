/**
 * Options intelligence rail — backend eligibility + analyze preview + portfolio greeks.
 * 0DTE Autopilot explicitly disabled messaging.
 */

import React, { useEffect, useState } from "react";
import { api, apiAuthHeaders } from "../../api/client";
import PortfolioGreeks from "../../components/PortfolioGreeks";

export interface OptionsEligibility {
  final_status: string;
  block_reasons: string[];
  warnings: string[];
  environment?: string;
  execution_mode?: string;
}

export default function OptionsIntelligenceRail({
  symbol,
  eligibility,
}: {
  symbol: string;
  eligibility: OptionsEligibility | null;
}) {
  const [analyze, setAnalyze] = useState<any | null>(null);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [ivRank, setIvRank] = useState<string>("—");

  useEffect(() => {
    let alive = true;
    setAnalyze(null);
    setAnalyzeError(null);

    api.getIVRank(symbol)
      .then((d: any) => {
        if (!alive) return;
        setIvRank(d.iv_rank != null ? String(Math.round(d.iv_rank)) : "—");
      })
      .catch(() => { if (alive) setIvRank("Unavailable"); });

    // Preview intelligence for a generic credit put vertical near spot — evidence only.
    api.getSnapshot(symbol)
      .then(async (snap: any) => {
        if (!alive || typeof snap.last_close !== "number") return;
        const spot = snap.last_close;
        const short = Math.round(spot * 0.95);
        const long = Math.round(spot * 0.93);
        const res = await fetch("/api/options/analyze", {
          method: "POST",
          headers: apiAuthHeaders(),
          body: JSON.stringify({
            spot,
            short_strike: short,
            long_strike: long,
            option_type: "put",
            dte: 30,
            iv: 0.2,
            credit_per_share: Math.max(0.3, (short - long) * 0.25),
          }),
        });
        const body = await res.json();
        if (!alive) return;
        if (body.error) setAnalyzeError(body.error);
        else setAnalyze(body);
      })
      .catch((e) => {
        if (alive) setAnalyzeError(e?.message || "Analyze unavailable");
      });

    return () => { alive = false; };
  }, [symbol]);

  const status = eligibility?.final_status || "UNKNOWN";
  const statusColor =
    status === "BLOCKED" ? "var(--red)" :
    status.includes("ELIGIBLE") || status.includes("COPILOT") ? "var(--green)" :
    "var(--amber)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 8, overflow: "auto", height: "100%" }}>
      <div style={{ border: "1px solid rgba(245,158,11,0.4)", padding: "10px 12px", background: "var(--bg-3)" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", color: "var(--amber)" }}>
          0DTE POLICY
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink)", marginTop: 4, lineHeight: 1.5 }}>
          0DTE Autopilot is disabled. Short-dated flow is evidence only (read-only / Copilot).
        </div>
      </div>

      <div style={{ border: `1px solid ${statusColor}55`, padding: "10px 12px", background: "var(--bg-3)" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", color: "var(--ink-faint)" }}>
          ELIGIBILITY (BACKEND)
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 13, fontWeight: 700, color: statusColor, marginTop: 4 }}>
          {status.replace(/_/g, " ")}
        </div>
        {(eligibility?.block_reasons || []).map((r, i) => (
          <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--red)", marginTop: 4 }}>■ {r}</div>
        ))}
        {(eligibility?.warnings || []).map((r, i) => (
          <div key={i} style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--amber)", marginTop: 4 }}>· {r}</div>
        ))}
        {!eligibility && (
          <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)", marginTop: 6 }}>
            Run Evaluate on the composer strip for a live decision.
          </div>
        )}
      </div>

      <div style={{ border: "1px solid var(--line-dim)", padding: "10px 12px", background: "var(--bg-3)" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", color: "var(--ink-faint)" }}>
          IV RANK · {symbol}
        </div>
        <div style={{ fontFamily: "var(--mono)", fontSize: 16, color: "var(--ink)", marginTop: 4 }}>{ivRank}</div>
      </div>

      <div style={{ border: "1px solid var(--line-dim)", padding: "10px 12px", background: "var(--bg-3)" }}>
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.1em", color: "var(--ink-faint)", marginBottom: 6 }}>
          SAMPLE CREDIT PUT INTEL (ILLUSTRATIVE)
        </div>
        {analyzeError && (
          <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--amber)" }}>{analyzeError}</div>
        )}
        {analyze && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontFamily: "var(--mono)", fontSize: 10 }}>
            <span style={{ color: "var(--ink-dim)" }}>POP</span>
            <span style={{ color: "var(--ink)" }}>{analyze.pop != null ? `${(analyze.pop * 100).toFixed(0)}%` : "—"}</span>
            <span style={{ color: "var(--ink-dim)" }}>Δ short</span>
            <span style={{ color: "var(--ink)" }}>{analyze.delta_short ?? "—"}</span>
            <span style={{ color: "var(--ink-dim)" }}>θ short</span>
            <span style={{ color: "var(--ink)" }}>{analyze.theta_short ?? "—"}</span>
            <span style={{ color: "var(--ink-dim)" }}>Vega</span>
            <span style={{ color: "var(--ink)" }}>{analyze.vega_short ?? "—"}</span>
            <span style={{ color: "var(--ink-dim)" }}>Kelly</span>
            <span style={{ color: "var(--ink)" }}>
              {analyze.kelly_fraction != null ? `${(analyze.kelly_fraction * 100).toFixed(0)}%` : "—"}
            </span>
          </div>
        )}
        <div style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)", marginTop: 8 }}>
          Not a trade recommendation — preview of analyze_spread for {symbol}.
        </div>
      </div>

      <PortfolioGreeks />
    </div>
  );
}
