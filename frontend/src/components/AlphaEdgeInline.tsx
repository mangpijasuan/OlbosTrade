/**
 * On-demand, per-signal Alpha Edge lookup — additive to Equity/Options
 * signal cards. Reuses the existing GET /api/alpha-edge/{ticker} route
 * (no new backend endpoint); nothing fetches until the operator asks.
 */
import React, { useState } from "react";
import { api } from "../api/client";

interface AlphaEdgeResponse {
  entry_score: number | null;
  hold_score: number | null;
  exit_score: number | null;
  risk_score: number | null;
  lifecycle_state: "new" | "confirmed" | "decaying" | "expired";
  opportunity_score: number | null;
}

const LIFECYCLE_COLOR: Record<string, string> = {
  new: "var(--ink-faint)",
  confirmed: "var(--green)",
  decaying: "var(--amber)",
  expired: "var(--red)",
};

function scoreColor(score: number): string {
  return score >= 70 ? "var(--green)" : score >= 45 ? "var(--amber)" : "var(--red)";
}

function Mini({ label, value }: { label: string; value: number | null }) {
  return (
    <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-dim)" }}>
      {label} <b style={{ color: value != null ? scoreColor(value) : "var(--ink-faint)" }}>
        {value != null ? value.toFixed(0) : "—"}
      </b>
    </span>
  );
}

export function OpportunityScorePill({ value }: { value: number }) {
  const color = value >= 70 ? "var(--green)" : value >= 45 ? "var(--amber)" : "var(--red)";
  return (
    <div style={{
      background: "var(--bg-3)", border: `1px solid ${color}40`, borderRadius: 3, padding: "3px 8px",
      fontFamily: "var(--mono)", fontSize: 9, display: "flex", gap: 5, alignItems: "center",
    }}>
      <span style={{ color: "var(--ink-dim)", letterSpacing: "0.08em" }}>OPPORTUNITY</span>
      <span style={{ color, fontWeight: 700 }}>{value}</span>
    </div>
  );
}

export default function AlphaEdgeInline({ ticker, assetType }: { ticker: string; assetType: "equity" | "options" }) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<AlphaEdgeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = () => {
    if (expanded) { setExpanded(false); return; }
    setExpanded(true);
    if (data || loading) return;
    setLoading(true);
    setError(null);
    (api.getAlphaEdge(ticker, assetType) as Promise<AlphaEdgeResponse>)
      .then(setData)
      .catch(e => setError(e?.message || "Failed to load"))
      .finally(() => setLoading(false));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
      <button
        onClick={toggle}
        className="mono"
        style={{
          background: "transparent", border: "1px solid var(--line-dim)", borderRadius: 3,
          padding: "2px 8px", fontSize: 9, letterSpacing: "0.08em", color: "var(--cyan)",
          cursor: "pointer",
        }}
      >
        ALPHA EDGE {expanded ? "▴" : "▾"}
      </button>
      {expanded && (
        <div style={{
          display: "flex", gap: 10, alignItems: "center", background: "var(--bg-3)",
          borderRadius: 3, padding: "4px 10px",
        }}>
          {loading && <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--ink-faint)" }}>loading…</span>}
          {error && <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--red)" }}>{error}</span>}
          {data && (
            <>
              <Mini label="ENTRY" value={data.entry_score} />
              <Mini label="RISK" value={data.risk_score} />
              <span style={{
                fontFamily: "var(--mono)", fontSize: 9, fontWeight: 700,
                color: LIFECYCLE_COLOR[data.lifecycle_state] || "var(--ink-faint)",
              }}>
                {data.lifecycle_state.toUpperCase()}
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
