/**
 * Alpha Edge Signal — portfolio watchlist + scan candidates with live scores.
 * Auto-loads open positions and latest actionable scan tickers; manual lookup
 * remains for symbols outside the watchlist.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { Panel } from "../components/ui";
import { AssetToggle, type AssetTab } from "./EquitySignals";
import SignalAttribution from "../components/SignalAttribution";
import type { SignalAttributionData } from "../types/signal";
import { useAlphaEdgeWatchlist } from "../hooks/useAlphaEdgeWatchlist";
import type { AlphaEdgeCandidate } from "../utils/alphaEdgeCandidates";

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
  opportunity_score: number | null;
}

type ScoreState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: AlphaEdgeResponse }
  | { status: "error"; message: string };

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
    <div className="instrument-card" style={{
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

function MiniScore({ label, value }: { label: string; value: number | null }) {
  return (
    <span className="mono" style={{ fontSize: 9, color: "var(--ink-dim)" }}>
      {label}{" "}
      <b style={{ color: value != null ? scoreColor(value) : "var(--ink-faint)" }}>
        {value != null ? value.toFixed(0) : "—"}
      </b>
    </span>
  );
}

async function fetchScoresConcurrent(
  tickers: string[],
  assetType: "equity" | "options",
  onUpdate: (ticker: string, state: ScoreState) => void,
  cancelled: () => boolean,
  concurrency = 4,
) {
  const queue = [...tickers];
  const worker = async () => {
    while (queue.length > 0) {
      if (cancelled()) return;
      const ticker = queue.shift();
      if (!ticker) return;
      onUpdate(ticker, { status: "loading" });
      try {
        const data = await api.getAlphaEdge(ticker, assetType) as AlphaEdgeResponse;
        if (cancelled()) return;
        if (data.error) {
          onUpdate(ticker, { status: "error", message: data.error });
        } else {
          onUpdate(ticker, { status: "ready", data });
        }
      } catch (e) {
        if (cancelled()) return;
        onUpdate(ticker, {
          status: "error",
          message: e instanceof Error ? e.message : "Failed to load",
        });
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, tickers.length || 1) }, worker));
}

function SourceBadge({ source }: { source: AlphaEdgeCandidate["source"] }) {
  const color = source === "held" ? "var(--cyan)" : "var(--ink-dim)";
  return (
    <span className="mono" style={{
      fontSize: 8, fontWeight: 700, letterSpacing: "0.08em",
      padding: "2px 6px", borderRadius: 3,
      border: `1px solid ${color}50`, color,
    }}>
      {source === "held" ? "HELD" : "SCAN"}
    </span>
  );
}

function AlphaEdgeDetail({ data }: { data: AlphaEdgeResponse }) {
  const attribution: SignalAttributionData = {
    direction: data.current_action || "NEUTRAL",
    source: "Alpha Edge Signal",
    confidence: data.current_confidence,
    updatedAt: null,
    authority: "advisory",
    topPositiveFactors: data.supporting_evidence,
    topNegativeFactors: data.deterioration_evidence,
  };

  return (
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
          <ScoreTile label="OPPORTUNITY SCORE" value={data.opportunity_score} sublabel="confidence + EV + R:R + liquidity + regime" />
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
  );
}

function CandidateRow({
  candidate,
  scoreState,
  selected,
  onSelect,
}: {
  candidate: AlphaEdgeCandidate;
  scoreState: ScoreState;
  selected: boolean;
  onSelect: () => void;
}) {
  const data = scoreState.status === "ready" ? scoreState.data : null;

  return (
    <button
      type="button"
      onClick={onSelect}
      className="instrument-card"
      style={{
        width: "100%", textAlign: "left", cursor: "pointer",
        padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8,
        border: selected ? "1px solid var(--cyan)60" : undefined,
        background: selected ? "var(--bg-3)" : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)", minWidth: 52 }}>
          {candidate.ticker}
        </span>
        <SourceBadge source={candidate.source} />
        {candidate.scanAction && (
          <span className="mono" style={{ fontSize: 10, color: "var(--ink-dim)" }}>
            {candidate.scanAction}
            {candidate.scanConfidence != null ? ` · ${Math.round(candidate.scanConfidence * 100)}%` : ""}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {data && (
          <span className="mono" style={{
            fontSize: 9, fontWeight: 700,
            color: LIFECYCLE_COLOR[data.lifecycle_state] || "var(--ink-faint)",
          }}>
            {LIFECYCLE_LABEL[data.lifecycle_state] || data.lifecycle_state.toUpperCase()}
          </span>
        )}
      </div>

      {scoreState.status === "loading" && (
        <span className="mono" style={{ fontSize: 10, color: "var(--ink-faint)" }}>Loading scores…</span>
      )}
      {scoreState.status === "error" && (
        <span className="mono" style={{ fontSize: 10, color: "var(--red)" }}>{scoreState.message}</span>
      )}
      {data && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <MiniScore label="OPP" value={data.opportunity_score} />
          <MiniScore label="ENTRY" value={data.entry_score} />
          <MiniScore label="HOLD" value={data.hold_score} />
          <MiniScore label="EXIT" value={data.exit_score} />
          <MiniScore label="RISK" value={data.risk_score} />
        </div>
      )}
    </button>
  );
}

export default function AlphaEdgePanel() {
  const [assetTab, setAssetTab] = useState<AssetTab>("equities");
  const [symbolInput, setSymbolInput] = useState("");
  const [manualLookup, setManualLookup] = useState<AlphaEdgeResponse | null>(null);
  const [manualLoading, setManualLoading] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [scores, setScores] = useState<Record<string, ScoreState>>({});

  const { candidates, loading, error, refresh, lastRefresh, assetType } = useAlphaEdgeWatchlist(assetTab);
  const fetchGen = useRef(0);

  const held = useMemo(() => candidates.filter(c => c.source === "held"), [candidates]);
  const scan = useMemo(() => candidates.filter(c => c.source === "scan"), [candidates]);

  const setScore = useCallback((ticker: string, state: ScoreState) => {
    setScores(prev => ({ ...prev, [ticker]: state }));
  }, []);

  useEffect(() => {
    const tickers = candidates.map(c => c.ticker);
    if (tickers.length === 0) {
      setScores({});
      setSelectedTicker(null);
      return;
    }

    const gen = ++fetchGen.current;
    const cancelled = () => gen !== fetchGen.current;

    setScores(Object.fromEntries(tickers.map(t => [t, { status: "idle" as const }])));
    setSelectedTicker(prev => (prev && tickers.includes(prev) ? prev : tickers[0]));

    fetchScoresConcurrent(tickers, assetType, setScore, cancelled).catch(() => {});

    return () => { fetchGen.current += 1; };
  }, [candidates, assetType, setScore]);

  const lookup = () => {
    const ticker = symbolInput.trim().toUpperCase();
    if (!ticker) return;
    setManualLoading(true);
    setManualError(null);
    setManualLookup(null);
    setSelectedTicker(ticker);
    (api.getAlphaEdge(ticker, assetType) as Promise<AlphaEdgeResponse>)
      .then(d => {
        setManualLookup(d);
        if (d.error) setManualError(d.error);
        setScore(ticker, d.error
          ? { status: "error", message: d.error }
          : { status: "ready", data: d });
      })
      .catch(e => setManualError(e?.message || "Failed to load Alpha Edge"))
      .finally(() => setManualLoading(false));
  };

  const selectedData = useMemo(() => {
    if (!selectedTicker) return null;
    const st = scores[selectedTicker];
    if (st?.status === "ready") return st.data;
    if (manualLookup?.ticker === selectedTicker) return manualLookup;
    return null;
  }, [selectedTicker, scores, manualLookup]);

  const onTabChange = (t: AssetTab) => {
    setAssetTab(t);
    setManualLookup(null);
    setManualError(null);
    setSymbolInput("");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 16 }}>
      <div className="instrument-card" style={{ padding: "10px 14px", border: "1px solid var(--cyan)30", borderLeft: "2px solid var(--cyan)" }}>
        <span className="panel-title" style={{ marginRight: 12 }}>ALPHA EDGE SIGNAL</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-dim)" }}>
          Auto-loads open positions and latest scan candidates · scores computed live per symbol.
        </span>
      </div>

      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <AssetToggle tab={assetTab} onChange={onTabChange} />
        <button
          type="button"
          onClick={() => refresh()}
          disabled={loading}
          className="mono"
          style={{
            padding: "8px 12px", background: "var(--bg-3)", color: "var(--ink-dim)",
            border: "1px solid var(--line)", borderRadius: 4, fontSize: 10,
            cursor: loading ? "wait" : "pointer",
          }}
        >
          {loading ? "REFRESHING…" : "REFRESH"}
        </button>
        {lastRefresh && (
          <span className="mono" style={{ fontSize: 9, color: "var(--ink-faint)" }}>
            Updated {lastRefresh.toLocaleTimeString()}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <input
          value={symbolInput}
          onChange={e => setSymbolInput(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") lookup(); }}
          placeholder="Other symbol…"
          aria-label="Alpha Edge symbol lookup"
          style={{
            fontFamily: "var(--mono)", fontSize: 12, padding: "8px 10px",
            background: "var(--bg-3)", color: "var(--ink)", border: "1px solid var(--line)", borderRadius: 4,
            width: 140,
          }}
        />
        <button
          onClick={lookup}
          disabled={manualLoading || !symbolInput.trim()}
          className="mono"
          style={{
            padding: "8px 16px", background: "var(--cyan)", color: "var(--bg-0)",
            border: "none", borderRadius: 4, fontWeight: 700, fontSize: 11,
            cursor: manualLoading ? "wait" : "pointer", opacity: manualLoading ? 0.6 : 1,
          }}
        >
          {manualLoading ? "…" : "LOOK UP"}
        </button>
      </div>

      {(error || manualError) && (
        <div style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
          padding: "10px 14px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>
          {error || manualError}
        </div>
      )}

      {!loading && candidates.length === 0 && !manualLookup && (
        <div style={{ padding: 20, textAlign: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
          No open {assetType} positions or recent scan candidates — run a scan on Live Signals or look up a symbol.
        </div>
      )}

      {(held.length > 0 || scan.length > 0) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {held.length > 0 && (
            <section>
              <div className="kicker" style={{ marginBottom: 8 }}>
                OPEN POSITIONS ({held.length})
              </div>
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                gap: 8,
              }}>
                {held.map(c => (
                  <CandidateRow
                    key={c.ticker}
                    candidate={c}
                    scoreState={scores[c.ticker] || { status: "idle" }}
                    selected={selectedTicker === c.ticker}
                    onSelect={() => setSelectedTicker(c.ticker)}
                  />
                ))}
              </div>
            </section>
          )}

          {scan.length > 0 && (
            <section>
              <div className="kicker" style={{ marginBottom: 8 }}>
                SCAN CANDIDATES ({scan.length})
              </div>
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                gap: 8,
              }}>
                {scan.map(c => (
                  <CandidateRow
                    key={c.ticker}
                    candidate={c}
                    scoreState={scores[c.ticker] || { status: "idle" }}
                    selected={selectedTicker === c.ticker}
                    onSelect={() => setSelectedTicker(c.ticker)}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      {selectedData && <AlphaEdgeDetail data={selectedData} />}
    </div>
  );
}
