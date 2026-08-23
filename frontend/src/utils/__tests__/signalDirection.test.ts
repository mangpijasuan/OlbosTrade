import { describe, it, expect } from "vitest";
import {
  actionTone,
  formatSignalAction,
  normalizePositionSide,
  positionSideFromAction,
} from "../signalDirection";

describe("signalDirection", () => {
  it("maps equity and spread actions to LONG/SHORT", () => {
    expect(positionSideFromAction("BUY")).toBe("LONG");
    expect(positionSideFromAction("SELL")).toBe("SHORT");
    expect(positionSideFromAction("BUY_SPREAD")).toBe("LONG");
    expect(positionSideFromAction("SELL_SPREAD")).toBe("SHORT");
  });

  it("normalizes held position direction", () => {
    expect(normalizePositionSide("BUY")).toBe("LONG");
    expect(normalizePositionSide("SHORT")).toBe("SHORT");
  });

  it("formats actions for display", () => {
    expect(formatSignalAction("BUY_SPREAD")).toBe("BUY SPREAD");
    expect(formatSignalAction("SELL_SPREAD")).toBe("SELL SPREAD");
  });

  it("tones long/short actions", () => {
    expect(actionTone("LONG")).toContain("green");
    expect(actionTone("SHORT")).toContain("red");
  });
});
