/**
 * Actionable next-step copy when the desk is empty or suspended.
 */

import type { DeskBlockContext } from "./signalBlockReason";

export function deskNextAction(
  ctx: DeskBlockContext,
  openCount: number,
): string | null {
  if (ctx.killEngaged) {
    return "Kill switch engaged — clear the kill switch to resume trading";
  }

  if (!ctx.tradingAllowed) {
    const lim = ctx.maxConsecutiveLosses;
    const streak =
      lim != null
        ? `${ctx.consecutiveLosses}/${lim}`
        : String(ctx.consecutiveLosses);

    if ((ctx.guardrailFlags || []).includes("consecutive_loss_limit")) {
      if (openCount <= 0) {
        return `Flat · streak ${streak} · need a green close (or raise paper consecutive-loss limit) to resume entries`;
      }
      return `Streak ${streak} · close a winner (≥ $0) to unlock new entries`;
    }

    if ((ctx.guardrailFlags || []).includes("daily_trade_cap")) {
      return "Daily trade cap reached — wait for next session or adjust mode caps";
    }

    if (ctx.guardrailReason) {
      const r = ctx.guardrailReason.replace(/\s+/g, " ").trim();
      return r.length > 96 ? `${r.slice(0, 94)}…` : r;
    }
    return "Trading suspended — check Guardrails for the blocking rule";
  }

  if (openCount <= 0) {
    return "Flat · run a scan and queue a signal that clears the style floor";
  }

  return null;
}
