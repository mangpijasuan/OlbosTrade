/**
 * Data Quality — operational health from /api/health/detail: scanner heartbeat,
 * kill-switch state, regime classification, and observability counters.
 */
import React, { useEffect, useState } from "react";

interface Health {
  status?: string;
  broker?: string;
  scanner?: { alive: boolean; last_tick_age_seconds: number | null };
  kill_switch?: { engaged: boolean; reason: string | null };
  regime?: string | null;
  observability?: Record<string, any>;
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

export default function DataQuality() {
  const [h, setH] = useState<Health | null>(null);
  const [err, setErr] = useState(false);

  const load = () => {
    fetch("/api/health/detail")
      .then(r => r.json())
      .then(d => { setH(d); setErr(false); })
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
        <div style={{ maxWidth: 560, border: "1px solid var(--line-dim)", background: "var(--bg-2)", padding: "6px 16px 12px" }}>
          <Check ok={h?.status === "ok"} label="Service"
            detail={h?.status === "ok" ? "ok" : (h?.status ?? "…")} />
          <Check ok={scannerOk} label="Scanner heartbeat"
            detail={age != null ? `last tick ${age}s ago` : "no tick yet"} />
          <Check ok={!ksEngaged} label="Kill switch"
            detail={ksEngaged ? `ENGAGED — ${h?.kill_switch?.reason ?? "manual"}` : "clear"} />
          <Check ok={!!h?.regime} label="Regime classified"
            detail={h?.regime ? String(h.regime).replace(/_/g, " ") : "unclassified"} />
          {Object.entries(obs).slice(0, 8).map(([k, v]) => (
            <Check key={k} ok={true} label={k.replace(/_/g, " ")}
              detail={typeof v === "object" ? JSON.stringify(v) : String(v)} />
          ))}
        </div>
      )}
    </div>
  );
}
