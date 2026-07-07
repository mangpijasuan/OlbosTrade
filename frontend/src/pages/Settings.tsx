/**
 * Settings — SaaS account management (UI scaffold).
 *
 * NOTE: This is presentational only. There is no auth/tenancy/billing backend
 * yet, so nothing here persists. Broker API-key fields are WRITE-ONLY by
 * design — existing keys are shown masked (last 4 only) and never revealed;
 * the real value would be held server-side. Do not wire these to store keys
 * client-side.
 */

import React, { useState, useEffect } from "react";

type Tab = "profile" | "brokers" | "billing";

const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Profile & Security" },
  { key: "brokers", label: "Broker Integrations" },
  { key: "billing", label: "Subscription & Billing" },
];

const inputStyle: React.CSSProperties = {
  width: "100%", background: "var(--bg-3)", border: "1px solid var(--line-dim)",
  color: "var(--ink)", fontFamily: "var(--sans)", fontSize: 13,
  padding: "7px 10px", outline: "none", borderRadius: 4, boxSizing: "border-box",
};

function Panel({ title, desc, children, actions }: {
  title: string; desc?: string; children: React.ReactNode; actions?: React.ReactNode;
}) {
  return (
    <div style={{ border: "1px solid var(--line-dim)", background: "var(--bg-2)", borderRadius: 6 }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line-dim)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{title}</div>
          {desc && <div style={{ fontSize: 12, color: "var(--ink-dim)", marginTop: 2 }}>{desc}</div>}
        </div>
        {actions}
      </div>
      <div style={{ padding: 14 }}>{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="kicker" style={{ marginBottom: 5 }}>{label}</div>
      {children}
    </div>
  );
}

function HealthDot({ ok }: { ok: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: ok ? "var(--green)" : "var(--ink-dim)" }}>
      <span className={`dot ${ok ? "live" : "dead"}`} />
      {ok ? "Connected" : "Not connected"}
    </span>
  );
}

// ── Profile & Security ───────────────────────────────────────────────────────
function ProfileTab() {
  const [twoFA, setTwoFA] = useState(false);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, alignItems: "start" }}>
      <Panel title="Profile">
        <Field label="Email">
          <input style={inputStyle} type="email" defaultValue="mangpijasuan@zomiok.org" />
        </Field>
        <Field label="Display name">
          <input style={inputStyle} defaultValue="MJ" />
        </Field>
        <button className="btn-t active" style={{ marginTop: 4 }}>Save profile</button>
      </Panel>

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Panel title="Password">
          <Field label="Current password"><input style={inputStyle} type="password" placeholder="••••••••" /></Field>
          <Field label="New password"><input style={inputStyle} type="password" placeholder="••••••••" /></Field>
          <Field label="Confirm new password"><input style={inputStyle} type="password" placeholder="••••••••" /></Field>
          <button className="btn-t">Update password</button>
        </Panel>

        <Panel
          title="Two-factor authentication"
          desc={twoFA ? "2FA is enabled on your account." : "Add a second layer of security to sign-in."}
          actions={
            <span style={{
              fontSize: 12, padding: "2px 8px", borderRadius: 3,
              background: twoFA ? "rgba(34,197,94,0.15)" : "var(--fill-active)",
              color: twoFA ? "var(--green)" : "var(--ink-dim)",
              border: `1px solid ${twoFA ? "rgba(34,197,94,0.4)" : "var(--line-dim)"}`,
            }}>{twoFA ? "Enabled" : "Disabled"}</span>
          }
        >
          {!twoFA ? (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{
                width: 96, height: 96, background: "var(--bg-3)", border: "1px solid var(--line-dim)",
                borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center",
                color: "var(--ink-faint)", fontSize: 11, textAlign: "center",
              }}>QR code</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.6, marginBottom: 8 }}>
                  Scan with an authenticator app, then confirm the 6-digit code.
                </div>
                <button className="btn-t active" onClick={() => setTwoFA(true)}>Enable 2FA</button>
              </div>
            </div>
          ) : (
            <button className="btn-t danger" onClick={() => setTwoFA(false)}>Disable 2FA</button>
          )}
        </Panel>
      </div>
    </div>
  );
}

// ── Broker Integrations ──────────────────────────────────────────────────────
interface BrokerRow {
  name: string;
  fields: { label: string; masked?: string; placeholder?: string }[];
  connected: boolean;
  env?: string;
}

