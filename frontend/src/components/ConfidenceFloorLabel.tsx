/**
 * Confidence vs trading-style floor — e.g. "78% · need 70%".
 */

import React from "react";
import { formatConfidenceFloor } from "../hooks/useTradingStyleFloor";

export default function ConfidenceFloorLabel({
  confidence,
  minConfidence,
  style,
}: {
  confidence: number | null | undefined;
  minConfidence: number;
  style?: React.CSSProperties;
}) {
  const { text, passes } = formatConfidenceFloor(confidence, minConfidence);
  const color =
    passes === true ? "var(--green)" :
    passes === false ? "var(--amber)" :
    "var(--ink-faint)";

  return (
    <span
      title={
        passes === false
          ? "Below trading-style minimum — Autopilot will block this signal"
          : passes === true
          ? "Meets trading-style minimum confidence"
          : "Trading-style minimum confidence"
      }
      style={{
        fontFamily: "var(--mono)",
        fontSize: 10,
        letterSpacing: "0.04em",
        color,
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {text}
    </span>
  );
}
