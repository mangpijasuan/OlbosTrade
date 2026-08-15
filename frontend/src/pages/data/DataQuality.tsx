/**
 * Data Quality — operational health from /api/health/detail: scanner heartbeat,
 * kill-switch state, regime classification, and observability counters/events.
 */
import React, { useEffect, useState } from "react";
import { Panel } from "../../components/ui";

interface ObsEvent {
  ts: number;
  name: string;
  ticker?: string;
  asset_type?: string;
  reason?: string;
  order_id?: string | number;
  [key: string]: any;
}

interface Observability {
  uptime_seconds?: number;
  counters?: Record<string, number>;
  gauges?: Record<string, number>;
  recent_events?: ObsEvent[];
  event_count?: number;
}

interface IbkrHealth {
  connected: boolean;
  coordinator: {
    workers: number;
    reserved_workers: number;
    active_requests: number;
    queue_depth: Record<string, number>;
    in_flight_dedup_keys: number;
  };
  options_chain_cache: { hits: number; misses: number; hit_rate: number | null; entries: number };
}

interface Health {
  status?: string;
  broker?: string;
  scanner?: { alive: boolean; last_tick_age_seconds: number | null };
  kill_switch?: { engaged: boolean; reason: string | null };
  regime?: string | null;
  observability?: Observability;
  ibkr?: IbkrHealth;
}

function Check({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderBottom: "1px solid var(--line-dim)" }}>
      <span className={`dot ${ok ? "live" : "dead"}`} />
      <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: ok ? "var(--ink)" : "var(--red)", minWidth: 170 }}>{label}</span>
      <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", marginLeft: "auto" }}>{detail}</span>
    </div>
  );
}

function formatUptime(seconds: number | undefined): string {
  if (seconds == null) return "—";
  const s = Math.floor(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function relativeTime(ts: number, now: number): string {
  const deltaS = Math.max(0, Math.round(now - ts));
  if (deltaS < 60) return `${deltaS}s ago`;
  if (deltaS < 3600) return `${Math.round(deltaS / 60)}m ago`;
  if (deltaS < 86400) return `${Math.round(deltaS / 3600)}h ago`;
  return `${Math.round(deltaS / 86400)}d ago`;
}

function eventTone(name: string): string {
  const n = name.toLowerCase();
  if (n === "blocked") return "var(--amber)";
  if (n === "submitted" || n === "filled") return "var(--green)";
  if (n === "skipped") return "var(--ink-dim)";
  return "var(--cyan)";
}

function CounterStrip({ counters }: { counters: Record<string, number> }) {
  const entries = Object.entries(counters);
  if (entries.length === 0) return null;
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: "10px 0", borderBottom: "1px solid var(--line-dim)" }}>
      {entries.map(([k, v]) => (
        <span key={k} style={{
          fontFamily: "var(--mono)", fontSize: 10.5, padding: "3px 9px",
          background: "var(--bg-3)", border: "1px solid var(--line-dim)", color: "var(--ink-dim)",
        }}>
          {k.replace(/_/g, " ")} <span style={{ color: "var(--ink)", fontWeight: 700 }}>{v}</span>
        </span>
      ))}
    </div>
  );
}

