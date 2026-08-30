/**
 * Prominent BUY/SELL (or spread action) on signal cards. A LONG/SHORT side
 * chip appears only when a caller passes a positionDirection that actually
 * differs from what the action implies — otherwise it just repeats it.
 * SignalAttribution stays for source/confidence disclosure.
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
  showSide: showSideProp = true,
}: {
  action?: string | null;
  /** Held book direction when it differs from or supplements the scan action. */
  positionDirection?: string | null;
  size?: "sm" | "md";
  /** Force the side chip off even when a differing positionDirection exists. */
  showSide?: boolean;
}) {
  const actionLabel = formatSignalAction(action);
  if (!action || actionLabel === "—") return null;

  // A side derived from the action can only ever repeat it: BUY implies LONG,
  // SELL implies SHORT, so "BUY LONG" and "SELL SHORT" say one thing twice.
  // The chip earns its space only when a caller supplies a position direction
  // that genuinely disagrees with the action — a held short being bought back,
  // say. Deciding that here rather than per call site, because the opt-out
  // prop this replaces had to be remembered everywhere and mostly was not.
  const explicitSide = normalizePositionSide(positionDirection);
  const impliedSide = positionSideFromAction(action);
  const side = explicitSide;
  const tone = actionTone(action);
  const fontSize = size === "md" ? 11 : 10;
  const pad = size === "md" ? "3px 10px" : "2px 8px";
  const actionUpper = (action || "").toUpperCase();
  const showSide = Boolean(
    showSideProp && side && side !== actionUpper && side !== impliedSide,
  );

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
      {showSide && side && chip(side, tone, true)}
    </span>
  );
}
