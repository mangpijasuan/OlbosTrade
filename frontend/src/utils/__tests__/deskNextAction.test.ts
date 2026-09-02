import { describe, expect, it } from "vitest";
import { deskNextAction } from "../deskNextAction";
import type { DeskBlockContext } from "../signalBlockReason";

const base: DeskBlockContext = {
  killEngaged: false,
  tradingAllowed: true,
  guardrailReason: null,
  guardrailFlags: [],
  consecutiveLosses: 0,
  maxConsecutiveLosses: 8,
  tradesToday: 0,
  maxTradesPerDay: 20,
  openCount: 0,
  maxConcurrent: 5,
  minConfidence: 0.7,
};

describe("deskNextAction", () => {
  it("prioritizes kill switch", () => {
    expect(
      deskNextAction({ ...base, killEngaged: true, tradingAllowed: false }, 0),
    ).toMatch(/kill switch/i);
  });

  it("explains flat + consecutive-loss catch-22", () => {
    const msg = deskNextAction(
      {
        ...base,
        tradingAllowed: false,
        guardrailFlags: ["consecutive_loss_limit"],
        consecutiveLosses: 4,
        maxConsecutiveLosses: 8,
      },
      0,
    );
    expect(msg).toMatch(/Flat/);
    expect(msg).toMatch(/4\/8/);
  });

  it("returns null when trading and carrying positions", () => {
    expect(deskNextAction({ ...base, openCount: 2 }, 2)).toBeNull();
  });
});
