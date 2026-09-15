import { describe, expect, it } from "vitest";
import {
  DEFAULT_PAGE,
  TERMINAL_BASE,
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

  it("decodes a percent-encoded path without throwing on a malformed one", () => {
    expect(pathToPageKey("/terminal/markets%2Fchart".replace("%2F", "/"))).toBe("markets:chart");
    // A lone % is not a valid escape — decodeURIComponent throws on it, and a
    // pasted URL must not be able to take the whole terminal down.
    expect(() => pathToPageKey("/terminal/mark%ets")).not.toThrow();
  });

  it("returns an unknown key as-is rather than silently rewriting it", () => {
    // App renders UnknownPage for this and the URL stays put. Rewriting to the
    // dashboard is exactly the silent-wrong-page behaviour being fixed.
    expect(pathToPageKey("/terminal/does/not/exist")).toBe("does:not:exist");
  });
});

describe("round trip", () => {
  const KEYS = [
    "dashboard", "journal", "risk", "settings", "paper",
    "markets:chart", "markets:sector-rotation", "trade:overview",
    "strat:alpha-edge", "strat:signal-history", "options:chain",
    "risk:heat", "lab:scenario", "system:broker",
  ];

  it("every real page key survives url -> key -> url", () => {
    for (const key of KEYS) {
      expect(pathToPageKey(pageKeyToUrl(key)), `round trip failed for ${key}`).toBe(key);
    }
  });
});
