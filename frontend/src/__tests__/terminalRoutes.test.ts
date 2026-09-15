import { describe, expect, it } from "vitest";
import {
  DEFAULT_PAGE,
  PAGE_ALIASES,
  TERMINAL_BASE,
  canonicalPageKey,
  pageKeyToPath,
  pageKeyToUrl,
  pathToPageKey,
} from "../terminalRoutes";

describe("page key -> url", () => {
  it("turns the colon into a path separator", () => {
    expect(pageKeyToPath("markets:chart")).toBe("markets/chart");
    expect(pageKeyToUrl("markets:chart")).toBe("/terminal/markets/chart");
  });

  it("leaves a bare key as a single segment", () => {
    expect(pageKeyToUrl("dashboard")).toBe("/terminal/dashboard");
  });

  it("handles a key with a hyphen in the sub-part", () => {
    // These exist in BASE_PAGES and would break a naive split.
    expect(pageKeyToUrl("markets:sector-rotation")).toBe("/terminal/markets/sector-rotation");
    expect(pageKeyToUrl("strat:alpha-edge")).toBe("/terminal/strat/alpha-edge");
  });

  it("falls back to the base url for an empty key", () => {
    expect(pageKeyToUrl("")).toBe(TERMINAL_BASE);
  });
});

describe("url -> page key", () => {
  it("joins path segments back into a key", () => {
    expect(pathToPageKey("/terminal/markets/chart")).toBe("markets:chart");
    expect(pathToPageKey("/terminal/trade/overview")).toBe("trade:overview");
  });

  it("reads a bare page", () => {
    expect(pathToPageKey("/terminal/journal")).toBe("journal");
  });

  it("opens the dashboard for a bare /terminal", () => {
    // Every CTA on the marketing page links here. It must open the terminal,
    // not an error page.
    expect(pathToPageKey("/terminal")).toBe(DEFAULT_PAGE);
    expect(pathToPageKey("/terminal/")).toBe(DEFAULT_PAGE);
    expect(pathToPageKey("")).toBe(DEFAULT_PAGE);
    expect(pathToPageKey(undefined)).toBe(DEFAULT_PAGE);
    expect(pathToPageKey(null)).toBe(DEFAULT_PAGE);
  });

  it("accepts the router splat as well as a full pathname", () => {
    expect(pathToPageKey("markets/chart")).toBe("markets:chart");
  });

  it("ignores a query string and hash", () => {
    expect(pathToPageKey("/terminal/risk/heat?tab=2")).toBe("risk:heat");
    expect(pathToPageKey("/terminal/risk/heat#top")).toBe("risk:heat");
  });

  it("tolerates duplicate and trailing slashes", () => {
    expect(pathToPageKey("/terminal//markets///chart/")).toBe("markets:chart");
  });

  it("normalises case", () => {
    expect(pathToPageKey("/terminal/Markets/Chart")).toBe("markets:chart");
  });

  it("resolves a percent-encoded separator to the same page", () => {
    // The encoded input goes in AS-IS. An earlier version of this test did
    // `"...markets%2Fchart".replace("%2F", "/")` before calling, so it passed
    // "/terminal/markets/chart" and never exercised decoding at all — green
    // against both the bug and the fix. Which is how the bug shipped: decoding
    // happened after the split, leaving the separator trapped in one segment
    // and producing the non-key "markets/chart".
    expect(pathToPageKey("/terminal/markets%2Fchart")).toBe("markets:chart");
    expect(pathToPageKey("/terminal/markets%2fchart")).toBe("markets:chart");
  });

  it("does not throw on a malformed percent-escape", () => {
    // A lone % is not valid encoding — decodeURIComponent throws on it, and a
    // pasted URL must not be able to take the whole terminal down.
    expect(() => pathToPageKey("/terminal/mark%ets")).not.toThrow();
    expect(pathToPageKey("/terminal/mark%ets")).toBe("mark%ets");
  });

  it("strips the base path case-insensitively", () => {
    // React Router matches /terminal/* case-insensitively, so /TERMINAL/risk
    // mounts the terminal. A case-sensitive strip left the base in the key
    // ("terminal:risk") and rendered UnknownPage for a URL the router had
    // already accepted.
    expect(pathToPageKey("/TERMINAL/risk")).toBe("risk");
    expect(pathToPageKey("/Terminal/Markets/Chart")).toBe("markets:chart");
  });

  it("only strips the base on a path boundary", () => {
    // A path that merely starts with the same letters is not the base.
    expect(pathToPageKey("/terminalish/risk")).toBe("terminalish:risk");
  });

  it("returns an unknown key as-is rather than silently rewriting it", () => {
    // App renders UnknownPage for this and the URL stays put. Rewriting to the
    // dashboard is exactly the silent-wrong-page behaviour being fixed.
    expect(pathToPageKey("/terminal/does/not/exist")).toBe("does:not:exist");
  });
});

