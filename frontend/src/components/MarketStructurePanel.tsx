/**
 * Market Structure Panel — Chart Intelligence Phase 1.
 *
 * Explains swing structure and support/resistance zones without making any
 * institutional-intent claims.
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { Panel } from "./ui";

interface Structure {
  symbol?: string;
  timeframe?: string;
  state: string;
  recent_event: string;
  support: number[];
  resistance: number[];
  swing_count: number;
  note: string;
}

function stateTone(state: string) {
  if (state.includes("uptrend")) return "var(--green)";
  if (state.includes("downtrend")) return "var(--red)";
  if (state.includes("range")) return "var(--amber)";
  return "var(--ink-dim)";
}

function fmtLevel(value: number) {
  return value.toFixed(2);
}

export default function MarketStructurePanel({
  symbol,
  timeframe = "1d",
}: {
  symbol: string;
  timeframe?: string;
}) {
  const [structure, setStructure] = useState<Structure | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    setError(null);
    (api.getMarketStructure(symbol, timeframe) as Promise<Structure>)
      .then((data) => {
        if (alive) setStructure(data);
      })
      .catch((err: Error) => {
        if (alive) {
          setStructure(null);
          setError(err.message);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [symbol, timeframe]);

  return (
    <Panel
      title="Market Structure"
      action={<span className="kicker">{timeframe.toUpperCase()} closed bars</span>}
    >
      {loading && !structure ? (
        <div className="empty-state">Loading structure evidence...</div>
      ) : error ? (
        <div className="empty-state">Structure unavailable: {error}</div>
      ) : !structure ? (
        <div className="empty-state">No structure evidence available.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontSize: 20, fontWeight: 700, color: stateTone(structure.state), textTransform: "capitalize" }}>
              {structure.state.replace(/_/g, " ")}
            </span>
            <span className="tnum" style={{ marginLeft: "auto", color: "var(--ink-dim)" }}>
              {structure.swing_count} swings
            </span>
          </div>

          <div style={{ color: "var(--ink-dim)", fontSize: 12, lineHeight: 1.7 }}>
            Recent event: <span style={{ color: "var(--ink)" }}>{structure.recent_event}</span>
          </div>

          <div className="chart-intel-level-grid">
            <LevelStack label="Support" tone="var(--green)" levels={structure.support} />
            <LevelStack label="Resistance" tone="var(--red)" levels={structure.resistance} />
          </div>

          <div style={{ color: "var(--ink-faint)", fontSize: 11, lineHeight: 1.65, borderTop: "1px solid var(--line-dim)", paddingTop: 8 }}>
            {structure.note || "Chart structure only. Validation required before use in strategy decisions."}
          </div>
        </div>
      )}
    </Panel>
  );
}

function LevelStack({ label, tone, levels }: { label: string; tone: string; levels: number[] }) {
  return (
    <div className="instrument-card--flat" style={{ padding: 10 }}>
      <div className="kicker" style={{ marginBottom: 8 }}>{label}</div>
      {levels.length ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {levels.slice(0, 3).map((level) => (
            <span key={level} className="mode-badge" style={{ color: tone, borderColor: `${tone}55` }}>
              {fmtLevel(level)}
            </span>
          ))}
        </div>
      ) : (
        <div style={{ color: "var(--ink-faint)", fontSize: 12 }}>No zone detected</div>
      )}
    </div>
  );
}
