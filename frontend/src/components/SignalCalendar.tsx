/**
 * Daily signal calendar — what the desk ranked at 10:00 ET, and what happened.
 *
 * Reads the frozen snapshot (daily_signal_snapshots) with resolution joined on
 * from signal_outcomes. The value is entirely in the freeze: these are the
 * picks as they stood at a fixed decision time, not the best-scoring version
 * of each signal found in hindsight.
 *
 * Which is why the scorecard here reports `pending` next to `resolved` rather
 * than folding it away. An unresolved signal is not a miss, and counting it as
 * one would understate the record as surely as dropping it would flatter it.
 */

import React, { useEffect, useState } from "react";

import { api } from "../api/client";
import { Panel } from "./ui";

interface Pick {
  rank: number;
  ticker: string;
  opportunity_score: number | null;
  confidence: number | null;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  outcome: string | null;
  days_to_resolve: number | null;
}

interface Day { date: string; BUY: Pick[]; SELL: Pick[] }

interface CalendarResp {
  status: string;
  days: Day[];
  note?: string;
  summary?: {
    trading_days: number; picks: number; resolved: number;
    pending: number; target_hit: number; hit_rate_pct: number | null;
  };
}

const OUTCOME_TONE: Record<string, string> = {
  target_hit: "var(--green)",
  stop_hit: "var(--red)",
  expired: "var(--ink-dim)",
  pending: "var(--amber)",
};

function outcomeLabel(o: string | null): string {
  if (!o) return "—";
  return o.replace(/_/g, " ").toUpperCase();
}

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="mono" style={{ fontSize: 9, color: "var(--ink-faint)", letterSpacing: "0.08em" }}>
        {label}
      </div>
      <div className="mono" style={{ fontSize: 16, fontWeight: 700, color: tone ?? "var(--ink)" }}>
        {value}
      </div>
    </div>
  );
}

function PickRow({ p }: { p: Pick }) {
  const tone = OUTCOME_TONE[p.outcome ?? "pending"] ?? "var(--ink-dim)";
  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 10, padding: "8px 0",
        borderBottom: "1px solid var(--line-dim)", flexWrap: "wrap",
      }}
    >
      <span className="mono" style={{ fontSize: 10, color: "var(--ink-faint)", width: 16 }}>
        {p.rank}
      </span>
      <span className="mono" style={{ fontWeight: 700, minWidth: 56 }}>{p.ticker}</span>
      <span className="mono" style={{ fontSize: 11, color: "var(--ink-dim)" }}>
        OPP {p.opportunity_score ?? "—"}
      </span>
      <div style={{ flex: 1 }} />
      <span
        className="mono"
        style={{
          fontSize: 9, padding: "2px 7px", borderRadius: 3,
          color: tone, border: `1px solid ${tone}55`, whiteSpace: "nowrap",
        }}
      >
        {outcomeLabel(p.outcome)}
        {p.days_to_resolve != null ? ` · ${p.days_to_resolve}d` : ""}
      </span>
    </div>
  );
}

function Side({ label, picks, tone }: { label: string; picks: Pick[]; tone: string }) {
  return (
    <div style={{ minWidth: 0, flex: "1 1 260px" }}>
      <div className="mono" style={{ fontSize: 10, fontWeight: 700, color: tone, marginBottom: 4 }}>
        {label}
      </div>
      {picks.length === 0 ? (
        // A side with nothing is a real outcome — the desk ranked nothing that
        // way — and says so rather than showing an empty box.
        <div style={{ fontSize: 11, color: "var(--ink-faint)", padding: "8px 0" }}>
          none ranked
        </div>
      ) : (
        picks.map((p) => <PickRow key={`${p.rank}-${p.ticker}`} p={p} />)
      )}
    </div>
  );
}

export default function SignalCalendar({ days = 30 }: { days?: number }) {
  const [data, setData] = useState<CalendarResp | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (api.getSignalCalendar(days) as Promise<CalendarResp>)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setError(e?.message || "could not load the calendar"); });
    return () => { alive = false; };
  }, [days]);

  if (error) {
    // A fetch failure must not read as "no snapshots" — that would look like a
    // desk with no history rather than a page that could not load one.
    return (
      <Panel title="Daily Signal Calendar">
        <div style={{ color: "var(--red)", fontSize: 12 }}>
          Could not load the calendar: {error}
        </div>
      </Panel>
    );
  }

  if (!data) {
    return (
      <Panel title="Daily Signal Calendar">
        <div style={{ color: "var(--ink-faint)", fontSize: 12 }}>Loading…</div>
      </Panel>
    );
  }

  if (data.status !== "ok" || data.days.length === 0) {
    return (
      <Panel title="Daily Signal Calendar">
        <div style={{ color: "var(--ink-dim)", fontSize: 12, lineHeight: 1.7 }}>
          {data.note ||
            "No snapshots yet. The first one is captured at 10:00 ET on the next trading day."}
        </div>
      </Panel>
    );
  }

  const s = data.summary;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Panel title="Scorecard">
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <Stat label="DAYS" value={s?.trading_days ?? "—"} />
          <Stat label="PICKS" value={s?.picks ?? "—"} />
          <Stat label="RESOLVED" value={s?.resolved ?? "—"} />
          <Stat label="PENDING" value={s?.pending ?? "—"} tone="var(--amber)" />
          <Stat label="TARGET HIT" value={s?.target_hit ?? "—"} tone="var(--green)" />
          <Stat
            label="HIT RATE"
            value={s?.hit_rate_pct != null ? `${s.hit_rate_pct}%` : "—"}
            tone={s?.hit_rate_pct != null && s.hit_rate_pct >= 50 ? "var(--green)" : "var(--amber)"}
          />
        </div>
        <div style={{ marginTop: 10, fontSize: 11, color: "var(--ink-faint)", lineHeight: 1.6 }}>
          Frozen at 10:00 ET each trading day and never rewritten — these are the
          picks as they stood when you could have acted, not the best-scoring
          version of each found afterwards. Hit rate counts resolved signals
          only; pending is reported separately because an unresolved signal is
          not a miss.
        </div>
      </Panel>

      {data.days.map((d) => (
        <Panel key={d.date} title={d.date}>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <Side label="TOP 3 BUY" picks={d.BUY} tone="var(--green)" />
            <Side label="TOP 3 SELL" picks={d.SELL} tone="var(--red)" />
          </div>
        </Panel>
      ))}
    </div>
  );
}
