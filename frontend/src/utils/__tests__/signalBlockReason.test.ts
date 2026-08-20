import { describe, expect, it } from "vitest";
import { deriveSignalBlockReason, type DeskBlockContext } from "../signalBlockReason";

const clear: DeskBlockContext = {
  killEngaged: false,
  tradingAllowed: true,
  guardrailReason: null,
  guardrailFlags: [],
  consecutiveLosses: 0,
  maxConsecutiveLosses: 8,
  tradesToday: 0,
  maxTradesPerDay: 20,
  openCount: 1,
  maxConcurrent: 5,
  minConfidence: 0.7,
};

describe("deriveSignalBlockReason", () => {
  it("ignores HOLD", () => {
    expect(deriveSignalBlockReason({ action: "HOLD", confidence: 0.9 }, clear)).toBeNull();
  });

  it("prioritizes kill switch", () => {
    const r = deriveSignalBlockReason(
      { action: "BUY", confidence: 0.95 },
      { ...clear, killEngaged: true, tradingAllowed: false },
    );
    expect(r?.code).toBe("kill_switch");
  });

  it("surfaces consecutive losses", () => {
    const r = deriveSignalBlockReason(
      { action: "BUY", confidence: 0.95 },
      {
        ...clear,
        tradingAllowed: false,
        guardrailFlags: ["consecutive_loss_limit"],
        consecutiveLosses: 4,
        maxConsecutiveLosses: 8,
      },
    );
    expect(r?.label).toBe("consec losses 4/8");
  });

  it("flags below floor", () => {
    const r = deriveSignalBlockReason(
      { action: "BUY", confidence: 0.65 },
      clear,
    );
    expect(r?.code).toBe("below_min_confidence");
  });

  it("flags max positions", () => {
    const r = deriveSignalBlockReason(
      { action: "SELL", confidence: 0.9 },
      { ...clear, openCount: 5, maxConcurrent: 5 },
    );
    expect(r?.code).toBe("max_positions");
    expect(r?.label).toContain("5/5");
  });

  it("returns null when clear", () => {
    expect(
      deriveSignalBlockReason({ action: "BUY", confidence: 0.85 }, clear),
    ).toBeNull();
  });
});
