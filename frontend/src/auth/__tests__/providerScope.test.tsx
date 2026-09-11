/**
 * The auth provider must not boot on the public landing page.
 *
 * It was first mounted above the whole route switch, so its effect called
 * /api/auth/status and installed the fetch interceptor on every visit to the
 * marketing page — which has no authenticated work to do. Raised in review:
 * a wasted request on the most-visited page of a default auth-disabled install.
 *
 * This mirrors the routing in index.tsx rather than importing it, because that
 * module calls ReactDOM.createRoot against a #root element on import.
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import AuthGate from "../AuthGate";
import { AuthProvider } from "../AuthContext";
import { uninstallSessionExpiryInterceptor } from "../sessionExpiry";

function routes() {
  return (
    <Routes>
      <Route path="/" element={<div data-testid="landing">public landing</div>} />
      <Route
        path="/terminal/*"
        element={
          <AuthProvider>
            <AuthGate><div data-testid="terminal">terminal</div></AuthGate>
          </AuthProvider>
        }
      />
    </Routes>
  );
}

function stubFetch() {
  const spy = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(
    JSON.stringify({ auth_enabled: false, authenticated: false, user: null }),
    { status: 200 }
  ));
  window.fetch = spy as unknown as typeof window.fetch;
  return spy;
}

afterEach(() => {
  uninstallSessionExpiryInterceptor();
  vi.restoreAllMocks();
});

describe("provider scope", () => {
  it("does not call /api/auth/status on the landing page", async () => {
    const spy = stubFetch();
    render(<MemoryRouter initialEntries={["/"]}>{routes()}</MemoryRouter>);

    await screen.findByTestId("landing");
    const authCalls = spy.mock.calls.filter(([i]) => String(i).includes("/api/auth/"));
    expect(authCalls).toHaveLength(0);
  });

  it("does not install the fetch interceptor on the landing page", async () => {
    const spy = stubFetch();
    render(<MemoryRouter initialEntries={["/"]}>{routes()}</MemoryRouter>);

    await screen.findByTestId("landing");
    expect(window.fetch).toBe(spy);      // untouched
  });

  it("does boot auth on the terminal route", async () => {
    const spy = stubFetch();
    render(<MemoryRouter initialEntries={["/terminal/dashboard"]}>{routes()}</MemoryRouter>);

    await screen.findByTestId("terminal");
    await waitFor(() => {
      const authCalls = spy.mock.calls.filter(([i]) => String(i).includes("/api/auth/status"));
      expect(authCalls.length).toBeGreaterThan(0);
    });
  });
});
