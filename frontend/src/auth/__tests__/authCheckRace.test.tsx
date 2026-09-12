/**
 * Only the newest status check may write state.
 *
 * The provider used to guard with a single `alive` boolean, which cannot tell
 * "the provider unmounted" from "a newer check started". Two ways that bit:
 *
 *   StrictMode — React 18 mounts, unmounts and remounts in development. The
 *   cleanup set alive=false and the remount set it straight back to true, so
 *   the first mount's in-flight response found alive===true and applied.
 *
 *   retry() — exposed on the context, so a person can click it twice. With two
 *   requests in flight, whichever RESOLVES last wins, which may be the older
 *   one. On a recovering server a failure then lands after a success and puts
 *   the operator back on the error screen.
 *
 * The shape that matters is a STALE response carrying a DIFFERENT outcome
 * arriving LAST. A first attempt at these tests released responses that either
 * agreed with each other or arrived in order, and passed against the broken
 * implementation — so every test here is checked against it.
 */

import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AuthGate from "../AuthGate";
import { AuthProvider, useAuth } from "../AuthContext";
import { uninstallSessionExpiryInterceptor } from "../sessionExpiry";

const TERMINAL = "terminal-content";
const USER = { id: "u1", email: "trader@example.com", tier: "pro" };
const SIGNED_IN = { auth_enabled: true, authenticated: true, user: USER };
const ANON = { auth_enabled: true, authenticated: false, user: null };

/** Triggers an extra check without needing the error screen's Retry button. */
function Recheck() {
  const { retry } = useAuth();
  return <button onClick={retry}>recheck</button>;
}

/** A fetch stub whose responses are released by hand, in any order. */
function deferredFetch() {
  const pending: Array<{ resolve: (r: Response) => void; reject: (e: unknown) => void }> = [];
  window.fetch = vi.fn(() => new Promise<Response>((resolve, reject) => {
    pending.push({ resolve, reject });
  })) as never;
  return {
    count: () => pending.length,
    succeed: (i: number, body: unknown) =>
      pending[i].resolve(new Response(JSON.stringify(body), { status: 200 })),
    fail: (i: number) => pending[i].reject(new TypeError("network down")),
  };
}

function renderApp(strict = false) {
  const tree = (
    <AuthProvider>
      <AuthGate><div data-testid={TERMINAL}>terminal</div></AuthGate>
      <Recheck />
    </AuthProvider>
  );
  return render(strict ? <React.StrictMode>{tree}</React.StrictMode> : tree);
}

afterEach(() => {
  uninstallSessionExpiryInterceptor();
  vi.restoreAllMocks();
});

describe("concurrent status checks", () => {
  it("ignores a stale FAILURE that lands after a newer success", async () => {
    const f = deferredFetch();
    renderApp();
    await waitFor(() => expect(f.count()).toBe(1));     // boot check, in flight

    fireEvent.click(screen.getByText("recheck"));       // second check starts
    await waitFor(() => expect(f.count()).toBe(2));

    f.succeed(1, SIGNED_IN);                            // newer resolves first
    expect(await screen.findByTestId(TERMINAL)).toBeInTheDocument();

    f.fail(0);                                          // stale failure, last
    await new Promise(r => setTimeout(r, 20));

    // Under the old guard this threw the operator onto the error screen.
    expect(screen.getByTestId(TERMINAL)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("ignores a stale SIGNED-IN that lands after a newer anonymous", async () => {
    // The dangerous direction: a stale success must not resurrect a session the
    // newer check says is gone.
    const f = deferredFetch();
    renderApp();
    await waitFor(() => expect(f.count()).toBe(1));

    fireEvent.click(screen.getByText("recheck"));
    await waitFor(() => expect(f.count()).toBe(2));

    f.succeed(1, ANON);                                 // newer: signed out
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();

    f.succeed(0, SIGNED_IN);                            // stale: still signed in
    await new Promise(r => setTimeout(r, 20));

    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByTestId(TERMINAL)).not.toBeInTheDocument();
  });

  it("ignores the first mount's response after a StrictMode remount", async () => {
    const f = deferredFetch();
    renderApp(true);

    // StrictMode double-invokes the effect, so two checks are in flight.
    await waitFor(() => expect(f.count()).toBe(2));

    f.succeed(1, ANON);                                 // the live mount's
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();

    f.succeed(0, SIGNED_IN);                            // the discarded mount's
    await new Promise(r => setTimeout(r, 20));

    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByTestId(TERMINAL)).not.toBeInTheDocument();
  });
});
