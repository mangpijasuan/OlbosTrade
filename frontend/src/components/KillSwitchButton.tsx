import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { Button } from "./ui";

type Variant = "sidebar" | "panel";

function HaltIcon({ engaged }: { engaged: boolean }) {
  return (
    <span className="instrument-halt__icon" aria-hidden="true">
      {engaged ? (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
          <circle cx="5" cy="5" r="4" />
        </svg>
      ) : (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
          <rect x="1.5" y="1.5" width="7" height="7" rx="1" />
        </svg>
      )}
    </span>
  );
}

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

  const label = engaged ? "Trading halted" : busy ? "Engaging…" : "Kill switch";
  const badge = engaged ? "Active" : "Halt";
  const showCopy = variant === "panel" || expanded;
  const disabled = variant === "sidebar" ? busy : engaged || busy;

  return (
    <>
      <button
        type="button"
        onClick={() => !engaged && setConfirming(true)}
        aria-label={engaged ? "Kill switch engaged" : "Engage kill switch"}
        disabled={disabled}
        title={engaged ? "Kill switch is engaged" : "Engage kill switch"}
        className={`instrument-halt${engaged ? " is-engaged" : ""}`}
        style={{
          width: "100%",
          minHeight: 36,
          display: "flex",
          alignItems: "center",
          justifyContent: showCopy ? "flex-start" : "center",
          gap: showCopy ? 8 : 0,
          padding: showCopy ? "6px 10px" : "6px 0",
        }}
      >
        <HaltIcon engaged={engaged} />
        {showCopy && (
          <>
            <span className="instrument-halt__label" style={{ flex: 1, textAlign: "left", minWidth: 0 }}>
              {label}
            </span>
            <span className="instrument-halt__badge">{badge}</span>
          </>
        )}
      </button>
      {variant === "panel" && message && !confirming && (
        <div style={{ fontFamily: "var(--sans)", fontSize: 11, color: engaged ? "var(--red)" : "var(--ink-dim)", lineHeight: 1.5 }}>
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
      <div className="glass-surface" style={{ width: "100%", maxWidth: 440, border: "1px solid rgba(239,68,68,0.48)", padding: 20 }}>
        <div id="kill-switch-title" style={{ fontFamily: "var(--sans)", fontSize: 15, color: "var(--red)", fontWeight: 700, marginBottom: 10 }}>
          Engage kill switch?
        </div>
        <div style={{ fontFamily: "var(--sans)", color: "var(--ink-dim)", fontSize: 12, lineHeight: 1.7, marginBottom: 16 }}>
          This will halt new order submission and ask the broker layer to cancel open orders and flatten positions. Resume requires a manual reset.
        </div>
        {message && (
          <div style={{ fontFamily: "var(--sans)", color: "var(--red)", fontSize: 11, marginBottom: 12 }}>
            {message}
          </div>
        )}
        <div style={{ display: "flex", gap: 10 }}>
          <Button onClick={onCancel} disabled={busy} style={{ flex: 1 }}>
            Cancel
          </Button>
          <Button danger onClick={onConfirm} disabled={busy} style={{ flex: 1 }}>
            {busy ? "Engaging..." : "Confirm halt"}
          </Button>
        </div>
      </div>
    </div>
  );
}
