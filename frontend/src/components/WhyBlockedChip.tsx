/**
 * One-line Autopilot block preview on signal cards.
 */

import React from "react";
import type { SignalBlockReason } from "../utils/signalBlockReason";

export default function WhyBlockedChip({
  reason,
}: {
  reason: SignalBlockReason | null;
}) {
  if (!reason) return null;

  return (
    <span
      title={`Likely Autopilot block: ${reason.code}. Run Evaluate for the authoritative gate list.`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontFamily: "var(--mono)",
        fontSize: 9,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        color: "var(--amber)",
        border: "1px solid rgba(245,158,11,0.4)",
        background: "rgba(245,158,11,0.08)",
        padding: "2px 7px",
        borderRadius: 2,
        whiteSpace: "nowrap",
      }}
    >
      blocked · {reason.label}
    </span>
  );
}
