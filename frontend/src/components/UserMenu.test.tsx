/**
 * The status-bar identity chip.
 *
 * Mostly about when it must render NOTHING. It sits inside TerminalLayout, so
 * every way it can misbehave takes the whole shell with it — and it first
 * shipped throwing outside an AuthProvider, which broke 14 existing layout
 * tests before this file existed.
 */

import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import UserMenu from "./UserMenu";
import { AuthProvider } from "../auth/AuthContext";
import { uninstallSessionExpiryInterceptor } from "../auth/sessionExpiry";

const USER = { id: "u1", email: "trader@example.com", tier: "pro" };

function stubStatus(body: unknown) {
  window.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), window.location.origin).pathname;
    if (path === "/api/auth/status") {
      return new Response(JSON.stringify(body), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  }) as never;
}

afterEach(() => {
  uninstallSessionExpiryInterceptor();
  vi.restoreAllMocks();
});

describe("without an AuthProvider", () => {
  it("renders nothing instead of throwing", () => {
    // TerminalLayout is rendered standalone by other tests and by any future
    // reuse. Optional chrome must degrade, not explode.
    const { container } = render(<UserMenu />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("with auth disabled", () => {
  it("renders nothing — there is no identity on a single-operator install", async () => {
    stubStatus({ auth_enabled: false, authenticated: false, user: null });
    const { container } = render(<AuthProvider><UserMenu /></AuthProvider>);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

describe("signed in", () => {
  it("shows the local part of the address and the tier", async () => {
    stubStatus({ auth_enabled: true, authenticated: true, user: USER });
    render(<AuthProvider><UserMenu /></AuthProvider>);

    const chip = await screen.findByRole("button", { name: /trader@example\.com/i });
    expect(chip).toHaveTextContent("trader");
    expect(chip).toHaveTextContent(/pro/i);
  });

  it("reveals the full address and a sign-out control when opened", async () => {
    stubStatus({ auth_enabled: true, authenticated: true, user: USER });
    render(<AuthProvider><UserMenu /></AuthProvider>);

    fireEvent.click(await screen.findByRole("button", { name: /trader@example\.com/i }));
    expect(screen.getByRole("menu")).toHaveTextContent("trader@example.com");
    expect(screen.getByRole("menuitem", { name: /sign out/i })).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    stubStatus({ auth_enabled: true, authenticated: true, user: USER });
    render(<AuthProvider><UserMenu /></AuthProvider>);

    fireEvent.click(await screen.findByRole("button", { name: /trader@example\.com/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("hides the chip after signing out", async () => {
    stubStatus({ auth_enabled: true, authenticated: true, user: USER });
    const { container } = render(<AuthProvider><UserMenu /></AuthProvider>);

    fireEvent.click(await screen.findByRole("button", { name: /trader@example\.com/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /sign out/i }));

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders the menu outside the status bar so it is not clipped", async () => {
    /**
     * On mobile .instrument-status is a horizontal scroller (overflow-x: auto,
     * overflow-y: hidden) and this menu opens above it, outside that box — so
     * the ancestor clipped it completely and Sign out became unreachable on a
     * phone. Verified in Chromium at 390px before the fix: the menu painted
     * nothing at all.
     *
     * The fix portals it to <body>, so the test asserts the structural
     * property that makes clipping impossible rather than a pixel measurement
     * jsdom cannot produce.
     */
    stubStatus({ auth_enabled: true, authenticated: true, user: USER });
    const { container } = render(
      <div className="instrument-status" style={{ overflowX: "auto", overflowY: "hidden" }}>
        <AuthProvider><UserMenu /></AuthProvider>
      </div>
    );

    fireEvent.click(await screen.findByRole("button", { name: /trader@example\.com/i }));

    const menu = screen.getByRole("menu");
    expect(container.contains(menu)).toBe(false);      // escaped the scroller
    expect(document.body.contains(menu)).toBe(true);
    expect(menu).toHaveStyle({ position: "fixed" });   // not clipped by an ancestor
  });

  it("still closes on a click outside, now that the menu is portalled", async () => {
    // The menu is no longer a DOM descendant of the wrapper, so naive
    // click-away logic would treat a click INSIDE it as a click-away and close
    // it before Sign out ran.
    stubStatus({ auth_enabled: true, authenticated: true, user: USER });
    render(<AuthProvider><UserMenu /></AuthProvider>);

    fireEvent.click(await screen.findByRole("button", { name: /trader@example\.com/i }));
    fireEvent.mouseDown(screen.getByRole("menu"));
    expect(screen.getByRole("menu")).toBeInTheDocument();   // a click inside keeps it open

    fireEvent.mouseDown(document.body);
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });

  it("does not render the tier chip for a free account", async () => {
    // "free" next to someone's name is noise, not information.
    stubStatus({ auth_enabled: true, authenticated: true, user: { ...USER, tier: "free" } });
    render(<AuthProvider><UserMenu /></AuthProvider>);

    const chip = await screen.findByRole("button", { name: /trader@example\.com/i });
    expect(chip.textContent).toBe("trader");
  });
});
