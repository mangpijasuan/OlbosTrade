/**
 * ResearchCenter's tab actually reaches the URL.
 *
 * This test exists because the ones around it did not prove that. Research is
 * the one hub the browser suite cannot drive — its panels read a nested field
 * off the e2e stub's flat `{}` and throw, so the ErrorBoundary renders and no
 * tab bar mounts — and the table test next door checks the ROUTE TABLES, not
 * the wiring that uses them. Caught in review by exactly the right question:
 * revert this page to plain useState and every other test still passes.
 *
 * So this renders the real component with its panels mocked, clicks a real
 * tab, and asserts the navigation. Mocking the panels is what makes that
 * possible without a fixture for five separate response schemas — the claim
 * under test is about the tab bar and the hook, and neither needs the panels
 * to be real.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ResearchCenter, { TABS, TAB_PAGE_KEYS } from "../ResearchCenter";

const nav = vi.fn();
vi.mock("../../components/TerminalNavContext", () => ({
  useTerminalNav: () => nav,
}));

// The panels are the reason this page cannot be reached in the browser suite.
// They are not what is under test.
vi.mock("../ResearchLab", () => ({ default: () => <div>lab panel</div> }));
vi.mock("../Research", () => ({ default: () => <div>market panel</div> }));
vi.mock("../Intel", () => ({ default: () => <div>intel panel</div> }));
vi.mock("../research/ScenarioLab", () => ({ default: () => <div>scenario panel</div> }));
vi.mock("../research/MLModels", () => ({ default: () => <div>models panel</div> }));

beforeEach(() => nav.mockReset());

describe("ResearchCenter tab -> URL", () => {
  it("renders its tab bar (otherwise everything below is vacuous)", () => {
    render(<ResearchCenter />);
    expect(screen.getAllByRole("tab").length).toBe(TABS.length);
  });

  /**
   * Every tab, derived from the page's own TABS — a hard-coded list here could
   * drift from the component and quietly stop covering a tab.
   */
  it.each(TABS.map((t) => [t.label, t.key] as const))(
    "clicking %s navigates to its page key",
    (label, key) => {
      // Start on a DIFFERENT tab, or TabBar treats the click as a no-op and
      // the assertion below would be testing nothing.
      render(<ResearchCenter initialTab={key === "scenario" ? "lab" : "scenario"} />);

      fireEvent.click(screen.getByRole("tab", { name: label }));

      const expected = TAB_PAGE_KEYS[key as keyof typeof TAB_PAGE_KEYS];
      expect(
        nav,
        `clicking "${label}" did not navigate — the tab is only in component ` +
        `state, so reload and Back cannot restore it`
      ).toHaveBeenCalledWith(expected);
    },
  );

  it("selecting the tab already open does not navigate", () => {
    // The hook navigates on every changeTab; App.handleNav is what collapses a
    // no-op. TabBar not firing onChange for the active tab is the cheaper
    // guard, and this pins it: a regression here would put a history entry
    // behind every click on the current tab.
    render(<ResearchCenter initialTab="market" />);
    expect(screen.getByRole("tab", { name: "Market & Regime" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(nav).not.toHaveBeenCalled();
  });
});