function EventRow({ e, now }: { e: ObsEvent; now: number }) {
  const { ts, name, ticker, asset_type, reason, ...rest } = e;
  const extra = Object.entries(rest).filter(([, v]) => v != null && v !== "");
  return (
    <div style={{
      display: "flex", alignItems: "baseline", gap: 10, padding: "6px 0",
      borderBottom: "1px solid var(--line-dim)", fontFamily: "var(--mono)", fontSize: 11,
    }}>
      <span style={{ color: "var(--ink-faint)", minWidth: 56, flexShrink: 0 }}>{relativeTime(ts, now)}</span>
      <span style={{
        color: eventTone(name), border: `1px solid ${eventTone(name)}66`, padding: "0 6px",
        textTransform: "uppercase", fontSize: 9.5, flexShrink: 0,
      }}>
        {name}
      </span>
      {ticker && <span style={{ color: "var(--ink)", fontWeight: 700, flexShrink: 0 }}>{ticker}</span>}
      {asset_type && <span style={{ color: "var(--ink-faint)", flexShrink: 0 }}>{asset_type}</span>}
      {reason && <span style={{ color: "var(--ink-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{reason}</span>}
      {extra.length > 0 && (
        <span style={{ color: "var(--ink-faint)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {extra.map(([k, v]) => `${k}=${v}`).join(" · ")}
        </span>
      )}
    </div>
  );
}

export default function DataQuality() {
  const [h, setH] = useState<Health | null>(null);
  const [err, setErr] = useState(false);
  const [now, setNow] = useState(() => Date.now() / 1000);

  const load = () => {
    fetch("/api/health/detail")
      .then(r => r.json())
      .then(d => { setH(d); setErr(false); setNow(Date.now() / 1000); })
      .catch(() => setErr(true));
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const scannerOk = !!h?.scanner?.alive;
  const age = h?.scanner?.last_tick_age_seconds;
  const ksEngaged = !!h?.kill_switch?.engaged;
  const obs = h?.observability ?? {};
  const events = obs.recent_events ?? [];

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Data Quality</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          operational heartbeat · polls every 15s
        </span>
      </div>

      {err ? (
        <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--red)", padding: 24 }}>
          ⚠ health endpoint unreachable
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 640 }}>
          <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)", padding: "6px 16px 4px" }}>
            <Check ok={h?.status === "ok"} label="Service"
              detail={h?.status === "ok" ? "ok" : (h?.status ?? "…")} />
            <Check ok={scannerOk} label="Scanner heartbeat"
              detail={age != null ? `last tick ${age}s ago` : "no tick yet"} />
            <Check ok={!ksEngaged} label="Kill switch"
              detail={ksEngaged ? `ENGAGED — ${h?.kill_switch?.reason ?? "manual"}` : "clear"} />
            <Check ok={!!h?.regime} label="Regime classified"
              detail={h?.regime ? String(h.regime).replace(/_/g, " ") : "unclassified"} />
            <Check ok={true} label="Uptime" detail={formatUptime(obs.uptime_seconds)} />
            {obs.counters && <CounterStrip counters={obs.counters} />}
          </div>

          {h?.ibkr && (
            <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)", padding: "6px 16px 4px" }}>
              <div className="panel-title" style={{ padding: "8px 0 4px" }}>IBKR Connection</div>
              <Check ok={h.ibkr.connected} label="Broker connection"
                detail={h.ibkr.connected ? "connected" : "disconnected"} />
              <Check ok={true} label="Active requests"
                detail={`${h.ibkr.coordinator.active_requests} in flight · ${h.ibkr.coordinator.workers} workers (${h.ibkr.coordinator.reserved_workers} reserved for P0/P1)`} />
              <Check ok={true} label="Options chain cache"
                detail={h.ibkr.options_chain_cache.hit_rate != null
                  ? `${Math.round(h.ibkr.options_chain_cache.hit_rate * 100)}% hit rate · ${h.ibkr.options_chain_cache.entries} cached`
                  : "no requests yet"} />
              <CounterStrip counters={Object.fromEntries(
                Object.entries(h.ibkr.coordinator.queue_depth).map(([k, v]) => [`queue depth ${k.toLowerCase()}`, v])
              )} />
            </div>
          )}

          <Panel
            padding={0}
            title="Recent Events"
            action={<span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>{obs.event_count ?? events.length} newest first</span>}
          >
            {events.length === 0 ? (
              <div style={{ padding: 24, textAlign: "center", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)" }}>
                No events recorded yet this process.
              </div>
            ) : (
              <div style={{ padding: "4px 14px", maxHeight: 400, overflowY: "auto" }}>
                {events.map((e, i) => <EventRow key={`${e.ts}-${i}`} e={e} now={now} />)}
              </div>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
