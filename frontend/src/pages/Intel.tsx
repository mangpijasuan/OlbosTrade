/**
 * Intel — Market News & Catalyst Intelligence Hub (Phase 1).
 *
 * Read-only research: event calendar, smart watchlists, data quality, and a
 * "why is it moving?" lookup. Nothing here creates orders or touches risk.
 */

import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import AlertsManager from "../components/AlertsManager";

type Tab = "calendar" | "watchlists" | "why" | "alerts";

interface CalEvent {
  name: string; date: string; days_away: number;
  severity: "very_high" | "high" | "moderate" | "low";
  kind: string; symbol?: string; source: string;
}
interface Watchlist {
  slug: string; name: string; description: string; is_system: boolean;
  symbols: { symbol: string; asset_class: string }[];
}
interface WhyMoving {
  symbol: string; headline: string;
  facts: string[]; inferences: string[]; risk_notes: string[]; unknown: string[];
}
interface FeedItem {
  payload: any; source: string; as_of: string; is_delayed: boolean;
}

const SEV_TONE: Record<string, string> = {
  very_high: "var(--red)", high: "var(--amber)", moderate: "var(--accent)", low: "var(--ink-dim)",
};

function SevBadge({ s }: { s: string }) {
  const tone = SEV_TONE[s] || "var(--ink-dim)";
  return (
    <span style={{ fontSize: 11, color: tone, border: `1px solid ${tone}`, borderRadius: 3, padding: "1px 7px", whiteSpace: "nowrap" }}>
      {s.replace("_", " ")}
    </span>
  );
}

