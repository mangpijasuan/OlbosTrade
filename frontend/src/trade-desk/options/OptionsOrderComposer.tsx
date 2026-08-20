/**
 * Options composer strip — evaluate via backend; no direct execute.
 * Submit queues through existing /api/trade-desk/signal when not blocked.
 */

import React, { useState } from "react";
import { apiAuthHeaders } from "../../api/client";
import type { OptionsEligibility } from "./OptionsIntelligenceRail";

export default function OptionsOrderComposer({
  symbol,
  onEvaluated,
}: {
  symbol: string;
  onEvaluated: (e: OptionsEligibility | null) => void;
}) {
  const [strategy, setStrategy] = useState("bull_put_spread");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [evalResult, setEvalResult] = useState<OptionsEligibility | null>(null);

  const evaluate = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/trade-desk/evaluate-options", {
        method: "POST",
        headers: apiAuthHeaders(),
        body: JSON.stringify({
          ticker: symbol,
          strategy,
          dte: 30,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || `Evaluate failed (${res.status})`);
      const snap: OptionsEligibility = {
        final_status: body.final_status,
        block_reasons: body.block_reasons || [],
        warnings: body.warnings || [],
        environment: body.environment,
        execution_mode: body.execution_mode,
      };
      setEvalResult(snap);
      onEvaluated(snap);
      setMsg(`Evaluated: ${snap.final_status.replace(/_/g, " ")}`);
    } catch (e: any) {
      setMsg(e?.message || "Evaluate failed");
      setEvalResult(null);
      onEvaluated(null);
    } finally {
      setBusy(false);
    }
  };

  const blocked = evalResult?.final_status === "BLOCKED";

  return (
    <div
      className="instrument-card"
      style={{
        borderTop: "1px solid var(--line-dim)",
        padding: "10px 12px",
        display: "flex",
        flexWrap: "wrap",
        gap: 10,
        alignItems: "center",
        flexShrink: 0,
      }}
    >
      <span style={{ fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.08em", color: "var(--ink-dim)" }}>
        OPTIONS GATE · {symbol}
      </span>
      <select
        value={strategy}
        onChange={(e) => setStrategy(e.target.value)}
        style={{
          fontFamily: "var(--mono)",
          fontSize: 11,
          padding: "6px 8px",
          background: "var(--bg-3)",
          color: "var(--ink)",
          border: "1px solid var(--line)",
        }}
      >
        <option value="bull_put_spread">Bull put spread</option>
        <option value="bear_call_spread">Bear call spread</option>
        <option value="bull_call_spread">Bull call spread</option>
        <option value="bear_put_spread">Bear put spread</option>
        <option value="cash_secured_put">Cash-secured put</option>
        <option value="covered_call">Covered call</option>
      </select>
      <button type="button" className="btn-t" disabled={busy} onClick={evaluate}>
        {busy ? "…" : "EVALUATE"}
      </button>
      <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: blocked ? "var(--red)" : "var(--ink-faint)" }}>
        {msg || "Advisory only — use Spread Scanner / Copilot to queue trades. No naked shorts. No 0DTE Autopilot."}
      </span>
    </div>
  );
}
