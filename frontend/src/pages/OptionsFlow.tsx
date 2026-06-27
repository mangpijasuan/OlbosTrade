/**
 * OptionsFlow — "Unusual Options Activity" tape (free yfinance approximation).
 *
 * A real-time OPRA flow feed needs a paid subscription; this shows a periodic
 * snapshot of contracts trading at unusually high volume vs. open interest across
 * the watchlist. Polls /api/options-flow (server caches ~5 min).
 */
import React, { useEffect, useState } from "react";

interface FlowRow {
  ticker: string; type: "CALL" | "PUT"; strike: number; expiry: string;
  dte: number | null; spot: number | null; volume: number;
  open_interest: number; vol_oi_ratio: number | null; last_price: number;
  iv: number | null; premium: number; sentiment: string;
}

const usd = (n: number) =>
  "$" + Math.round(n).toLocaleString("en-US");

export default function OptionsFlow() {
  const [rows, setRows] = useState<FlowRow[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    fetch("/api/options-flow?min_volume=200&ratio=2&top=150")
      .then(r => r.json())
      .then(d => {
        if (d.error) setError(d.error);
        else { setRows(d.results || []); setError(null); }
      })
      .catch(() => setError("Failed to load options flow"))
      .finally(() => setLoading(false));
    fetch("/api/options-flow/summary").then(r => r.json()).then(setSummary).catch(() => {});
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      {/* Header / summary */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Unusual Options Activity</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          free snapshot · volume ≫ open interest · not a real-time OPRA tape
        </span>
        {summary?.count != null && (
          <div style={{ display: "flex", gap: 16, marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11 }}>
            <span style={{ color: "var(--green)" }}>CALLS {usd(summary.call_premium || 0)}</span>
            <span style={{ color: "var(--red)" }}>PUTS {usd(summary.put_premium || 0)}</span>
            <span style={{ color: (summary.bullish_ratio ?? 0.5) >= 0.5 ? "var(--green)" : "var(--red)" }}>
              BULLISH {(((summary.bullish_ratio ?? 0.5) * 100)).toFixed(0)}%
            </span>
          </div>
        )}
      </div>

      {error ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--red)", padding: 24 }}>
          ⚠ {error}
        </div>
      ) : loading ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-faint)", padding: 24 }}>
          Scanning option chains… (first load can take a few seconds)
        </div>
      ) : rows.length === 0 ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-faint)", padding: 24 }}>
          No unusual options activity right now (markets may be closed, or nothing above threshold).
        </div>
      ) : (
        <table className="t-table">
          <thead>
            <tr>
              {["Ticker","P/C","Strike","Exp","DTE","Spot","Volume","OI","Vol/OI","Last","IV","Premium"].map(h => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="mono" style={{ color: "var(--cyan)" }}>{r.ticker}</td>
                <td className="mono" style={{ color: r.type === "CALL" ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
                  {r.type}
                </td>
                <td className="mono">{r.strike}</td>
                <td className="mono">{r.expiry}</td>
                <td className="mono" style={{ color: "var(--ink-dim)" }}>{r.dte != null ? `${r.dte}d` : "—"}</td>
                <td className="mono">{r.spot != null ? r.spot.toFixed(2) : "—"}</td>
                <td className="mono">{r.volume.toLocaleString("en-US")}</td>
                <td className="mono" style={{ color: "var(--ink-dim)" }}>{r.open_interest.toLocaleString("en-US")}</td>
                <td className="mono" style={{ color: "var(--amber)" }}>{r.vol_oi_ratio != null ? `${r.vol_oi_ratio}×` : "NEW"}</td>
                <td className="mono">${r.last_price.toFixed(2)}</td>
                <td className="mono" style={{ color: "var(--ink-dim)" }}>{r.iv != null ? `${(r.iv * 100).toFixed(0)}%` : "—"}</td>
                <td className="mono" style={{ color: r.type === "CALL" ? "var(--green)" : "var(--red)" }}>{usd(r.premium)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
