/**
 * Shared measurement helpers. Not a spec file — Playwright's default testMatch
 * only collects *.spec.ts, so this is never run as a test.
 */

import { expect, type Page } from "@playwright/test";

/**
 * Assert the document is not wider than the window it is displayed in.
 *
 * On failure it names the elements actually responsible, because "the page
 * scrolls sideways" on its own sends you hunting through a whole stylesheet.
 *
 * An element is only reported if nothing above it clips horizontally. That
 * distinction matters here: the terminal's ticker strip is an intentionally
 * over-wide marquee inside an `overflow: hidden` container, so it is far wider
 * than the screen by design and contributes nothing to document scroll width.
 * Reporting it would point every terminal failure at the wrong element — a
 * mistake worth encoding once rather than re-making at each call site.
 */
export async function expectNoHorizontalOverflow(page: Page, width: number) {
  const { scrollWidth, clientWidth, offenders } = await page.evaluate(() => {
    const doc = document.documentElement;
    const limit = doc.clientWidth;

    const clipsHorizontally = (el: Element): boolean => {
      for (let n: Element | null = el.parentElement; n; n = n.parentElement) {
        const overflowX = getComputedStyle(n).overflowX;
        if (overflowX !== "visible") return true;
      }
      return false;
    };

    const offenders: string[] = [];
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const box = el.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      if (box.right <= limit + 0.5) continue;
      // Fixed elements are positioned against the viewport and do not extend
      // the scrollable area.
      if (getComputedStyle(el).position === "fixed") continue;
      if (clipsHorizontally(el)) continue;
      const cls = String(el.className || "").trim().slice(0, 40);
      offenders.push(
        `${el.tagName.toLowerCase()}${cls ? "." + cls : ""} right=${Math.round(box.right)}`
      );
    }

    return { scrollWidth: doc.scrollWidth, clientWidth: limit, offenders: offenders.slice(0, 5) };
  });

  expect(
    scrollWidth,
    `the page scrolls sideways at ${width}px: document is ${scrollWidth}px wide ` +
    `against a ${clientWidth}px viewport.\n` +
    (offenders.length
      ? `Elements extending past the viewport:\n  ${offenders.join("\n  ")}`
      : `No unclipped element extends past the viewport — suspect a margin, ` +
        `a negative offset, or a transform.`)
  ).toBeLessThanOrEqual(clientWidth);
}

/**
 * Stub the backend so the terminal renders without a server.
 *
 * /api/auth/status gets a real payload rather than `{}` — it is the one call
 * that gates whether the terminal mounts at all, and this shape is the default
 * single-operator install (AUTH_ENABLED false), which renders the terminal
 * straight through. Everything else returns an empty object: the panels' own
 * ErrorBoundaries catch the resulting shape mismatches, which keeps the run
 * deterministic and leaves the SHELL — nav, ticker, status bar, bottom nav —
 * laid out exactly as it is in production. The shell is what these tests
 * measure; panel contents are vitest's job.
 */
export async function stubBackend(page: Page) {
  await page.route("**/api/auth/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ auth_enabled: false, authenticated: false, user: null }),
    })
  );
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" })
  );
}
