/**
 * The close gate's own behaviour.
 *
 * The bug this pins: close_position() has accepted put and call for a while,
 * routing them through close_options_trade(). The Trade Desk's gate was still
 * equity-only, so an options row rendered a "close via broker" placeholder and
 * no button. Reported as "hold to close is not functioning" — correctly, from
 * the outside, since an absent button and a dead button look the same.
 *
 * These tests alone would NOT have caught that: the helper can be perfectly
 * consistent with itself and still disagree with the backend. The test that
 * catches it compares both allowlists, and lives in the backend suite —
 * backend/tests/test_close_gate_matches_the_route.py — because reading across
 * the boundary is already the idiom there and needs no node types here.
 */

import { describe, it, expect } from "vitest";
import {
  CLOSEABLE_SPREAD_TYPES,
  canClosePosition,
  isCloseableType,
  isEquityPosition,
} from "../closeablePosition";

describe("canClosePosition", () => {
  it("offers a button for equity positions with a trade id", () => {
    expect(canClosePosition({ spread_type: "equity_long", id: "t1" })).toBe(true);
    expect(canClosePosition({ spread_type: "equity_short", id: "t1" })).toBe(true);
  });

  it("offers a button for put and call positions — the case that was missing", () => {
    expect(canClosePosition({ spread_type: "put", id: "t1" })).toBe(true);
    expect(canClosePosition({ spread_type: "call", id: "t1" })).toBe(true);
  });

  it("withholds it without a trade id, whatever the type", () => {
    for (const t of CLOSEABLE_SPREAD_TYPES) {
      expect(canClosePosition({ spread_type: t, id: null })).toBe(false);
      expect(canClosePosition({ spread_type: t })).toBe(false);
    }
  });

  it("withholds it for a type the backend would reject", () => {
    // close_position() 400s on anything outside its allowlist, so rendering a
    // button here would promise an action that cannot succeed.
    expect(canClosePosition({ spread_type: "iron_condor", id: "t1" })).toBe(false);
    expect(canClosePosition({ spread_type: "", id: "t1" })).toBe(false);
    expect(canClosePosition({ id: "t1" })).toBe(false);
  });

  it("is case-insensitive — the backend lowercases before matching", () => {
    expect(canClosePosition({ spread_type: "PUT", id: "t1" })).toBe(true);
    expect(canClosePosition({ spread_type: "Equity_Long", id: "t1" })).toBe(true);
  });
});

describe("isEquityPosition", () => {
  it("separates equities from options, which close by different broker paths", () => {
    expect(isEquityPosition({ spread_type: "equity_long" })).toBe(true);
    expect(isEquityPosition({ spread_type: "put" })).toBe(false);
    // Still closeable — just not an equity.
    expect(isCloseableType({ spread_type: "put" })).toBe(true);
  });
});
