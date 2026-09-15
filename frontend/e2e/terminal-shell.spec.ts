/**
 * The terminal shell must fit a phone on every route.
 *
 * Scope is deliberate: this measures the SHELL — header, ticker strip, nav
 * drawer, status bar, bottom nav — not panel contents. The backend is stubbed,
 * so panels render their ErrorBoundary fallback rather than real data. That is
 * the point: it keeps the run deterministic and hermetic while still exercising
 * the parts where a horizontal overflow would actually come from, which are all
 * in the chrome.
 *
 * The drawer test is here because the bug it guards was invisible to jsdom and
 * to a static read of the CSS: the mobile nav overlay was clipped out of
 * existence by an ancestor's `overflow-y: hidden`, so sign-out was unreachable
 * on a phone. Nothing but a real browser paints that.
 */

import { test, expect } from "@playwright/test";
import { expectNoHorizontalOverflow, stubBackend } from "./helpers";

const ROUTES = [
  "/terminal/dashboard",
  "/terminal/markets",
  "/terminal/tradedesk",
  "/terminal/positions",
  "/terminal/risk",
  "/terminal/journal",
  "/terminal/performance",
  "/terminal/strategies",
];

const PHONE = { width: 390, height: 844 };
const NARROW = { width: 320, height: 844 };

test.describe("terminal shell fits a phone", () => {
  for (const route of ROUTES) {
    test(`no horizontal overflow on ${route}`, async ({ page }) => {
      await stubBackend(page);
      await page.setViewportSize(PHONE);
      await page.goto(route);
      // The bottom nav is the last piece of the shell to mount, so its presence
      // means the shell is laid out rather than mid-render.
      await page.waitForSelector("nav, footer, [class*=bottom]", { timeout: 15_000 });
      await expectNoHorizontalOverflow(page, PHONE.width);
    });
  }

  test(`no horizontal overflow at ${NARROW.width}px`, async ({ page }) => {
    await stubBackend(page);
    await page.setViewportSize(NARROW);
    await page.goto("/terminal/dashboard");
    await page.waitForSelector("nav, footer, [class*=bottom]", { timeout: 15_000 });
    await expectNoHorizontalOverflow(page, NARROW.width);
  });
});

/**
 * How far the drawer has slid in, measured as the right edge of one of its
 * rows.
 *
 * Open/closed CANNOT be asserted with toBeVisible() here, and getting that
 * wrong is the easy mistake: on mobile the sidebar is always mounted and is
 * merely pushed off with `transform: translateX(-100%)`. A translated element
 * still has a non-empty box and `visibility: visible`, so Playwright considers
 * it visible whether the drawer is open or shut — an assertion on visibility
 * passes in both states and tests nothing.
 *
 * Position is the honest signal: fully open puts the row on screen, fully
 * closed puts its right edge at or past the left viewport edge.
 */
async function drawerRowRightEdge(page: import("@playwright/test").Page): Promise<number> {
  const box = await page.getByText(/^Journal$/i).first().boundingBox();
  return box ? box.x + box.width : NaN;
}

test.describe("mobile nav drawer", () => {
  /**
   * Regression guard for a bug that no unit test could have caught: the user
   * menu inside this overlay was once clipped to nothing by an ancestor's
   * `overflow-y: hidden`, which made sign-out impossible on a phone. The
   * element was in the DOM with a non-zero box and was simply never painted.
   *
   * Clicking is what proves it. Playwright hit-tests the click point before
   * dispatching, so a row that is clipped, covered, or painted behind the page
   * fails here rather than silently "passing" a visibility check.
   */
  test("opens, its rows are actually clickable, and it closes on tap-away", async ({ page }) => {
    await stubBackend(page);
    await page.setViewportSize(PHONE);
    await page.goto("/terminal/dashboard");
    await page.waitForSelector("text=Journal");

    // Starts off-screen to the left.
    await expect.poll(() => drawerRowRightEdge(page)).toBeLessThanOrEqual(0);

    // Addressed by its accessible name, not by DOM order. `button.first()`
    // would silently bind to whatever button happens to come first, so adding
    // any control above the header would leave this test green while
    // exercising the wrong element.
    const burger = page.getByRole("button", { name: /toggle navigation/i });
    await burger.click();
    await expect
      .poll(() => drawerRowRightEdge(page), { timeout: 5_000 })
      .toBeGreaterThan(0);

    // Selecting a destination closes the overlay — otherwise it covers the page
    // the user just asked for. The click itself is the hit-test.
    await page.getByText(/^Journal$/i).first().click();
    await expect
      .poll(() => drawerRowRightEdge(page), { timeout: 5_000 })
      .toBeLessThanOrEqual(0);

    // Tapping the backdrop must also close it. Without one the drawer covers
    // the page with no obvious way out.
    await burger.click();
    await expect
      .poll(() => drawerRowRightEdge(page), { timeout: 5_000 })
      .toBeGreaterThan(0);
    await page.mouse.click(PHONE.width - 30, 400);
    await expect
      .poll(() => drawerRowRightEdge(page), { timeout: 5_000 })
      .toBeLessThanOrEqual(0);
  });
});
