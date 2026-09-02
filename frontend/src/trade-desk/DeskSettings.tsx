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
    <div className="page-shell" style={{ maxWidth: 720, display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="instrument-card page-header">
        <div>
          <div className="page-header__title">Desk Settings</div>
          <p className="page-header__sub">Trading style floors and Trade Desk version</p>
        </div>
      </div>

      <section className="instrument-card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="panel-title">Trading style</div>
        <p className="kicker" style={{ lineHeight: 1.6 }}>
          Sets Autopilot entry floors (min confidence, daily caps, sizing).
          Balanced requires ~90% confidence — that is why ~75% top signals were
          blocked. Aggressive floors at 70%. Same OMS for every style.
        </p>
        <TradingModeSelector />
      </section>

      <section className="instrument-card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="panel-title">Trade Desk version</div>
        <p className="kicker" style={{ lineHeight: 1.6 }}>
          Trade Desk 2.0 is the default. Turn it off to roll back to the legacy
          Trade Desk nav/pages. Same OMS either way — no execution-path change.
        </p>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            fontFamily: "var(--sans)",
            fontSize: 12,
            color: "var(--ink)",
            cursor: "pointer",
          }}
        >
          <input type="checkbox" checked={enabled} onChange={toggle} />
          Trade Desk 2.0 enabled ({enabled ? "ON — default" : "OFF — legacy"})
        </label>
        <p className="empty-chassis__hint" style={{ margin: 0 }}>
          Storage key: olbos.flags.trade_desk_v2 · set to 0 to roll back
        </p>
      </section>
    </div>
  );
}
