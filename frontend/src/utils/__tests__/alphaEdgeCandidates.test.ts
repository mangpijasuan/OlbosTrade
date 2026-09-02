import { describe, it, expect } from "vitest";
import {
  buildAlphaEdgeCandidates,
  type EquitySignalRow,
  type PositionRow,
} from "../alphaEdgeCandidates";

const now = new Date().toISOString();

describe("buildAlphaEdgeCandidates", () => {
  it("puts held positions first and dedupes scan tickers", () => {
    const positions: PositionRow[] = [
      { symbol: "NVDA", asset_type: "equity", tracked: true },
      { symbol: "SPY", asset_type: "options" },
    ];
    const signals: EquitySignalRow[] = [
      { ticker: "NVDA", action: "BUY", confidence: 0.9, generated_at: now },
      { ticker: "AMD", action: "BUY", confidence: 0.85, generated_at: now },
      { ticker: "KDP", action: "SELL", confidence: 0.8, generated_at: now },
    ];
    const list = buildAlphaEdgeCandidates(positions, signals, "equity");
    expect(list.map(c => c.ticker)).toEqual(["NVDA", "AMD", "KDP"]);
    expect(list[0].source).toBe("held");
    expect(list.filter(c => c.source === "scan").map(c => c.ticker)).toEqual(["AMD", "KDP"]);
  });

  it("filters positions and signals by asset type", () => {
    const positions: PositionRow[] = [
      { symbol: "AAPL", asset_type: "equity" },
      { symbol: "QQQ", asset_type: "options" },
    ];
    const equity = buildAlphaEdgeCandidates(positions, [], "equity");
    const options = buildAlphaEdgeCandidates(positions, [], "options");
    expect(equity.map(c => c.ticker)).toEqual(["AAPL"]);
    expect(options.map(c => c.ticker)).toEqual(["QQQ"]);
  });

  it("ignores non-actionable equity signals", () => {
    const signals: EquitySignalRow[] = [
      { ticker: "XYZ", action: "HOLD", confidence: 0.5, generated_at: now },
      { ticker: "ABC", action: "BUY", confidence: 0.7, generated_at: now, earnings_gated: true },
    ];
    const list = buildAlphaEdgeCandidates([], signals, "equity");
    expect(list).toEqual([]);
  });
});
