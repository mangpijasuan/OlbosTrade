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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ticker, setTicker] = useState("");
  const [tickerInput, setTickerInput] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "call" | "put">("all");

  const load = () => {
    fetch("/api/options-flow?min_volume=200&ratio=2&top=150")
      .then(r => r.json())
      .then(d => {
        if (d.error) setError(d.error);
        else { setRows(d.results || []); setError(null); }
      })
      .catch(() => setError("Failed to load options flow"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  const submitTicker = (e: React.FormEvent) => {
    e.preventDefault();
    setTicker(tickerInput.trim().toUpperCase());
  };

  const shown = rows.filter(r =>
    (ticker === "" || r.ticker === ticker) &&
    (typeFilter === "all" || r.type === typeFilter.toUpperCase()));

  // Stats reflect the current filtered view, not the whole watchlist.
  const callCount = shown.filter(r => r.type === "CALL").length;
  const putCount  = shown.filter(r => r.type === "PUT").length;
  const totalCount = callCount + putCount;
  const callPct = totalCount > 0 ? Math.round((callCount / totalCount) * 100) : null;
  const putPct  = totalCount > 0 ? 100 - (callPct ?? 0) : null;
  const callPremium = shown.filter(r => r.type === "CALL").reduce((s, r) => s + r.premium, 0);
  const putPremium  = shown.filter(r => r.type === "PUT").reduce((s, r) => s + r.premium, 0);

  // Top 3 tickers by total premium, computed separately for calls and puts
  // (a ticker can appear in both lists — e.g. NVDA heavy on calls, light on puts).
  const topByTicker = (type: "CALL" | "PUT") => {
    const totals = new Map<string, number>();
    for (const r of shown) {
      if (r.type !== type) continue;
      totals.set(r.ticker, (totals.get(r.ticker) ?? 0) + r.premium);
    }
    return [...totals.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
  };
  const topCalls = topByTicker("CALL");
  const topPuts  = topByTicker("PUT");

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      {/* Header / summary */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Unusual Options Activity</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          free snapshot · volume ≫ open interest · not a real-time OPRA tape
        </span>

        {totalCount > 0 && (
          <div style={{ display: "flex", gap: 16, fontFamily: "var(--mono)", fontSize: 11 }}>
            <span style={{ color: "var(--green)" }}>CALLS {callCount} · {callPct}% · {usd(callPremium)}</span>
            <span style={{ color: "var(--red)" }}>PUTS {putCount} · {putPct}% · {usd(putPremium)}</span>
          </div>
        )}

        <form onSubmit={submitTicker} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            value={tickerInput}
            onChange={e => setTickerInput(e.target.value)}
            placeholder="Ticker"
            style={{
              width: 80, fontFamily: "var(--mono)", fontSize: 12, textTransform: "uppercase",
              background: "var(--bg-2)", border: "1px solid var(--line-dim)", color: "var(--ink)",
              padding: "4px 8px",
            }}
          />
          <button className="btn-t" type="submit" style={{ padding: "4px 10px", fontSize: 10 }}>Go</button>
          {ticker && (
            <button type="button" className="btn-t" style={{ padding: "4px 10px", fontSize: 10 }}
              onClick={() => { setTicker(""); setTickerInput(""); }}>
              Clear
            </button>
          )}
        </form>

        <div style={{ display: "flex", gap: 6 }}>
          {(["all", "call", "put"] as const).map(f => (
            <button key={f} className={`btn-t ${f === typeFilter ? "active" : ""}`}
              style={{ padding: "2px 10px", fontSize: 10 }} onClick={() => setTypeFilter(f)}>
              {f === "all" ? "ALL" : f === "call" ? "CALLS" : "PUTS"}
            </button>
          ))}
        </div>
      </div>

      {(topCalls.length > 0 || topPuts.length > 0) && (
        <div style={{ display: "flex", gap: 28, marginBottom: 14, flexWrap: "wrap", fontFamily: "var(--mono)", fontSize: 11 }}>
          {topCalls.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: "var(--ink-faint)", fontSize: 9.5, letterSpacing: "0.08em" }}>TOP CALLS</span>
              {topCalls.map(([tk, premium], i) => (
                <button key={tk} className="btn-t" style={{ padding: "2px 8px", fontSize: 10.5, color: "var(--green)" }}
                  onClick={() => { setTicker(tk); setTickerInput(tk); }}>
                  {i + 1}. {tk} {usd(premium)}
                </button>
              ))}
            </div>
          )}
          {topPuts.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: "var(--ink-faint)", fontSize: 9.5, letterSpacing: "0.08em" }}>TOP PUTS</span>
              {topPuts.map(([tk, premium], i) => (
                <button key={tk} className="btn-t" style={{ padding: "2px 8px", fontSize: 10.5, color: "var(--red)" }}
                  onClick={() => { setTicker(tk); setTickerInput(tk); }}>
                  {i + 1}. {tk} {usd(premium)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {error ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--red)", padding: 24 }}>
          ⚠ {error}
        </div>
      ) : loading ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-faint)", padding: 24 }}>
          Scanning option chains… (first load can take a few seconds)
        </div>
      ) : shown.length === 0 ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-faint)", padding: 24 }}>
          {rows.length === 0
            ? "No unusual options activity right now (markets may be closed, or nothing above threshold)."
            : "No rows match the current ticker/type filter."}
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
            {shown.map((r, i) => (
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
