/**
 * The public landing page must fit every phone, and the nav row must stay
 * fitted no matter what the CTA says.
 *
 * This is the test that could not be written in vitest. The bug it guards
 * shipped twice: the nav row was a fixed 373.9px wide at EVERY viewport
 * because .landing-nav-actions is flex-shrink: 0 and the CTA label is
 * unbreakable text. It cleared a 375px screen by 1.1px, overhung 360px by 14px
 * and 320px by 54px — and the second-widest phone viewport in the world
 * scrolled sideways on the marketing page.
 *
 * The first fix was measured on one screen (390px) and passed. That is the
 * failure mode the width table below exists to prevent: a fix verified at the
 * width the author happened to open.
 */

import { test, expect } from "@playwright/test";
import { expectNoHorizontalOverflow } from "./helpers";

/**
 * Real device widths, not round numbers. 360 is the most common Android
 * viewport worldwide; 375 covers the iPhone SE/mini line; 320 is the narrow
 * floor (iPhone 5/SE 1st gen, and any browser at minimum zoom-out).
 */
const PHONE_WIDTHS = [430, 414, 393, 390, 375, 360, 344, 320];

test.describe("landing page fits every phone", () => {
  for (const width of PHONE_WIDTHS) {
    test(`no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto("/");
      await page.waitForSelector(".landing-nav-cta");
      await expectNoHorizontalOverflow(page, width);
    });
  }
});

test.describe("nav CTA label", () => {
  test("phones get the compact label, desktop keeps the full one", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 844 });
    await page.goto("/");
    const cta = page.locator(".landing-nav-cta");

    // useInnerText matters here and is the whole point of the assertion: both
    // labels are in the DOM and CSS hides one, so textContent is always
    // "Start Paper TradingStart Free" and a default toHaveText would pass no
    // matter which label is actually on screen.
    await expect(cta).toHaveText("Start Free", { useInnerText: true });

    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(cta).toHaveText("Start Paper Trading", { useInnerText: true });
  });

  test("announces exactly one label to a screen reader", async ({ page }) => {
    // Both labels are in the DOM and CSS hides one. display: none content is
    // excluded from the accessible name, so this must not read as the two
    // labels concatenated.
    await page.setViewportSize({ width: 360, height: 844 });
    await page.goto("/");
    await expect(page.locator(".landing-nav-cta")).toHaveAccessibleName("Start Free");

    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(page.locator(".landing-nav-cta")).toHaveAccessibleName("Start Paper Trading");
  });
});

test.describe("the shrink guard, not just the shorter label", () => {
  /**
   * The compact label alone would be a fix that works until someone lengthens
   * the copy. The load-bearing part is that the row can actually shrink.
   *
   * This forces the full desktop label back on at the narrowest supported
   * width — the exact thing the guard exists to survive. Mutation-checked when
   * written: removing `.landing-nav-actions { flex-shrink: 1 }` takes the
   * document to 362px against a 320px viewport and fails this test.
   */
  const FORCE_LONG_LABEL = `
    @media (max-width: 600px) {
      .landing-nav-cta .landing-cta-full { display: inline !important; }
      .landing-nav-cta .landing-cta-compact { display: none !important; }
    }
  `;

  test("a long CTA label cannot push the document wider than the viewport", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    await page.goto("/");
    await page.waitForSelector(".landing-nav-cta");
    await page.addStyleTag({ content: FORCE_LONG_LABEL });
    await expectNoHorizontalOverflow(page, 320);
  });

  test("a long CTA label ellipsizes rather than being hard-clipped", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    await page.goto("/");
    await page.waitForSelector(".landing-nav-cta");
    await page.addStyleTag({ content: FORCE_LONG_LABEL });

    const label = page.locator(".landing-nav-cta .landing-cta-full");
    const { rendered, natural } = await label.evaluate((el) => ({
      rendered: Math.ceil(el.getBoundingClientRect().width),
      natural: el.scrollWidth,
    }));

    // The span must shrink below its own text width. It can, because its
    // overflow: hidden makes the flex automatic minimum size resolve to 0
    // (css-flexbox-1 §4.5) — which is what lets text-overflow produce an
    // ellipsis instead of the text simply being cut off by the parent.
    expect(
      rendered,
      `the label did not shrink (rendered ${rendered}px, text ${natural}px), ` +
      `so text-overflow cannot ellipsize it`
    ).toBeLessThan(natural);
    await expect(label).toHaveCSS("text-overflow", "ellipsis");
  });
});
