/**
 * News & Catalysts — filtered tape of headlines/filings for the watchlist.
 * Backed by GET /api/intel/classify/{symbol} (RSS news + SEC EDGAR filings,
 * each attached a deterministic impact classification). Read-only, doesn't
 * touch the order path. Fetched once per watchlist symbol and merged client-side
 * — the backend route is per-symbol, there's no multi-symbol endpoint yet.
 */
import React, { useEffect, useState } from "react";
import { UNIVERSE } from "./universe";

type NewsItem = {
  symbol: string;
  type: "news" | "filing";
  payload: { title?: string; link?: string; published?: string };
  source: string;
  as_of: string;
  classification: {
    category: string;
    impact: "high" | "moderate" | "low";
    direction: string;
    time_sensitivity: string;
    strategy_impact: string;
  };
};

const IMPACT_COLOR: Record<string, string> = {
  high: "var(--red)",
  moderate: "var(--amber)",
  low: "var(--ink-faint)",
};

export default function NewsCatalysts() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const symbols = UNIVERSE.flatMap(g => g.symbols.map(s => s.api ?? s.sym));
    Promise.all(
      symbols.map(sym =>
        fetch(`/api/intel/classify/${encodeURIComponent(sym)}?limit=5`)
          .then(r => r.json())
          .then(d => (d.items ?? []).map((it: Omit<NewsItem, "symbol">) => ({ ...it, symbol: d.symbol })))
          .catch(() => [] as NewsItem[])
      )
    ).then(lists => {
      const merged = (lists.flat() as NewsItem[]).sort((a, b) => (a.as_of < b.as_of ? 1 : -1));
      setItems(merged.slice(0, 40));
      setLoading(false);
    });
  }, []);

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">News &amp; Catalysts</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          {loading ? "loading…" : `${items.length} items · watchlist`}
        </span>
      </div>

      <p style={{ fontSize: 13, color: "var(--ink-dim)", maxWidth: 620, lineHeight: 1.6, marginBottom: 12 }}>
        Headlines and filings for the watchlist. Impact is a deterministic classification of the
        headline/filing type — not a market prediction, and never a fabricated cause.
      </p>

      <table className="t-table">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Time</th>
            <th style={{ textAlign: "left" }}>Symbol</th>
            <th style={{ textAlign: "left" }}>Headline</th>
            <th style={{ textAlign: "left" }}>Type</th>
            <th style={{ textAlign: "left" }}>Impact</th>
          </tr>
        </thead>
        <tbody>
          {!loading && items.length === 0 && (
            <tr><td colSpan={5} className="mono" style={{ color: "var(--ink-faint)" }}>No recent items</td></tr>
          )}
          {items.map((it, i) => (
            <tr key={i}>
              <td className="mono" style={{ color: "var(--ink-faint)", fontSize: 11 }}>
                {new Date(it.as_of).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
              </td>
              <td className="mono" style={{ color: "var(--cyan)" }}>{it.symbol}</td>
              <td>
                {it.payload.link ? (
                  <a href={it.payload.link} target="_blank" rel="noopener noreferrer" style={{ color: "var(--ink)" }}>
                    {it.payload.title}
                  </a>
                ) : it.payload.title}
              </td>
              <td className="mono" style={{ textTransform: "uppercase", fontSize: 10, color: "var(--ink-dim)" }}>
                {it.type}
              </td>
              <td className="mono" style={{
                color: IMPACT_COLOR[it.classification?.impact] ?? "var(--ink-dim)",
                textTransform: "uppercase", fontSize: 11,
              }}>
                {it.classification?.impact ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
