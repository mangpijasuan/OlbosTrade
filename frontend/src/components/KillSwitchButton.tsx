import React, { useEffect, useState } from "react";
import { api } from "../api/client";

type Variant = "sidebar" | "panel";

export default function KillSwitchButton({
  variant = "panel",
  expanded = true,
  onEngaged,
}: {
  variant?: Variant;
  expanded?: boolean;
  onEngaged?: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [engaged, setEngaged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const readEngaged = (status: any) =>
    Boolean(status?.engaged ?? status?.active ?? status?.kill_switch_engaged ?? status?.kill_switch_active);

  const load = async () => {
    try {
      const status: any = await api.getTradeDeskKillSwitch();
      setEngaged(readEngaged(status));
    } catch {
      try {
        const status: any = await api.getKillSwitchStatus();
        setEngaged(readEngaged(status));
      } catch {
        setMessage("Kill switch status unavailable.");
      }
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  const engage = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result: any = await api.setTradeDeskKillSwitch(true);
      setEngaged(readEngaged(result));
      setConfirming(false);
      setMessage("Kill switch engaged. New orders are halted.");
      onEngaged?.();
    } catch (err: any) {
      setMessage(err?.message || "Could not engage kill switch.");
    } finally {
      setBusy(false);
    }
  };

  if (variant === "sidebar") {
    return (
      <>
        <button
          onClick={() => !engaged && setConfirming(true)}
          aria-label={engaged ? "Kill switch engaged" : "Engage kill switch"}
          disabled={busy}
          title={engaged ? "Kill switch is engaged" : "Engage kill switch"}
          style={{
            width: "100%",
            minHeight: 30,
            display: "flex",
            alignItems: "center",
            justifyContent: expanded ? "space-between" : "center",
            gap: 8,
            border: "1px solid transparent",
            background: engaged ? "rgba(239,68,68,0.12)" : "transparent",
            color: "var(--red)",
            cursor: engaged || busy ? "default" : "pointer",
            padding: expanded ? "0 8px" : 0,
            fontFamily: "var(--sans)",
          }}
        >
          {expanded && (
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em" }}>
              {engaged ? "Halted" : "Kill Switch"}
            </span>
          )}
          <span aria-hidden="true" style={{ fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1 }}>HALT</span>
        </button>
        {confirming && <KillConfirmModal busy={busy} message={message} onCancel={() => setConfirming(false)} onConfirm={engage} />}
      </>
    );
  }

  return (
    <>
      <button
        className="btn-t danger"
        onClick={() => !engaged && setConfirming(true)}
        aria-label={engaged ? "Kill switch engaged" : "Engage kill switch"}
        disabled={engaged || busy}
        style={{ padding: "10px 0", justifyContent: "center", display: "flex", fontWeight: 600 }}
      >
        {engaged ? "KILL SWITCH ENGAGED" : busy ? "ENGAGING..." : "ENGAGE KILL SWITCH"}
      </button>
      {message && !confirming && (
        <div style={{ fontSize: 11, color: engaged ? "var(--red)" : "var(--ink-dim)", lineHeight: 1.6 }}>
          {message}
        </div>
      )}
      {confirming && <KillConfirmModal busy={busy} message={message} onCancel={() => setConfirming(false)} onConfirm={engage} />}
    </>
  );
}

function KillConfirmModal({
  busy,
  message,
  onCancel,
  onConfirm,
}: {
  busy: boolean;
  message: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="kill-switch-title"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 300,
        background: "rgba(0,0,0,0.72)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div style={{ width: "100%", maxWidth: 440, background: "var(--bg-2)", border: "1px solid rgba(239,68,68,0.48)", padding: 20 }}>
        <div id="kill-switch-title" style={{ fontSize: 15, color: "var(--red)", fontWeight: 700, marginBottom: 10 }}>
          Engage kill switch?
        </div>
        <div style={{ color: "var(--ink-dim)", fontSize: 12, lineHeight: 1.7, marginBottom: 16 }}>
          This will halt new order submission and ask the broker layer to cancel open orders and flatten positions. Resume requires a manual reset.
        </div>
        {message && (
          <div style={{ color: "var(--red)", fontSize: 11, marginBottom: 12 }}>
            {message}
          </div>
        )}
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn-t" onClick={onCancel} disabled={busy} style={{ flex: 1 }}>
            Cancel
          </button>
          <button className="btn-t danger" onClick={onConfirm} disabled={busy} style={{ flex: 1 }}>
            {busy ? "Engaging..." : "Confirm halt"}
          </button>
        </div>
      </div>
    </div>
  );
}