const BROKERS: BrokerRow[] = [
  { name: "Interactive Brokers", connected: true, env: "Paper", fields: [
    { label: "Username", placeholder: "ib_username" },
    { label: "API password", masked: "••••••••2305" },
  ]},
  { name: "Alpaca", connected: true, env: "Paper", fields: [
    { label: "API key ID", masked: "••••••••OK3R" },
    { label: "Secret key", masked: "••••••••FCBt" },
  ]},
  { name: "Tradier", connected: false, env: "Sandbox", fields: [
    { label: "Access token", placeholder: "Add token to connect" },
  ]},
];

function BrokerCard({ b }: { b: BrokerRow }) {
  const [replacing, setReplacing] = useState<Record<string, boolean>>({});
  return (
    <Panel
      title={b.name}
      desc={b.env ? `${b.env} environment` : undefined}
      actions={<HealthDot ok={b.connected} />}
    >
      {b.fields.map(f => (
        <Field key={f.label} label={f.label}>
          {f.masked && !replacing[f.label] ? (
            <div style={{ display: "flex", gap: 8 }}>
              <input style={{ ...inputStyle, fontFamily: "var(--mono)", color: "var(--ink-dim)" }} value={f.masked} readOnly />
              <button className="btn-t" onClick={() => setReplacing(r => ({ ...r, [f.label]: true }))}>Replace</button>
            </div>
          ) : (
            <input style={inputStyle} type="password" placeholder={f.placeholder || "Enter new value"} />
          )}
        </Field>
      ))}
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button className="btn-t active">{b.connected ? "Save keys" : "Connect"}</button>
        {b.connected && <button className="btn-t">Test connection</button>}
        {b.connected && <button className="btn-t danger">Disconnect</button>}
      </div>
    </Panel>
  );
}

// ── Live broker connection status (read-only, from /api/market/broker) ────────
interface BrokerLive {
  broker: string;
  status: "connected" | "disconnected" | "error";
  paper_mode?: boolean;
  supports_options?: boolean;
  supports_equities?: boolean;
  error?: string;
}

function LiveBrokerStatus() {
  const [info, setInfo] = useState<BrokerLive | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () =>
    fetch("/api/market/broker")
      .then(r => r.json())
      .then((d: BrokerLive) => setInfo(d))
      .catch(() => setInfo(null))
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const connected = info?.status === "connected";
  const errored = info?.status === "error";
  const tone = connected ? "var(--green)" : errored ? "var(--red)" : "var(--ink-dim)";
  const label = loading ? "Checking…"
    : connected ? "Connected"
    : errored ? "Error"
    : "Disconnected";

  const cells: { k: string; v: string; tone?: string }[] = [
    { k: "Broker", v: info ? info.broker.toUpperCase() : "—" },
    { k: "Session", v: label, tone },
    { k: "Mode", v: info?.paper_mode == null ? "—" : info.paper_mode ? "Paper" : "Live",
      tone: info?.paper_mode === false ? "var(--amber)" : "var(--ink)" },
    { k: "Capabilities", v: info ? [info.supports_equities && "Equities", info.supports_options && "Options"].filter(Boolean).join(" · ") || "—" : "—" },
  ];

  return (
    <Panel
      title="Connection status"
      desc="Live state of the trading engine's link to Interactive Brokers"
      actions={
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: tone }}>
          <span className={`dot ${connected ? "live" : "dead"}`} />
          {label}
        </span>
      }
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
        {cells.map(c => (
          <div key={c.k} style={{ background: "var(--bg-3)", borderRadius: 4, padding: "8px 10px" }}>
            <div className="kicker" style={{ marginBottom: 3 }}>{c.k}</div>
            <div className="tnum" style={{ fontSize: 13, fontWeight: 600, color: c.tone || "var(--ink)" }}>{c.v}</div>
          </div>
        ))}
      </div>
      {errored && info?.error && (
        <div style={{ marginTop: 10, fontFamily: "var(--mono)", fontSize: 11, color: "var(--red)" }}>{info.error}</div>
      )}
    </Panel>
  );
}

