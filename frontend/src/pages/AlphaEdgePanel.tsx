/**
 * Alpha Edge Signal — first vertical slice (docs/trade-desk-2.0/MASTER_SPEC.md
 * §5.3). Every score here is derived from real, already-shipped scoring code
 * (see backend/app/services/alpha_edge_engine.py) — no new prediction model.
 * Deliberately simple for this slice: on-demand lookup, no watchlist scan,
 * no real-time event stream, no persisted score history.
 */
import React, { useState } from "react";
import { api } from "../api/client";
import { Panel } from "../components/ui";
import { AssetToggle, type AssetTab } from "./EquitySignals";
import SignalAttribution from "../components/SignalAttribution";
import type { SignalAttributionData } from "../types/signal";

interface AlphaEdgeResponse {
  ticker: string;
  asset_type: string;
  entry_score: number | null;
  hold_score: number | null;
  exit_score: number | null;
  exit_score_basis: string;
  risk_score: number | null;
  lifecycle_state: "new" | "confirmed" | "decaying" | "expired";
  score_trend: { direction: string; delta: number | null; basis: string };
  current_action: string | null;
  current_confidence: number | null;
  position: { held: boolean; direction?: string; quantity?: number };
  supporting_evidence: { feature: string; impact: number }[];
  deterioration_evidence: { feature: string; impact: number }[];
  data_sources: Record<string, string>;
  error: string | null;
}

const LIFECYCLE_COLOR: Record<string, string> = {
  new: "var(--ink-faint)",
  confirmed: "var(--green)",
  decaying: "var(--amber)",
  expired: "var(--red)",
};

const LIFECYCLE_LABEL: Record<string, string> = {
  new: "NEW",
  confirmed: "CONFIRMED",
  decaying: "DECAYING",
  expired: "EXPIRED",
};

function scoreColor(score: number): string {
  return score >= 70 ? "var(--green)" : score >= 45 ? "var(--amber)" : "var(--red)";
}

function ScoreTile({ label, value, sublabel }: { label: string; value: number | null; sublabel?: string }) {
  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--line-dim)", borderRadius: 6,
      padding: "12px 14px", display: "flex", flexDirection: "column", gap: 4,
    }}>
      <span style={{ color: "var(--ink-dim)", fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em" }}>
        {label}
      </span>
      <span style={{
        color: value != null ? scoreColor(value) : "var(--ink-faint)",
        fontFamily: "var(--mono)", fontSize: 20, fontWeight: 700,
      }}>
        {value != null ? value.toFixed(0) : "—"}
      </span>
      {sublabel && (
        <span style={{ color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 9 }}>{sublabel}</span>
      )}
    </div>
  );
}

export default function AlphaEdgePanel() {
  const [assetTab, setAssetTab] = useState<AssetTab>("equities");
  const [symbolInput, setSymbolInput] = useState("");
  const [data, setData] = useState<AlphaEdgeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const assetType = assetTab === "equities" ? "equity" : "options";

  const lookup = () => {
    const ticker = symbolInput.trim().toUpperCase();
    if (!ticker) return;
    setLoading(true);
    setError(null);
    (api.getAlphaEdge(ticker, assetType) as Promise<AlphaEdgeResponse>)
      .then(d => { setData(d); if (d.error) setError(d.error); })
      .catch(e => setError(e?.message || "Failed to load Alpha Edge"))
      .finally(() => setLoading(false));
  };

  const attribution: SignalAttributionData | null = data ? {
    direction: data.current_action || "NEUTRAL",
    source: "Alpha Edge Signal",
    confidence: data.current_confidence,
    updatedAt: null,
    authority: "advisory",
    topPositiveFactors: data.supporting_evidence,
    topNegativeFactors: data.deterioration_evidence,
  } : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 16 }}>
      <div style={{ padding: "10px 14px", background: "var(--bg-2)", border: "1px solid var(--cyan)30", borderLeft: "2px solid var(--cyan)" }}>
        <span className="panel-title" style={{ marginRight: 12 }}>ALPHA EDGE SIGNAL</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-dim)" }}>
          Entry/Hold/Exit/Risk scores derived from existing signal-scoring code, computed live per lookup.
        </span>
      </div>

      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <AssetToggle tab={assetTab} onChange={t => { setAssetTab(t); setData(null); setError(null); }} />
        <input
          value={symbolInput}
          onChange={e => setSymbolInput(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") lookup(); }}
          placeholder="Symbol (e.g. AAPL)"
          aria-label="Alpha Edge symbol lookup"
          style={{
            fontFamily: "var(--mono)", fontSize: 12, padding: "8px 10px",
            background: "var(--bg-3)", color: "var(--ink)", border: "1px solid var(--line)", borderRadius: 4,
            width: 160,
          }}
        />
        <button
          onClick={lookup}
          disabled={loading || !symbolInput.trim()}
          className="mono"
          style={{
            padding: "8px 16px", background: "var(--cyan)", color: "var(--bg-0)",
            border: "none", borderRadius: 4, fontWeight: 700, fontSize: 11,
            cursor: loading ? "wait" : "pointer", opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? "LOOKING UP…" : "LOOK UP"}
        </button>
      </div>

      {error && (
        <div style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
          padding: "10px 14px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>
          {error}
        </div>
      )}

      {!data && !loading && !error && (
        <div style={{ padding: 20, textAlign: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
          Enter a symbol to look up its Alpha Edge scores.
        </div>
      )}

      {data && (
        <Panel padding={0} title={data.ticker}>
          <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{
                fontFamily: "var(--mono)", fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
                padding: "3px 10px", color: LIFECYCLE_COLOR[data.lifecycle_state],
                border: `1px solid ${LIFECYCLE_COLOR[data.lifecycle_state]}60`,
              }}>
                {LIFECYCLE_LABEL[data.lifecycle_state] || data.lifecycle_state.toUpperCase()}
              </span>
              {data.position.held && (
                <span className="mono" style={{ fontSize: 10, color: "var(--ink-dim)" }}>
                  Position: {data.position.direction} {data.position.quantity}
                </span>
              )}
              <span style={{ flex: 1 }} />
              <span className="mono" style={{
                fontSize: 10,
                color: data.score_trend.direction === "improving" ? "var(--green)"
                     : data.score_trend.direction === "declining" ? "var(--red)"
                     : "var(--ink-faint)",
              }}>
                Trend: {data.score_trend.direction === "not_tracked" ? "not tracked" : data.score_trend.direction}
                {data.score_trend.delta != null ? ` (${data.score_trend.delta >= 0 ? "+" : ""}${data.score_trend.delta.toFixed(1)})` : ""}
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 10 }}>
              <ScoreTile label="ENTRY SCORE" value={data.entry_score} />
              <ScoreTile label="HOLD SCORE" value={data.hold_score} sublabel={data.hold_score == null ? "no position" : undefined} />
              <ScoreTile label="EXIT SCORE" value={data.exit_score} sublabel={data.exit_score != null ? data.exit_score_basis.replace(/_/g, " ") : undefined} />
              <ScoreTile label="RISK SCORE" value={data.risk_score} />
            </div>

            <div>
              <div className="kicker" style={{ marginBottom: 6 }}>Evidence</div>
              <SignalAttribution data={attribution} />
            </div>

            <div className="mono" style={{ fontSize: 9, color: "var(--ink-faint)" }}>
              {Object.entries(data.data_sources).map(([k, v]) => `${k}: ${v}`).join(" · ")}
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}
