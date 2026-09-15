/**
 * A terminal URL must open the page it names.
 *
 * Until `terminalRoutes.ts` existed, App held its page in useState("dashboard")
 * and never read the pathname, so every /terminal/* URL rendered the Dashboard
 * while the address bar claimed otherwise. Reload, bookmark, share and Back
 * were all silently wrong — and "silently" is the point: nothing failed, you
 * just got a different page than the one you asked for.
 *
 * These are browser tests rather than unit tests because the thing under test
 * IS the browser's own machinery: a real address bar, a real reload, and a real
 * session history. jsdom has none of those.
 */

import { test, expect, type Page } from "@playwright/test";
import { stubBackend } from "./helpers";

/**
 * Each URL and the status-bar label the shell should show for it.
 *
 * The label is the assertion rather than page content, and deliberately: the
 * backend is stubbed, so some pages render their ErrorBoundary instead of real
 * content (ChartWorkstation does). Asserting on content would then fail for a
 * reason that has nothing to do with routing. The status bar is derived from
 * the app's own `activePage`, which is now derived from the URL — so if
 * routing regressed to "everything is the dashboard", every row below reads
 * COMMAND CENTER and every row fails. That is exactly the bug being guarded.
 */
const PAGES = [
  { url: "/terminal/journal",        label: "JOURNAL" },
  { url: "/terminal/risk",           label: "PORTFOLIO & RISK" },
  { url: "/terminal/markets/chart",  label: "MARKETS · CHART" },
  { url: "/terminal/trade/overview", label: "TRADE DESK · COMMAND OVERVIEW" },
];

async function open(page: Page, url: string, width = 1280) {
  await stubBackend(page);
  await page.setViewportSize({ width, height: 900 });
  await page.goto(url);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(800);
}

/**
 * What the shell says is open.
 *
 * NOT document.body: the first few hundred characters of every terminal page
 * are the same ticker strip, so a marker check against the body passes or
 * fails on chrome that is identical across all pages — it looks like a page
 * assertion and is not one.
 */
async function statusLabel(page: Page): Promise<string> {
  return page.locator(".instrument-status span").first().innerText();
}

/** The text of the page body, for the cases where the page itself renders. */
async function pageText(page: Page): Promise<string> {
  return page.evaluate(() => {
    const main = document.querySelector("main");
    return (main instanceof HTMLElement ? main.innerText : "") || "";
  });
}

test.describe("a terminal URL opens the page it names", () => {
  for (const { url, label } of PAGES) {
    test(`${url} opens its own page, not the dashboard`, async ({ page }) => {
      await open(page, url);
      expect(
        await statusLabel(page),
        `${url} did not open its own page — this is the deep-linking bug, ` +
        `where every /terminal/* URL rendered the Dashboard`
      ).toBe(label);
      expect(page.url()).toContain(url);
    });
  }

  test("a bare /terminal opens the dashboard", async ({ page }) => {
    // Every CTA on the marketing page links here.
    await open(page, "/terminal");
    expect(await statusLabel(page)).toBe("COMMAND CENTER");
  });

  test("an unknown page says so instead of quietly showing another one", async ({ page }) => {
    await open(page, "/terminal/not/a/real/page");
    expect(await pageText(page)).toMatch(/page unavailable/i);
    // The URL must stay put: a silent rewrite to the dashboard is the exact
    // behaviour this change removes.
    expect(page.url()).toContain("/terminal/not/a/real/page");
  });
});

test.describe("the URL tracks in-app navigation", () => {
  test("clicking a nav item changes the address bar, and reload stays put", async ({ page }) => {
    // Phone width: the drawer toggle only carries an accessible name in the
    // mobile header.
    await open(page, "/terminal/dashboard", 390);

    await page.getByRole("button", { name: /toggle navigation/i }).click();
    await page.getByText(/^Journal$/i).first().click();
    await page.waitForTimeout(500);

    expect(page.url(), "navigating did not update the URL").toContain("/terminal/journal");

    // The reload is the assertion that matters: before the fix this landed on
    // the Dashboard no matter what the address bar said.
    await page.reload();
    await page.waitForTimeout(800);
    expect(page.url()).toContain("/terminal/journal");
    expect(await statusLabel(page)).toBe("JOURNAL");
  });

  test("the browser Back button returns to the previous page", async ({ page }) => {
    // Phone width: the drawer toggle only carries an accessible name in the
    // mobile header.
    await open(page, "/terminal/dashboard", 390);

    await page.getByRole("button", { name: /toggle navigation/i }).click();
    await page.getByText(/^Journal$/i).first().click();
    await page.waitForTimeout(500);
    expect(page.url()).toContain("/terminal/journal");

    await page.goBack();
    await page.waitForTimeout(600);
    expect(page.url(), "Back did not return to the previous terminal page").toContain("/terminal/dashboard");

    await page.goForward();
    await page.waitForTimeout(600);
    expect(page.url()).toContain("/terminal/journal");
  });
});
