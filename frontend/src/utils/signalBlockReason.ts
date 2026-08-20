/**
 * Client-side Autopilot block preview — mirrors common OMS gates without
 * calling evaluate per signal. Heuristic only; Evaluate remains authoritative.
 */

export type DeskBlockContext = {
  killEngaged: boolean;
  tradingAllowed: boolean;
  guardrailReason: string | null;
  guardrailFlags: string[];
  consecutiveLosses: number;
  maxConsecutiveLosses: number | null;
  tradesToday: number;
  maxTradesPerDay: number | null;
  openCount: number;
  maxConcurrent: number | null;
  minConfidence: number;
};

export type SignalBlockReason = {
  code: string;
  label: string;
};

function shortGuardrailLabel(ctx: DeskBlockContext): string {
  const flags = ctx.guardrailFlags || [];
  if (flags.includes("consecutive_loss_limit")) {
    const lim =
      typeof ctx.maxConsecutiveLosses === "number"
        ? `${ctx.consecutiveLosses}/${ctx.maxConsecutiveLosses}`
        : String(ctx.consecutiveLosses);
    return `consec losses ${lim}`;
  }
  if (flags.includes("daily_trade_cap")) {
    const lim =
      typeof ctx.maxTradesPerDay === "number"
        ? `${ctx.tradesToday}/${ctx.maxTradesPerDay}`
        : "daily cap";
    return `daily cap ${lim}`;
  }
  if (flags.includes("daily_loss_limit")) return "daily loss limit";
  if (flags.includes("weekly_loss_limit")) return "weekly loss limit";
  if (flags.includes("monthly_loss_limit")) return "monthly loss limit";
  if (flags.includes("max_drawdown")) return "max drawdown";
  if (ctx.guardrailReason) {
    const r = ctx.guardrailReason.replace(/\s+/g, " ").trim();
    return r.length > 42 ? `${r.slice(0, 40)}…` : r;
  }
  return "guardrails";
}

/**
 * First matching block reason for a signal, or null if it looks clear.
 * HOLD returns null (not an executable candidate).
 */
export function deriveSignalBlockReason(
  signal: { action?: string; confidence?: number | null },
  ctx: DeskBlockContext,
): SignalBlockReason | null {
  const action = (signal.action || "").toUpperCase();
  if (action === "HOLD" || !action) return null;

  if (ctx.killEngaged) {
    return { code: "kill_switch", label: "kill switch" };
  }

  if (!ctx.tradingAllowed) {
    return { code: "guardrails", label: shortGuardrailLabel(ctx) };
  }

  if (
    typeof signal.confidence === "number" &&
    signal.confidence + 1e-9 < ctx.minConfidence
  ) {
    return { code: "below_min_confidence", label: "below floor" };
  }

  if (
    typeof ctx.maxConcurrent === "number" &&
    ctx.maxConcurrent > 0 &&
    ctx.openCount >= ctx.maxConcurrent
  ) {
    return {
      code: "max_positions",
      label: `max positions ${ctx.openCount}/${ctx.maxConcurrent}`,
    };
  }

  return null;
}
