import { defineConfig, devices } from "@playwright/test";

/**
 * Browser-level tests, for the things jsdom structurally cannot see.
 *
 * vitest runs under jsdom, which does NO layout: every element measures 0x0
 * and scrollWidth is always 0. Two real defects in this repo lived in exactly
 * that blind spot — a nav row that overflowed the viewport on a 360px phone,
 * and `var(--x)55` colours the browser drops silently so a border simply is
 * not painted. Neither is visible to a unit test, a type-check, or a linter.
 *
 * So this suite is deliberately narrow: it is for assertions that need a real
 * layout and a real cascade. Anything that can be checked in vitest belongs in
 * vitest, which is faster and does not need a browser.
 */

const PORT = 4173;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,

  /**
   * No retries, on purpose.
   *
   * These are deterministic measurements against a static build — there is no
   * network, no clock, and no backend in the loop. A retry here would not be
   * routing around infrastructure noise, it would be hiding a real intermittent
   * layout bug, which is the one class of bug this suite exists to catch.
   */
  retries: 0,

  reporter: [["list"], ["html", { open: "never" }]],

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
  },

  /**
   * Chromium only. Adding webkit would be the genuinely valuable second
   * browser for this bug class, since Safari is where flexbox and viewport-unit
   * behaviour diverges — but it roughly doubles the browser download and CI
   * time, so it is a deliberate follow-up rather than a default.
   */
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],

  /**
   * Tests run against the PRODUCTION build, not the dev server. The bugs this
   * suite guards are cascade- and bundling-sensitive, and the dev server serves
   * CSS differently from the built asset — testing the dev server would leave
   * the artifact that actually ships unverified.
   */
  webServer: {
    command: `npm run build && npm run preview -- --port ${PORT} --strictPort --host 127.0.0.1`,
    url: BASE_URL,
    // Safe in CI (a fresh runner has nothing on this port) and convenient
    // locally, where it avoids a rebuild between runs.
    reuseExistingServer: true,
    timeout: 180_000,
  },
});
