/**
 * Broker Gateway — live IBKR connection + capabilities from /api/market/broker.
 * The connect/disconnect controls live in Settings; this is the read-only ops view.
 */
import React, { useEffect, useState } from "react";

interface BrokerStatus {
  broker: string;
  status: "connected" | "disconnected" | "error";
  paper_mode?: boolean;
  supports_options?: boolean;
  supports_equities?: boolean;
  error?: string;
}

function StatusDot({ ok }: { ok: boolean }) {
  return <span className={`dot ${ok ? "live" : "dead"}`} style={{ marginRight: 8 }} />;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--line-dim)" }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-dim)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</span>
      <span style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{children}</span>
    </div>
  );
}

export default function BrokerGateway() {
  const [b, setB] = useState<BrokerStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    fetch("/api/market/broker")
      .then(r => r.json())
      .then(d => { setB(d); setLoading(false); })
      .catch(() => { setB({ broker: "unknown", status: "error", error: "unreachable" }); setLoading(false); });
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const connected = b?.status === "connected";

  return (
    <div style={{ padding: 16, height: "100%", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="panel-title">Broker Gateway</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          {loading ? "checking…" : "polls every 15s"}
        </span>
      </div>

      <div style={{ maxWidth: 520, border: "1px solid var(--line-dim)", background: "var(--bg-2)", padding: "12px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
          <StatusDot ok={connected} />
          <span style={{
            fontFamily: "var(--mono)", fontSize: 14, fontWeight: 600,
            color: connected ? "var(--green)" : b?.status === "error" ? "var(--red)" : "var(--amber)",
            textTransform: "uppercase", letterSpacing: "0.06em",
          }}>
            {b?.status ?? "…"}
          </span>
          {b?.paper_mode != null && (
            <span style={{
              marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 10,
              color: b.paper_mode ? "var(--amber)" : "var(--cyan)",
              border: `1px solid ${b.paper_mode ? "var(--amber)" : "var(--cyan)"}`,
              padding: "2px 7px", borderRadius: 2, textTransform: "uppercase", letterSpacing: "0.08em",
            }}>
              {b.paper_mode ? "paper" : "live"}
            </span>
          )}
        </div>

        <Field label="Broker">{(b?.broker ?? "—").toUpperCase()}</Field>
        <Field label="Equities">{b?.supports_equities ? "supported" : "—"}</Field>
        <Field label="Options">{b?.supports_options ? "supported" : "—"}</Field>
        {b?.error && <Field label="Error"><span style={{ color: "var(--red)" }}>{b.error}</span></Field>}
      </div>

      <div style={{ marginTop: 14, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-faint)", borderLeft: "2px solid var(--line-dim)", paddingLeft: 10, maxWidth: 520 }}>
        Connection is managed in Settings → Brokers. IBKR live ports are 4001 (Gateway) / 7496 (TWS); anything else is treated as paper.
      </div>
    </div>
  );
}
