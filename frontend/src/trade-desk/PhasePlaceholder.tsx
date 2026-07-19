/**
 * Honest placeholder for desks/modules not yet built in Phase B.
 */

import React from "react";

export default function PhasePlaceholder({
  title,
  phase,
  detail,
}: {
  title: string;
  phase: string;
  detail: string;
}) {
  return (
    <div
      style={{
        padding: 32,
        maxWidth: 560,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--mono)",
          fontSize: 14,
          letterSpacing: "0.08em",
          color: "var(--ink)",
        }}
      >
        {title}
      </h2>
      <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 11, color: "var(--amber)" }}>
        Scheduled for {phase} — not built yet.
      </p>
      <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-dim)", lineHeight: 1.6 }}>
        {detail}
      </p>
    </div>
  );
}
