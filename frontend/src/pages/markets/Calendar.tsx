/**
 * Calendar — forward-looking economic + earnings calendar.
 * Backed by GET /api/intel/calendar (maintained macro events + per-symbol
 * earnings dates via yfinance). Read-only, doesn't touch the order path.
 */
import React, { useEffect, useState } from "react";
import { UNIVERSE } from "./universe";

type CalEvent = {
  name: string;
  symbol?: string;
  date: string;
  days_away: number;
  severity: string;
  kind: string;
  source: string;
};

const SEVERITY_COLOR: Record<string, string> = {
  very_high: "var(--red)",
  high: "var(--amber)",
  moderate: "var(--cyan)",
  low: "var(--ink-faint)",
};

export default function Calendar() {
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const symbols = UNIVERSE.flatMap(g => g.symbols.map(s => s.api ?? s.sym)).join(",");
    fetch(`/api/intel/calendar?symbols=${encodeURIComponent(symbols)}&days_ahead=45`)
      .then(r => r.json())
      .then(d => { setEvents(d.events ?? []); setLoading(false); })
      .catch(() => { setError("Calendar feed unavailable"); setLoading(false); });
  }, []);

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Calendar</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          {loading ? "loading…" : error ? error : `${events.length} events · next 45 days`}
        </span>
      </div>

      <p style={{ fontSize: 13, color: "var(--ink-dim)", maxWidth: 620, lineHeight: 1.6, marginBottom: 12 }}>
        Forward-looking economic and earnings calendar — FOMC, CPI/PPI, jobs, and per-symbol
        earnings dates — so the desk can pre-emptively tighten risk into known volatility windows.
      </p>

      <table className="t-table">
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Date</th>
            <th style={{ textAlign: "left" }}>Event</th>
            <th style={{ textAlign: "left" }}>Symbol</th>
            <th style={{ textAlign: "left" }}>Severity</th>
            <th style={{ textAlign: "left" }}>Source</th>
          </tr>
        </thead>
        <tbody>
          {!loading && events.length === 0 && (
            <tr><td colSpan={5} className="mono" style={{ color: "var(--ink-faint)" }}>No events in window</td></tr>
          )}
          {events.map((e, i) => (
            <tr key={i}>
              <td className="mono">{e.date}</td>
              <td>{e.name}</td>
              <td className="mono" style={{ color: "var(--cyan)" }}>{e.symbol ?? "—"}</td>
              <td className="mono" style={{
                color: SEVERITY_COLOR[e.severity] ?? "var(--ink-dim)",
                textTransform: "uppercase", fontSize: 11,
              }}>
                {e.severity}
              </td>
              <td style={{ color: "var(--ink-faint)", fontSize: 11 }}>{e.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