function CalendarTab() {
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    (api.getCatalystCalendar(undefined, 60) as Promise<{ events: CalEvent[] }>)
      .then(d => setEvents(d.events || [])).finally(() => setLoading(false));
  }, []);
  return (
    <div style={{ border: "1px solid var(--line-dim)", borderRadius: 6, overflow: "hidden" }}>
      <table className="t-table">
        <thead><tr>
          <th>Event</th><th>Date</th><th style={{ textAlign: "right" }}>In</th><th>Type</th><th>Severity</th><th>Source</th>
        </tr></thead>
        <tbody>
          {events.map((e, i) => (
            <tr key={i}>
              <td style={{ color: "var(--ink)" }}>{e.name}</td>
              <td className="tnum" style={{ color: "var(--ink-dim)" }}>{e.date}</td>
              <td className="tnum" style={{ textAlign: "right", color: "var(--ink-dim)" }}>{e.days_away}d</td>
              <td style={{ color: "var(--ink-dim)", fontSize: 12, textTransform: "capitalize" }}>{e.kind}</td>
              <td><SevBadge s={e.severity} /></td>
              <td style={{ color: "var(--ink-faint)", fontSize: 12 }}>{e.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {loading ? <div style={{ padding: 24, textAlign: "center", color: "var(--ink-dim)", fontSize: 12 }}>Loading…</div>
        : events.length === 0 ? <div style={{ padding: 24, textAlign: "center", color: "var(--ink-dim)", fontSize: 12 }}>No events in window.</div> : null}
    </div>
  );
}

function WatchlistsTab() {
  const [lists, setLists] = useState<Watchlist[]>([]);
  useEffect(() => {
    (api.getWatchlists() as Promise<{ watchlists: Watchlist[] }>).then(d => setLists(d.watchlists || []));
  }, []);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
      {lists.map(w => (
        <div key={w.slug} style={{ border: "1px solid var(--line-dim)", borderRadius: 6, background: "var(--bg-2)", padding: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{w.name}</span>
            {w.is_system && <span style={{ fontSize: 10, color: "var(--ink-faint)", border: "1px solid var(--line-dim)", borderRadius: 2, padding: "0 4px" }}>system</span>}
          </div>
          <div style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 8 }}>{w.description}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {w.symbols.map(s => (
              <span key={s.symbol} className="mono" style={{ fontSize: 11, color: "var(--ink)", background: "var(--bg-3)", borderRadius: 3, padding: "2px 7px" }}>{s.symbol}</span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Bucket({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (!items.length) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="kicker" style={{ marginBottom: 5 }}>{title}</div>
      {items.map((t, i) => (
        <div key={i} style={{ fontSize: 13, color: tone, lineHeight: 1.6, display: "flex", gap: 7 }}>
          <span style={{ color: "var(--ink-faint)" }}>·</span>{t}
        </div>
      ))}
    </div>
  );
}

function FeedList({ title, items, render }: { title: string; items: FeedItem[]; render: (i: FeedItem) => React.ReactNode }) {
  return (
    <div style={{ border: "1px solid var(--line-dim)", borderRadius: 6, background: "var(--bg-2)", padding: 12 }}>
      <div className="kicker" style={{ marginBottom: 8 }}>{title}</div>
      {items.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>None available.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {items.map((it, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
              <span className="tnum" style={{ fontSize: 11, color: "var(--ink-faint)", minWidth: 70 }}>{it.as_of.slice(0, 10)}</span>
              <div style={{ minWidth: 0 }}>{render(it)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface Classification {
  category: string; direction: string; impact: string; risk_action: string;
}
interface ClassifiedItem extends FeedItem { type: string; classification: Classification; }
interface Insider {
  insider_filings: number; cluster: boolean; most_recent: string | null;
  context: string; limitations: string[];
}

const DIR_TONE: Record<string, string> = {
  bullish: "var(--green)", bearish: "var(--red)", mixed: "var(--amber)", uncertain: "var(--ink-dim)",
};
const IMPACT_TONE: Record<string, string> = { high: "var(--red)", moderate: "var(--amber)", low: "var(--ink-dim)" };

function ClassBadges({ c }: { c: Classification }) {
  return (
    <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 3 }}>
      <span style={{ fontSize: 10, color: "var(--ink-dim)", border: "1px solid var(--line-dim)", borderRadius: 3, padding: "0 5px" }}>{c.category}</span>
      <span style={{ fontSize: 10, color: DIR_TONE[c.direction], border: `1px solid ${DIR_TONE[c.direction]}`, borderRadius: 3, padding: "0 5px" }}>{c.direction}</span>
      <span style={{ fontSize: 10, color: IMPACT_TONE[c.impact], border: `1px solid ${IMPACT_TONE[c.impact]}`, borderRadius: 3, padding: "0 5px" }}>{c.impact} impact</span>
    </div>
  );
}

function WhyTab() {
  const [sym, setSym] = useState("NVDA");
  const [data, setData] = useState<WhyMoving | null>(null);
  const [quality, setQuality] = useState<any>(null);
  const [items, setItems] = useState<ClassifiedItem[]>([]);
  const [insider, setInsider] = useState<Insider | null>(null);
  const [loading, setLoading] = useState(false);
  const run = (s: string) => {
    setLoading(true);
    Promise.all([
      api.getWhyMoving(s) as Promise<WhyMoving>,
      api.getDataQuality(s).catch(() => null),
      (api.getClassifiedNews(s) as Promise<{ items: ClassifiedItem[] }>).catch(() => ({ items: [] })),
      (api.getInsiderIntel(s) as Promise<Insider>).catch(() => null),
    ]).then(([w, q, c, ins]) => { setData(w); setQuality(q); setItems(c.items || []); setInsider(ins); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { run("NVDA"); }, []);
  const news = items.filter(i => i.type === "news");
  const filings = items.filter(i => i.type === "filing");
  return (
    <div style={{ maxWidth: 1000 }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 14, maxWidth: 640 }}>
        <input value={sym} onChange={e => setSym(e.target.value.toUpperCase())}
          onKeyDown={e => { if (e.key === "Enter") run(sym); }}
          style={{ background: "var(--bg-3)", border: "1px solid var(--line-dim)", color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 13, padding: "7px 10px", borderRadius: 4, outline: "none", width: 120 }} />
        <button className="btn-t active" onClick={() => run(sym)} disabled={loading}>{loading ? "Loading…" : "Explain"}</button>
        {quality && (
          <span style={{ marginLeft: "auto", alignSelf: "center", fontSize: 12, color: "var(--ink-dim)" }}>
            Data quality <span className="tnum" style={{ color: quality.score >= 70 ? "var(--green)" : "var(--amber)" }}>{quality.score}/100</span>
          </span>
        )}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 14, alignItems: "start" }}>
        {data && (
          <div style={{ border: "1px solid var(--line-dim)", borderRadius: 6, background: "var(--bg-2)", padding: 14 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)", marginBottom: 12 }}>{data.headline}</div>
            <Bucket title="Observed facts" items={data.facts} tone="var(--ink)" />
            <Bucket title="Possible drivers (inference)" items={data.inferences} tone="var(--ink-dim)" />
            <Bucket title="Risk notes" items={data.risk_notes} tone="var(--amber)" />
            <Bucket title="Unknown / unavailable" items={data.unknown} tone="var(--ink-faint)" />
            <div style={{ fontSize: 11, color: "var(--ink-faint)", marginTop: 8, borderTop: "1px solid var(--line-dim)", paddingTop: 8 }}>
              Research context only — not a trade signal. Drivers are inferences, not confirmed causes.
            </div>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {insider && (
            <div style={{ border: "1px solid var(--line-dim)", borderRadius: 6, background: "var(--bg-2)", padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span className="kicker">Insider activity</span>
                {insider.cluster && <span style={{ fontSize: 10, color: "var(--amber)", border: "1px solid var(--amber)", borderRadius: 3, padding: "0 6px" }}>cluster</span>}
              </div>
              <div style={{ fontSize: 13, color: "var(--ink)" }}>
                <span className="tnum" style={{ fontWeight: 600 }}>{insider.insider_filings}</span> Form 3/4/5 filings
                {insider.most_recent && <span style={{ color: "var(--ink-faint)" }}> · latest {insider.most_recent}</span>}
              </div>
              <div style={{ fontSize: 12, color: "var(--ink-dim)", marginTop: 4 }}>{insider.context}</div>
              <div style={{ fontSize: 10, color: "var(--ink-faint)", marginTop: 6 }}>{insider.limitations[0]}</div>
            </div>
          )}
          <FeedList title="News (classified · delayed)" items={news} render={(it: any) => (
            <div>
              {it.payload.link
                ? <a href={it.payload.link} style={{ fontSize: 13, color: "var(--accent)", textDecoration: "none" }}>{it.payload.title}</a>
                : <span style={{ fontSize: 13, color: "var(--ink)" }}>{it.payload.title}</span>}
              {it.classification && <ClassBadges c={it.classification} />}
            </div>
          )} />
          <FeedList title="SEC filings" items={filings} render={(it: any) => (
            <div>
              <span className="mono" style={{ fontSize: 13, color: it.payload.is_insider ? "var(--amber)" : "var(--ink)" }}>{it.payload.form_type}</span>
              <span style={{ color: "var(--ink-dim)", marginLeft: 8, fontSize: 13 }}>{it.payload.category}</span>
              {it.classification && <ClassBadges c={it.classification} />}
            </div>
          )} />
        </div>
      </div>
    </div>
  );
}

const TABS: { key: Tab; label: string }[] = [
  { key: "calendar", label: "Event Calendar" },
  { key: "watchlists", label: "Smart Watchlists" },
  { key: "why", label: "Why Is It Moving?" },
  { key: "alerts", label: "Alerts" },
];

export default function Intel() {
  const [tab, setTab] = useState<Tab>("calendar");
  return (
    <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12, maxWidth: 1180 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "var(--ink)" }}>Intel</h2>
        <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--ink-dim)" }}>News &amp; catalyst intelligence · research context, not trade signals</p>
      </div>
      <div style={{ display: "flex", gap: 6, borderBottom: "1px solid var(--line-dim)", paddingBottom: 8 }}>
        {TABS.map(t => (
          <button key={t.key} className={`btn-t ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>
      {tab === "calendar" && <CalendarTab />}
      {tab === "watchlists" && <WatchlistsTab />}
      {tab === "why" && <WhyTab />}
      {tab === "alerts" && <AlertsManager />}
    </div>
  );
}
