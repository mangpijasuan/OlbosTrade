/**
 * Desk Settings — V2 toggle + Trading Style (risk mode).
 */

import React, { useState } from "react";
import TradingModeSelector from "../components/TradingModeSelector";
import { isTradeDeskV2Enabled, setFlagEnabled } from "./featureFlags";

export default function DeskSettings() {
  const [enabled, setEnabled] = useState(() => isTradeDeskV2Enabled());

  const toggle = () => {
    const next = !enabled;
    setFlagEnabled("trade_desk_v2", next);
    setEnabled(next);
    // Reload so App + TerminalLayout pick up the nav model and page map.
    window.location.reload();
  };

  return (
    <div style={{ padding: 24, maxWidth: 720, display: "flex", flexDirection: "column", gap: 22 }}>
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--mono)",
          fontSize: 14,
          letterSpacing: "0.08em",
          color: "var(--ink)",
        }}
      >
        DESK SETTINGS
      </h2>

      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--mono)",
            fontSize: 12,
            letterSpacing: "0.08em",
            color: "var(--ink-dim)",
          }}
        >
          TRADING STYLE
        </h3>
        <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.6 }}>
          Sets Autopilot entry floors (min confidence, daily caps, sizing).
          Balanced requires ~90% confidence — that is why ~75% top signals were
          blocked. Aggressive floors at 70%. Same OMS for every style.
        </p>
        <TradingModeSelector />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--mono)",
            fontSize: 12,
            letterSpacing: "0.08em",
            color: "var(--ink-dim)",
          }}
        >
          TRADE DESK VERSION
        </h3>
        <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.6 }}>
          Trade Desk 2.0 is the default. Turn it off to roll back to the legacy
          Trade Desk nav/pages. Same OMS either way — no execution-path change.
        </p>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            fontFamily: "var(--mono)",
            fontSize: 12,
            color: "var(--ink)",
            cursor: "pointer",
          }}
        >
          <input type="checkbox" checked={enabled} onChange={toggle} />
          Trade Desk 2.0 enabled ({enabled ? "ON — default" : "OFF — legacy"})
        </label>
        <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
          Storage key: olbos.flags.trade_desk_v2 · set to 0 to roll back
        </p>
      </section>
    </div>
  );
}
