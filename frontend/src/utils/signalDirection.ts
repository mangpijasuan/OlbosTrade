/** Map scanner actions to position side labels shown beside BUY/SELL. */
export function positionSideFromAction(action: string | null | undefined): "LONG" | "SHORT" | null {
  const a = (action || "").toUpperCase();
  if (a === "BUY" || a === "BUY_SPREAD" || a === "BULLISH") return "LONG";
  if (a === "SELL" || a === "SELL_SPREAD" || a === "BEARISH") return "SHORT";
  return null;
}

/** Normalize held-position direction (BUY/SELL or LONG/SHORT) to LONG/SHORT. */
export function normalizePositionSide(
  direction: string | null | undefined,
): "LONG" | "SHORT" | null {
  const d = (direction || "").toUpperCase();
  if (d === "LONG" || d === "BUY") return "LONG";
  if (d === "SHORT" || d === "SELL") return "SHORT";
  return null;
}

export function formatSignalAction(action: string | null | undefined): string {
  if (!action) return "—";
  return action.replace(/_/g, " ");
}

export function actionTone(action: string | null | undefined): string {
  const a = (action || "").toUpperCase();
  if (a === "BUY" || a === "BUY_SPREAD" || a === "BULLISH" || a === "LONG") return "var(--green)";
  if (a === "SELL" || a === "SELL_SPREAD" || a === "BEARISH" || a === "SHORT") return "var(--red)";
  if (a === "HOLD" || a === "NEUTRAL") return "var(--ink-dim)";
  return "var(--amber)";
}
