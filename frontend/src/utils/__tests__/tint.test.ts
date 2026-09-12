/**
 * These assertions encode what a real browser does, because jsdom does not.
 *
 * jsdom accepts `var(--amber)55` without complaint, which is precisely why the
 * broken form survived review and testing. The expected values below were
 * measured in Chromium with `--amber: #f59e0b`:
 *
 *     var(--amber)55  → border-style "none", background rgba(0,0,0,0)   dropped
 *     #f59e0b55       → rgba(245,158,11,0.333)                          fine
 *     color-mix(…)    → color(srgb 0.96 0.62 0.04 / 0.33)               fine
 */

import { describe, expect, it } from "vitest";

import { TINT_BORDER, TINT_FILL, tint } from "../tint";

describe("tint", () => {
  it("produces a colour function rather than a concatenated string", () => {
    // The whole point: never emit `var(--x)NN`, which browsers drop.
    const out = tint("var(--amber)", 0.4);
    expect(out).toBe("color-mix(in srgb, var(--amber) 40%, transparent)");
    expect(out).not.toMatch(/var\(--\w[\w-]*\)[0-9a-fA-F]{2}/);
  });

  it("works for literal hex too", () => {
    // The palette is mid-migration between tokens and literals; one helper has
    // to handle both or call sites go back to guessing.
    expect(tint("#f59e0b", 0.08)).toBe("color-mix(in srgb, #f59e0b 8%, transparent)");
  });

  it("clamps out-of-range alpha instead of emitting invalid CSS", () => {
    // A percentage outside 0–100 makes the declaration invalid, which is the
    // same silent-disappearance failure this helper exists to prevent.
    expect(tint("#fff", -1)).toContain("0%");
    expect(tint("#fff", 5)).toContain("100%");
  });

  it("rounds to whole percent", () => {
    expect(tint("#fff", 0.333)).toContain("33%");
  });

  it("names the two common weights", () => {
    expect(TINT_BORDER).toBeGreaterThan(TINT_FILL);
    expect(TINT_FILL).toBeGreaterThan(0);
    expect(TINT_BORDER).toBeLessThanOrEqual(1);
  });
});
