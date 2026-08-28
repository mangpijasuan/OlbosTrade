/**
 * QuantLab/StrategyList — manage saved strategies.
 * Lists all saved strategies with version info, allows selecting one for backtest.
 */

import React, { useEffect, useState } from "react";
import { api } from "../../api/client";

interface Strategy {
  strategy_id:     string;
  name:            string;
  description:     string | null;
  current_version: number;
  config:          Record<string, any>;
  created_at:      string;
  updated_at:      string;
}

interface Props {
  onSelectForBacktest?: (strategyId: string) => void;
}

const cell: React.CSSProperties = {
  padding: "8px 10px", fontFamily: "var(--mono)", fontSize: 11,
  borderBottom: "1px solid var(--line-dim)",
};
const hdr: React.CSSProperties = {
  ...cell, fontSize: 9, color: "var(--ink-dim)", letterSpacing: "0.08em",
  textTransform: "uppercase", background: "var(--bg-2)", borderBottom: "2px solid var(--line-dim)",
};

export default function StrategyList({ onSelectForBacktest }: Props) {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const [selected, setSelected]     = useState<Strategy | null>(null);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const res: any = await api.listQuantStrategies();
      setStrategies(res.strategies || []);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) return (
    <div style={{ padding: 24, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)" }}>
      Loading strategies…
    </div>
  );

  if (error) return (
    <div style={{ padding: 24, fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>
      Error: {error}
    </div>
  );

  return (
    <div style={{ display: "grid", gridTemplateColumns: strategies.length && selected ? "1fr 1fr" : "1fr", height: "100%", overflow: "hidden", gap: 0 }}>
      {/* Strategy list table */}
      <div style={{ overflowY: "auto", padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div className="panel-title">Saved Strategies</div>
          <button onClick={load} style={{
            background: "none", border: "1px solid var(--line-dim)", color: "var(--ink-dim)",
            fontFamily: "var(--mono)", fontSize: 10, padding: "3px 10px", cursor: "pointer",
          }}>↺ Refresh</button>
        </div>

        {strategies.length === 0 ? (
          <div style={{ color: "var(--ink-faint)", fontFamily: "var(--mono)", fontSize: 11, textAlign: "center", padding: 32 }}>
            No strategies yet. Build one in the Strategy Builder tab.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Name", "Version", "Direction", "Regime", "Saved", ""].map(h => (
                  <th key={h} style={{ ...hdr, textAlign: "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {strategies.map(s => (
                <tr
                  key={s.strategy_id}
                  onClick={() => setSelected(s)}
                  style={{
                    background: selected?.strategy_id === s.strategy_id ? "var(--bg-3)" : "var(--bg-1)",
                    cursor: "pointer",
                    borderLeft: selected?.strategy_id === s.strategy_id ? "3px solid var(--cyan)" : "3px solid transparent",
                  }}
                >
                  <td style={cell}>{s.name}</td>
                  <td style={{ ...cell, color: "var(--cyan)" }}>v{s.current_version}</td>
                  <td style={{ ...cell, color: s.config?.direction === "LONG" ? "var(--green)" : "var(--ink)" }}>
                    {s.config?.direction ?? "—"}
                  </td>
                  <td style={{ ...cell, color: "var(--ink-dim)" }}>{s.config?.regime ?? "—"}</td>
                  <td style={{ ...cell, color: "var(--ink-faint)", fontSize: 10 }}>
                    {s.updated_at ? s.updated_at.slice(0, 10) : "—"}
                  </td>
                  <td style={{ ...cell, textAlign: "right" }}>
                    {onSelectForBacktest && (
                      <button
                        onClick={e => { e.stopPropagation(); onSelectForBacktest(s.strategy_id); }}
                        style={{
                          background: "none", border: "1px solid var(--cyan)", color: "var(--cyan)",
                          fontFamily: "var(--mono)", fontSize: 9, padding: "2px 8px", cursor: "pointer",
                        }}
                      >
                        Backtest
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Detail panel */}
      {selected && (
        <div style={{
          borderLeft: "1px solid var(--line-dim)", overflowY: "auto", padding: 16,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div className="panel-title">{selected.name} <span style={{ color: "var(--cyan)", fontSize: 12 }}>v{selected.current_version}</span></div>
            <button onClick={() => setSelected(null)} style={{
              background: "none", border: "none", color: "var(--ink-dim)", cursor: "pointer", fontSize: 16,
            }}>×</button>
          </div>
          {selected.description && (
            <div style={{ color: "var(--ink-dim)", fontFamily: "var(--mono)", fontSize: 11, marginBottom: 12 }}>
              {selected.description}
            </div>
          )}
          <div className="kicker" style={{ marginBottom: 8 }}>Strategy Config</div>
          <pre style={{
            background: "var(--bg-3)", border: "1px solid var(--line-dim)",
            padding: 10, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-dim)",
            overflowX: "auto", whiteSpace: "pre-wrap", maxHeight: 500, overflowY: "auto",
          }}>
            {JSON.stringify(selected.config, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