function BrokersTab() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <LiveBrokerStatus />

      {/* Secondary-username tip — the fix for the single-session lockout */}
      <div style={{
        border: "1px solid var(--line-dim)", background: "var(--bg-2)", borderRadius: 6,
        padding: "11px 14px", fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.7,
      }}>
        <span style={{ color: "var(--ink)", fontWeight: 600 }}>Locked out of IBKR web/mobile while trading?</span>{" "}
        The IB Gateway holds one login per username, so the browser Client Portal gets kicked. Fix it once:
        in IBKR <span style={{ color: "var(--ink)" }}>Client Portal → Settings → Users &amp; Access Rights</span>,
        add a <b style={{ color: "var(--ink)" }}>second username</b> and use it for the Gateway (in{" "}
        <span style={{ fontFamily: "var(--mono)" }}>backend/.env.prod</span>). Keep your primary username free for
        web/mobile — both can then stay logged in at once.
      </div>

      <div style={{ fontSize: 12, color: "var(--ink-dim)", display: "flex", alignItems: "center", gap: 7 }}>
        <i /> Keys are stored server-side and never displayed. Existing values show the last 4 characters only.
      </div>
      {BROKERS.map(b => <BrokerCard key={b.name} b={b} />)}
    </div>
  );
}

// ── Subscription & Billing ───────────────────────────────────────────────────
const LIMITS: { feature: string; usage: string; limit: string }[] = [
  { feature: "Concurrent algos", usage: "2", limit: "5" },
  { feature: "Open positions", usage: "0", limit: "25" },
  { feature: "Broker connections", usage: "2", limit: "3" },
  { feature: "Historical data", usage: "—", limit: "5 years" },
  { feature: "Signal scans / day", usage: "48", limit: "500" },
  { feature: "API rate", usage: "—", limit: "120 req/min" },
];

function BillingTab() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 14, alignItems: "start" }}>
      <Panel
        title="Plan limits"
        desc="Current tier: Pro"
        actions={<span style={{ fontSize: 12, padding: "2px 10px", borderRadius: 3, background: "rgba(59,130,246,0.15)", color: "var(--accent)", border: "1px solid rgba(59,130,246,0.4)" }}>Pro</span>}
      >
        <table className="t-table">
          <thead>
            <tr>
              <th>Feature</th>
              <th style={{ textAlign: "right" }}>Usage</th>
              <th style={{ textAlign: "right" }}>Limit</th>
            </tr>
          </thead>
          <tbody>
            {LIMITS.map(l => (
              <tr key={l.feature}>
                <td>{l.feature}</td>
                <td className="tnum" style={{ textAlign: "right", color: "var(--ink)" }}>{l.usage}</td>
                <td className="tnum" style={{ textAlign: "right", color: "var(--ink-dim)" }}>{l.limit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Panel title="Billing">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {[
              { label: "Status", val: "Active", color: "var(--green)" },
              { label: "Next invoice", val: "Aug 1, 2026", color: "var(--ink)" },
              { label: "Amount", val: "$49.00", color: "var(--ink)" },
              { label: "Payment method", val: "•••• 4242", color: "var(--ink)" },
            ].map(s => (
              <div key={s.label} style={{ background: "var(--bg-3)", borderRadius: 4, padding: "8px 10px" }}>
                <div className="kicker" style={{ marginBottom: 3 }}>{s.label}</div>
                <div className="tnum" style={{ fontSize: 14, fontWeight: 600, color: s.color }}>{s.val}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="btn-t active">Manage billing</button>
            <button className="btn-t">View invoices</button>
          </div>
        </Panel>

        <Panel title="Plan">
          <div style={{ fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.6, marginBottom: 10 }}>
            Upgrade for more concurrent algos, longer history, and higher rate limits.
          </div>
          <button className="btn-t">Change plan</button>
        </Panel>
      </div>
    </div>
  );
}

export default function Settings() {
  const [tab, setTab] = useState<Tab>("profile");

  return (
    <div style={{ padding: 14, maxWidth: 1000, display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "var(--ink)" }}>Settings</h2>
        <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--ink-dim)" }}>Account, brokers, and billing</p>
      </div>

      <div style={{ display: "flex", gap: 6, borderBottom: "1px solid var(--line-dim)", paddingBottom: 8 }}>
        {TABS.map(t => (
          <button key={t.key} className={`btn-t ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "profile" && <ProfileTab />}
      {tab === "brokers" && <BrokersTab />}
      {tab === "billing" && <BillingTab />}
    </div>
  );
}
