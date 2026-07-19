/**
 * First-visit welcome on Command Center — dismissible, never blocks trading chrome.
 */
import React from "react";
import { useTerminalNav } from "./TerminalNavContext";

export const WELCOME_DISMISS_KEY = "olbos.welcome.dismissed";

export default function WelcomeBanner({ onDismiss }: { onDismiss: () => void }) {
  const onNav = useTerminalNav();

  const step = (
    n: string,
    title: string,
    detail: string,
    action?: { label: string; page: string },
  ) => (
    <div
      key={n}
      style={{
        display: "flex",
        gap: 12,
        alignItems: "flex-start",
        padding: "10px 0",
        borderBottom: "1px solid var(--line-dim)",
      }}
    >
      <span
        className="mono"
        style={{
          width: 22,
          height: 22,
          borderRadius: 11,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          fontWeight: 700,
          color: "var(--cyan)",
          background: "var(--cyan-dim)",
          border: "1px solid rgba(59,130,246,0.35)",
        }}
      >
        {n}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: "var(--sans)", fontSize: 13, fontWeight: 600, color: "var(--ink)", marginBottom: 2 }}>
          {title}
        </div>
        <div style={{ fontFamily: "var(--sans)", fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.5 }}>
          {detail}
        </div>
        {action && (
          <button
            type="button"
            className="btn-t"
            onClick={() => onNav(action.page)}
            style={{ marginTop: 8 }}
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <section
      aria-label="Getting started"
      style={{
        margin: "12px 16px 0",
        padding: "14px 16px",
        background: "var(--bg-2)",
        border: "1px solid var(--line-dim)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 4 }}>
        <div style={{ flex: 1 }}>
          <div className="kicker" style={{ marginBottom: 6 }}>Getting started</div>
          <div style={{ fontFamily: "var(--sans)", fontSize: 15, fontWeight: 600, color: "var(--ink)" }}>
            Three steps before you trade
          </div>
          <div style={{ fontFamily: "var(--sans)", fontSize: 12, color: "var(--ink-dim)", marginTop: 4, lineHeight: 1.5 }}>
            Stay in Manual execution mode until you understand a signal. Nothing here places an order.
          </div>
        </div>
        <button
          type="button"
          className="btn-t"
          onClick={onDismiss}
          aria-label="Dismiss welcome"
          style={{ flexShrink: 0 }}
        >
          Dismiss
        </button>
      </div>

      {step(
        "1",
        "Confirm your broker",
        "Open System → Broker and make sure IBKR shows paper and connected.",
        { label: "Open Broker", page: "system:broker" },
      )}
      {step(
        "2",
        "Keep execution on Manual",
        "Use the Manual / Copilot / Autopilot control in the header. Manual only shows signals — it does not auto-trade.",
      )}
      {step(
        "3",
        "Review one signal",
        "Open Strategies → Signals and read the attribution on a card before approving anything in Copilot.",
        { label: "Open Signals", page: "equity" },
      )}
    </section>
  );
}
