/**
 * Prominent BUY/SELL (or spread action) plus LONG/SHORT side — always visible
 * on signal cards. SignalAttribution stays for source/confidence disclosure.
 */
import React from "react";
import {
  actionTone,
  formatSignalAction,
  normalizePositionSide,
  positionSideFromAction,
} from "../utils/signalDirection";

export default function SignalDirectionBadge({
  action,
  positionDirection,
  size = "sm",
}: {
  action?: string | null;
  /** Held book direction when it differs from or supplements the scan action. */
  positionDirection?: string | null;
  size?: "sm" | "md";
}) {
  const actionLabel = formatSignalAction(action);
  if (!action || actionLabel === "—") return null;

  const side =
    normalizePositionSide(positionDirection) ?? positionSideFromAction(action);
  const tone = actionTone(action);
  const fontSize = size === "md" ? 11 : 10;
  const pad = size === "md" ? "3px 10px" : "2px 8px";
  const actionUpper = (action || "").toUpperCase();
  const showSide = side && side !== actionUpper;

  const chip = (label: string, color: string, muted = false) => (
    <span
      className="mono"
      style={{
        fontSize,
        fontWeight: 700,
        letterSpacing: "0.06em",
        padding: pad,
        borderRadius: 3,
        color,
        border: `1px solid ${color}${muted ? "55" : "88"}`,
        background: muted ? "transparent" : `${color}18`,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
      {chip(actionLabel, tone)}
      {showSide && chip(side, tone, true)}
    </span>
  );
}
