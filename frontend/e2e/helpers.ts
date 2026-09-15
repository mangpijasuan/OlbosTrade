/**
 * Shared measurement helpers. Not a spec file — Playwright's default testMatch
 * only collects *.spec.ts, so this is never run as a test.
 */

import { expect, type Page } from "@playwright/test";

/**
 * Assert no part of the page sits outside the window it is displayed in.
 *
 * Both edges are checked, and the left one is not redundant: in a
 * left-to-right document, content pushed past the left edge does NOT extend
 * scrollWidth — the browser simply clips it and offers no way to scroll there.
 * So a `scrollWidth === clientWidth` assertion alone reports a clean page while
 * an element sits permanently off-screen. Right-edge overflow is the visible
 * sideways scroll; left-edge overflow is content that silently cannot be
 * reached. This guard is named for both, so it checks both.
 *
 * On failure it names the elements responsible, because "the page scrolls
 * sideways" on its own sends you hunting through a whole stylesheet.
 *
 * An element is only reported if nothing above it clips horizontally. That
 * distinction carries real weight here: the ticker strip is an intentionally
 * over-wide marquee inside an `overflow: hidden` container, and the mobile nav
 * drawer parks itself at translateX(-100%) when closed. Both are far outside
 * the viewport by design. Reporting them would point every failure at the
 * wrong element — a mistake worth encoding once rather than re-making at each
 * call site.
 */
export async function expectNoHorizontalOverflow(page: Page, width: number) {
  const { scrollWidth, clientWidth, past, before } = await page.evaluate(() => {
    const doc = document.documentElement;
    const limit = doc.clientWidth;

    // Stops at <body>, and that boundary is the whole point. index.css sets
    // `body { overflow-x: hidden }` as a global safety net, so walking all the
    // way up finds a clipping ancestor for EVERY element on the page — which
    // silently emptied both diagnostic lists and made the left-edge assertion
    // below unfailable. Only a LOCAL clip (a marquee's container, the nav
    // drawer's own wrapper) means "off-screen by design"; the page-level net
    // means nothing of the sort.
    const clipsHorizontally = (el: Element): boolean => {
      for (let n: Element | null = el.parentElement; n && n !== document.body; n = n.parentElement) {
        if (getComputedStyle(n).overflowX !== "visible") return true;
      }
      return false;
    };

    const describe = (el: Element, box: DOMRect) => {
      const cls = String(el.className || "").trim().slice(0, 40);
      return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""} ` +
             `left=${Math.round(box.left)} right=${Math.round(box.right)}`;
    };

    const past: string[] = [];    // beyond the right edge
    const before: string[] = [];  // beyond the left edge
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const box = el.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      // Fixed elements are positioned against the viewport and do not extend
      // the scrollable area.
      if (getComputedStyle(el).position === "fixed") continue;
      if (clipsHorizontally(el)) continue;
      if (box.right > limit + 0.5) past.push(describe(el, box));
      if (box.left < -0.5) before.push(describe(el, box));
    }

    return {
      scrollWidth: doc.scrollWidth,
      clientWidth: limit,
      past: past.slice(0, 5),
      before: before.slice(0, 5),
    };
  });

  expect(
    scrollWidth,
    `the page scrolls sideways at ${width}px: document is ${scrollWidth}px wide ` +
    `against a ${clientWidth}px viewport.\n` +
    (past.length
      ? `Elements past the right edge:\n  ${past.join("\n  ")}`
      : `No unclipped element extends past the right edge — suspect a margin, ` +
        `a negative offset, or a transform.`)
  ).toBeLessThanOrEqual(clientWidth);

  expect(
    before,
    `content sits past the LEFT edge at ${width}px, where it cannot be scrolled ` +
    `to and is simply unreachable (this does not show up in scrollWidth):\n  ` +
    before.join("\n  ")
  ).toEqual([]);
}

/** A signed-in operator, for the surfaces that only exist when auth is on. */
export const SIGNED_IN = {
  auth_enabled: true,
  authenticated: true,
  user: { id: "11111111-1111-4111-8111-111111111111", email: "operator@example.test", tier: "elite" },
};

/** The default single-operator install: no login, terminal renders straight through. */
export const AUTH_DISABLED = { auth_enabled: false, authenticated: false, user: null };

/**
 * Stub the backend so the terminal renders without a server.
 *
 * ORDER MATTERS AND IS THE REVERSE OF WHAT IT LOOKS LIKE. Playwright evaluates
 * route handlers in reverse registration order — the most recently registered
 * wins — so the catch-all must be registered FIRST for the specific handler
 * after it to take precedence. Registered the other way round, the catch-all
 * swallows /api/auth/status and returns `{}`; the terminal still renders,
 * because `auth_enabled: undefined` is falsy and reads as auth-disabled, so
 * every test passes while the payload below is never once used. That is the
 * exact shape of a test that looks like coverage and is not.
 *
 * Everything other than auth returns an empty object: the panels' own
 * ErrorBoundaries catch the resulting shape mismatches, which keeps the run
 * deterministic and leaves the SHELL — nav, ticker, status bar, bottom nav —
 * laid out exactly as in production. The shell is what these tests measure;
 * panel contents are vitest's job.
 */
export async function stubBackend(page: Page, authStatus: unknown = AUTH_DISABLED) {
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" })
  );
  await page.route("**/api/auth/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(authStatus),
    })
  );
}
