/**
 * Desk Settings — Phase B flag toggle for rollback to legacy Trade Desk.
 */

import React, { useState } from "react";
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
    <div style={{ padding: 24, maxWidth: 520, display: "flex", flexDirection: "column", gap: 14 }}>
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
      <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.6 }}>
        Trade Desk 2.0 is opt-in. Default experience stays the legacy Trade Desk
        until you enable this. Turning it on switches nav + pages to V2
        (Equity/Options desks, Copilot Queue, Orders, Execution, Replay). No
        execution-path change — same OMS.
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
        Trade Desk 2.0 enabled ({enabled ? "ON" : "OFF — legacy default"})
      </label>
      <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faint)" }}>
        Storage key: olbos.flags.trade_desk_v2 · set to 1 to opt in, 0 to roll back
      </p>
    </div>
  );
}