/**
 * The round trip has to cover EVERY page key, not a sample.
 *
 * A hand-written list of 14 was wrong here: App.tsx registers 36 base keys
 * plus the feature-flagged Trade Desk set, so most nav destinations
 * (markets:watchlists, lab:intel, trade:settings) had no coverage at all, and
 * a key added later would silently have none either.
 *
 * So the keys are read out of App.tsx itself. Same approach as
 * landingNavOverflow.test.ts: the source is the fixture, so the test cannot
 * drift from the registry it is meant to guard.
 */
// @ts-expect-error - node:fs is untyped here; vitest runs in Node, so it resolves at runtime.
import { readFileSync } from "node:fs";

// Assembled by string, NOT `new URL(..., import.meta.url)` — Vite rewrites
// that exact pattern into an asset URL and readFileSync then fails.
const TEST_DIR = import.meta.url.replace(/^file:\/\//, "").replace(/\/[^/]*$/, "");
const APP_SOURCE: string = readFileSync(`${TEST_DIR}/../App.tsx`, "utf8");

/** Pull the property keys out of every page-registry object literal. */
function registeredPageKeys(source: string): string[] {
  const keys = new Set<string>();

  // Quoted keys: "markets:chart": () => ...
  for (const m of source.matchAll(/"([a-z0-9:-]+)"\s*:/g)) keys.add(m[1]);

  // Bare keys inside the registries only: `  dashboard: Dashboard,`.
  // Scoped to the registry blocks so style objects elsewhere in the file
  // (height:, display:) cannot leak in.
  const blocks = [
    /const BASE_PAGES[^{]*\{([\s\S]*?)\n\};/,
    /function tradeDeskPages[^{]*\{([\s\S]*?)\n\}\n/,
  ];
  for (const re of blocks) {
    const block = source.match(re)?.[1] ?? "";
    for (const m of block.matchAll(/^\s{2,6}([a-z][a-z0-9]*)\s*:/gm)) keys.add(m[1]);
  }
  return [...keys];
}

describe("round trip", () => {
  const KEYS = registeredPageKeys(APP_SOURCE);

  it("finds the real registry rather than an empty list", () => {
    // A zero-length list would make the loop below pass vacuously — which is
    // the failure mode this whole file keeps running into.
    expect(KEYS.length).toBeGreaterThan(30);
    expect(KEYS).toContain("dashboard");
    expect(KEYS).toContain("markets:watchlists");
    expect(KEYS).toContain("trade:overview");
  });

  it("every registered page key survives url -> key -> url", () => {
    for (const key of KEYS) {
      expect(pathToPageKey(pageKeyToUrl(key)), `round trip failed for ${key}`).toBe(key);
    }
  });

  it("no registered key collides with another once converted", () => {
    // Two keys mapping to one URL would make a deep link ambiguous.
    const urls = KEYS.map(pageKeyToUrl);
    expect(new Set(urls).size, "two page keys produce the same URL").toBe(urls.length);
  });
});

/**
 * PAGE_ALIASES must not fall behind the registry.
 *
 * An alias is a bare key whose page default tab equals the tab a `group:sub`
 * key pins — both spellings then render the identical screen, and the
 * duplicate-history check has to treat them as one page.
 *
 * Rather than trust a hand-written map, derive the set from App.tsx plus each
 * page's own default and compare. A new alias added later fails here with the
 * pair named, instead of quietly reintroducing a dead Back press.
 */
describe("page aliases stay in step with the registry", () => {
  /**
   * Restricted to BASE_PAGES on purpose.
   *
   * tradeDeskPages() registers the same keys twice, once per branch of the
   * trade_desk_v2 flag, so "what does this key render" has two answers there
   * and an alias claim cannot be settled from the registry alone. BASE_PAGES
   * has exactly one answer per key, which is what makes this derivation sound.
   */
  const BASE = APP_SOURCE.match(/const BASE_PAGES[^{]*\{([\s\S]*?)\n\};/)?.[1] ?? "";

  /** `"risk:heat": () => <RiskCenter initialTab="monitor" />` */
  const PINNED = [...BASE.matchAll(
    /"([a-z0-9:-]+)"\s*:\s*\(\)\s*=>\s*<(\w+)\s+initialTab="([^"]+)"/g
  )].map((m) => ({ key: m[1], component: m[2], tab: m[3] }));

  /** `risk: RiskCenter,` — a bare key taking the component's own default. */
  const BARE = [...BASE.matchAll(/^\s{2}([a-z][a-z0-9]*)\s*:\s*(\w+),/gm)]
    .map((m) => ({ key: m[1], component: m[2] }));

  function readPageSource(component: string): string | null {
    const rel = APP_SOURCE.match(
      new RegExp(`import\\s+${component}\\s+from\\s+"([^"]+)"`)
    )?.[1];
    if (!rel) return null;
    try {
      return readFileSync(`${TEST_DIR}/../${rel.replace(/^\.\//, "")}.tsx`, "utf8");
    } catch {
      return null;
    }
  }

  /** `export default function RiskCenter({ initialTab = "monitor" }` */
  function defaultTabOf(component: string): string | null {
    return readPageSource(component)?.match(/initialTab\s*=\s*"([^"]+)"/)?.[1] ?? null;
  }

  /** bare key -> the pinned key that renders the same component AND tab. */
  function twinOf(bare: { key: string; component: string }): string | null {
    const dflt = defaultTabOf(bare.component);
    if (dflt === null) return null;
    return PINNED.find((p) => p.component === bare.component && p.tab === dflt)?.key ?? null;
  }

  it("parses the registry rather than matching nothing", () => {
    // Empty lists would make every assertion below vacuous.
    expect(BASE.length, "BASE_PAGES block not found in App.tsx").toBeGreaterThan(200);
    expect(PINNED.length, "no pinned-tab entries parsed").toBeGreaterThan(5);
    expect(BARE.length, "no bare keys parsed").toBeGreaterThan(5);
  });

  it("every declared alias really is two spellings of one view", () => {
    for (const [from, to] of Object.entries(PAGE_ALIASES)) {
      const bare = BARE.find((b) => b.key === from);
      expect(bare, `PAGE_ALIASES declares "${from}", which BASE_PAGES does not register`).toBeTruthy();
      expect(
        twinOf(bare!),
        `"${from}" and "${to}" do not render the same component and tab — ` +
        `remove this from PAGE_ALIASES`
      ).toBe(to);
    }
  });

  it("no alias is missing from the map", () => {
    const missing = BARE
      .map((b) => ({ from: b.key, to: twinOf(b) }))
      .filter((a) => a.to !== null && canonicalPageKey(a.from) !== a.to)
      .map((a) => `${a.from} -> ${a.to}`);

    expect(
      missing,
      "these keys render the same view under two spellings but are not in " +
      "PAGE_ALIASES, so clicking the active nav item from the bare URL still " +
      "pushes a history entry that Back cannot meaningfully undo:\n  " +
      missing.join("\n  ")
    ).toEqual([]);
  });

  it("canonicalPageKey maps an alias and leaves everything else alone", () => {
    expect(canonicalPageKey("risk")).toBe("risk:heat");
    expect(canonicalPageKey("risk:heat")).toBe("risk:heat");
    expect(canonicalPageKey("journal")).toBe("journal");
    // Must not resolve inherited names — the same prototype hazard App guards.
    // This returned the constructor FUNCTION until it used hasOwnProperty.
    expect(canonicalPageKey("constructor")).toBe("constructor");
    expect(canonicalPageKey("__proto__")).toBe("__proto__");
  });
});
