/**
 * Sector Rotation — the 11 GICS sector ETFs ranked by trailing return
 * (1D/1W/1M/3M), with a rank-change indicator derived server-side from the
 * same bars fetch (see backend/app/services/sector_rotation_engine.py).
 * MASTER_SPEC.md lists this page under Markets with no further design
 * detail — this ranking-table shape was confirmed with the user.
 */
import React, { useEffect, useState } from "react";
import { api } from "../../api/client";
import { changeColor } from "./universe";

const TIMEFRAME_LABELS = ["1D", "1W", "1M", "3M"] as const;

interface SectorRow {
  ticker: string;
  name: string;
  returns: Record<string, number | null>;
  rank: number | null;
  prior_rank: number | null;
  rank_change: number | null;
}

interface SectorRotationResp {
  as_of?: string;
  rank_basis?: string;
  sectors?: SectorRow[];
  excluded?: { ticker: string; name: string; reason: string }[];
  data_source?: string;
  error?: string;
}

function pctCell(v: number | null): React.ReactNode {
  if (v === null) return <span style={{ color: "var(--ink-faint)" }}>—</span>;
  const pct = v * 100;
  return (
    <span style={{ color: changeColor(pct) }}>
      {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
    </span>
  );
}

function rankChangeCell(rc: number | null): React.ReactNode {
  if (rc === null) return <span style={{ color: "var(--ink-faint)" }}>—</span>;
  if (rc === 0) return <span style={{ color: "var(--ink-dim)" }}>—</span>;
  const color = rc > 0 ? "var(--green)" : "var(--red)";
  const glyph = rc > 0 ? "▲" : "▼";
  return <span style={{ color }}>{glyph} {Math.abs(rc)}</span>;
}

export default function SectorRotation() {
  const [data, setData] = useState<SectorRotationResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  const load = () => {
    (api.getSectorRotation() as Promise<SectorRotationResp>)
      .then((d) => {
        setData(d);
        setFetchError(false);
        setLoading(false);
      })
      .catch(() => {
        setFetchError(true);
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 300000); // 5 min — sector returns don't need sub-minute refresh
    return () => clearInterval(t);
  }, []);

  const sectors = data?.sectors ?? [];
  const excluded = data?.excluded ?? [];

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Sector Rotation</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          {data?.rank_basis ? `ranked by ${data.rank_basis} return` : "ranked return"} · refreshes every 5m
        </span>
        {loading && (
          <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
            loading…
          </span>
        )}
      </div>

      {fetchError || data?.error ? (
        <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>
          {data?.error ? `Failed to load sector rotation: ${data.error}` : "Failed to load sector rotation."}
        </div>
      ) : !loading && sectors.length === 0 ? (
        <div style={{ padding: "14px 16px", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
          No sector data available.
        </div>
      ) : (
        <div style={{ overflowX: "auto", border: "1px solid var(--line-dim)" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--mono)", fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--line-dim)" }}>
                <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--ink-dim)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>Rank</th>
                <th style={{ textAlign: "left", padding: "8px 12px", color: "var(--ink-dim)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>Sector</th>
                {TIMEFRAME_LABELS.map(tf => (
                  <th key={tf} style={{ textAlign: "right", padding: "8px 12px", color: "var(--ink-dim)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                    {tf}
                  </th>
                ))}
                <th style={{ textAlign: "right", padding: "8px 12px", color: "var(--ink-dim)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>Rank Δ</th>
              </tr>
            </thead>
            <tbody>
              {sectors.map(s => (
                <tr key={s.ticker} style={{ borderBottom: "1px solid var(--line-dim)" }}>
                  <td style={{ padding: "8px 12px", color: "var(--ink-faint)" }}>
                    {s.rank ?? "—"}
                  </td>
                  <td style={{ padding: "8px 12px" }}>
                    <span style={{ fontWeight: 600, color: "var(--ink)" }}>{s.ticker}</span>{" "}
                    <span style={{ fontSize: 10, color: "var(--ink-dim)" }}>{s.name}</span>
                  </td>
                  {TIMEFRAME_LABELS.map(tf => (
                    <td key={tf} style={{ padding: "8px 12px", textAlign: "right" }}>
                      {pctCell(s.returns?.[tf] ?? null)}
                    </td>
                  ))}
                  <td style={{ padding: "8px 12px", textAlign: "right" }}>
                    {rankChangeCell(s.rank_change)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {excluded.length > 0 && (
        <div style={{ padding: "8px 4px", display: "flex", flexDirection: "column", gap: 3 }}>
          {excluded.map(x => (
            <div key={x.ticker} className="mono" style={{ fontSize: 10, color: "var(--amber)" }}>
              {x.ticker} ({x.name}) excluded — {x.reason}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
