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

  it("does not render the tier chip for a free account", async () => {
    // "free" next to someone's name is noise, not information.
    stubStatus({ auth_enabled: true, authenticated: true, user: { ...USER, tier: "free" } });
    render(<AuthProvider><UserMenu /></AuthProvider>);

    const chip = await screen.findByRole("button", { name: /trader@example\.com/i });
    expect(chip.textContent).toBe("trader");
  });
});
