/**
 * The hook itself, for the cases a browser test cannot reach.
 *
 * e2e/tab-urls.spec.ts drives real tabs in a real browser and is the primary
 * guard. Two things are out of its reach:
 *
 *  - The legacy Trade Desk's unmapped tabs. They only exist when the
 *    trade_desk_v2 flag is OFF, and it ships ON, so a browser test for them
 *    skips on every CI run — a test that never executes is not a guard.
 *  - A tab named after an Object.prototype member. It cannot be clicked,
 *    because no such tab is rendered; it can only be reached by calling the
 *    hook, which is what makes it worth pinning here.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { useTabRoute } from "../useTabRoute";

const nav = vi.fn();
vi.mock("../../components/TerminalNavContext", () => ({
  useTerminalNav: () => nav,
}));

beforeEach(() => nav.mockReset());

/** Renders the hook and exposes its setter, so tests can drive it directly. */
function Harness<T extends string>({
  initialTab,
  keys,
  onReady,
}: {
  initialTab: T;
  keys: Readonly<Partial<Record<T, string>>>;
  onReady: (change: (next: T) => void) => void;
}) {
  const [tab, changeTab] = useTabRoute(initialTab, keys);
  onReady(changeTab);
  return <div data-testid="tab">{tab}</div>;
}

function mount<T extends string>(
  initialTab: T,
  keys: Readonly<Partial<Record<T, string>>>,
) {
  let change!: (next: T) => void;
  const view = render(
    <Harness initialTab={initialTab} keys={keys} onReady={(c) => { change = c; }} />,
  );
  return {
    tab: () => screen.getByTestId("tab").textContent,
    change: (next: T) => act(() => change(next)),
    view,
  };
}

type DeskTab = "overview" | "positions";
const DESK: Readonly<Partial<Record<DeskTab, string>>> = {
  overview: "trade:overview",
  positions: "trade:positions",
};

describe("useTabRoute", () => {
  it("navigates to the page key for the tab", () => {
    const h = mount<DeskTab>("overview", DESK);
    h.change("positions");
    expect(h.tab()).toBe("positions");
    expect(nav).toHaveBeenCalledTimes(1);
    expect(nav).toHaveBeenCalledWith("trade:positions");
  });

  it("switches an unmapped tab without navigating", () => {
    // "mode" (Trading style) and "manual" (Manual Trade) have no page key in
    // App.tsx. Refusing to open the tab because it has no URL would be the
    // worse trade — so it opens, and the URL keeps naming the desk.
    const h = mount<"overview" | "mode">("overview", DESK as never);
    h.change("mode");
    expect(h.tab(), "an unmapped tab must still switch").toBe("mode");
    expect(nav, "an unmapped tab must not invent a URL").not.toHaveBeenCalled();
  });

  it("navigates only for a string page key, never an inherited member", () => {
    // tabToPageKey is a plain object literal, so `tabToPageKey["constructor"]`
    // is a function rather than undefined, and an unguarded `if (key)
    // onNav(key)` would hand that function to the router.
    //
    // The hook carries two guards for this, and mutation testing showed that
    // either one ALONE satisfies this test: hasOwnProperty at the lookup, and
    // `typeof key === "string"` at the call. So this does not pin a particular
    // guard — it pins the behaviour, and fails when both are gone. That is the
    // right level for it: how the hook refuses is the hook's business.
    const h = mount<"overview" | "constructor" | "toString">("overview", DESK as never);

    h.change("constructor");
    expect(nav).not.toHaveBeenCalled();
    h.change("toString");
    expect(nav).not.toHaveBeenCalled();

    // And it still behaves like any other unmapped tab.
    expect(h.tab()).toBe("toString");
  });

  it("follows the URL when initialTab changes without a remount", () => {
    // Two tabs of one hub are two registry keys, and React usually remounts on
    // the swap — but not always. If it re-renders instead, the tab must follow
    // the prop, or Back would move the URL and leave the old tab selected.
    let change!: (next: DeskTab) => void;
    const { rerender } = render(
      <Harness<DeskTab> initialTab="overview" keys={DESK} onReady={(c) => { change = c; }} />,
    );
    expect(screen.getByTestId("tab").textContent).toBe("overview");
    void change;

    rerender(
      <Harness<DeskTab> initialTab="positions" keys={DESK} onReady={(c) => { change = c; }} />,
    );
    expect(screen.getByTestId("tab").textContent).toBe("positions");
  });
});
