/**
 * Boot states, login, sign-out, and expiry — driven through the real
 * AuthProvider with only fetch stubbed.
 *
 * The thing most worth pinning is the auth-disabled path. AUTH_ENABLED ships
 * false, so on every existing install the gate must be invisible: no login
 * screen, no identity chrome, no extra hop. A regression there breaks working
 * deployments rather than merely annoying new ones.
 */

import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AuthGate from "../AuthGate";
import { AuthProvider } from "../AuthContext";
import { uninstallSessionExpiryInterceptor } from "../sessionExpiry";

const TERMINAL = "terminal-content";

function Terminal() {
  return <div data-testid={TERMINAL}>trading terminal</div>;
}

function renderGate() {
  return render(
    <AuthProvider>
      <AuthGate><Terminal /></AuthGate>
    </AuthProvider>
  );
}

/** Routes each path to a canned response; unlisted paths 401 like the real API. */
function routeFetch(routes: Record<string, () => Response>) {
  const spy = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const path = new URL(url, window.location.origin).pathname;
    const handler = routes[path];
    if (handler) return handler();
    return new Response(JSON.stringify({ detail: "Authentication required" }), { status: 401 });
  });
  window.fetch = spy as unknown as typeof window.fetch;
  return spy;
}

/** Set a controlled input's value the way React's onChange expects. */
function fillIn(el: HTMLElement, value: string) {
  fireEvent.change(el, { target: { value } });
}

const json = (body: unknown, status = 200) =>
  () => new Response(JSON.stringify(body), { status });

const STATUS_DISABLED = { auth_enabled: false, authenticated: false, user: null };
const STATUS_ANON = { auth_enabled: true, authenticated: false, user: null };
const USER = { id: "u1", email: "trader@example.com", tier: "pro" };
const STATUS_SIGNED_IN = { auth_enabled: true, authenticated: true, user: USER };

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { uninstallSessionExpiryInterceptor(); });

describe("auth disabled — the default, and every existing install", () => {
  it("renders the terminal with no login screen", async () => {
    routeFetch({ "/api/auth/status": json(STATUS_DISABLED) });
    renderGate();

    await screen.findByTestId(TERMINAL);
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });
});

describe("auth enabled", () => {
  it("shows the login screen when nobody is signed in", async () => {
    routeFetch({ "/api/auth/status": json(STATUS_ANON) });
    renderGate();

    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByTestId(TERMINAL)).not.toBeInTheDocument();
  });

  it("renders the terminal for an existing session without asking again", async () => {
    routeFetch({ "/api/auth/status": json(STATUS_SIGNED_IN) });
    renderGate();

    await screen.findByTestId(TERMINAL);
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });

  it("signs in and reveals the terminal", async () => {
    routeFetch({
      "/api/auth/status": json(STATUS_ANON),
      "/api/auth/login": json({ user: USER }),
    });
    renderGate();

    fillIn(await screen.findByLabelText(/email/i), "trader@example.com");
    fillIn(screen.getByLabelText(/password/i), "correct horse battery staple");
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByTestId(TERMINAL)).toBeInTheDocument();
  });

  it("shows the server's generic message on bad credentials and stays put", async () => {
    routeFetch({
      "/api/auth/status": json(STATUS_ANON),
      "/api/auth/login": json({ detail: "Invalid email or password" }, 401),
    });
    renderGate();

    fillIn(await screen.findByLabelText(/email/i), "trader@example.com");
    fillIn(screen.getByLabelText(/password/i), "wrong");
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid email or password/i);
    expect(screen.queryByTestId(TERMINAL)).not.toBeInTheDocument();
  });

  it("does not say whether the account exists", async () => {
    // The backend returns one message for every credential failure so a wrong
    // password and a missing account are indistinguishable. The UI must not
    // reintroduce the oracle by being more helpful.
    routeFetch({
      "/api/auth/status": json(STATUS_ANON),
      "/api/auth/login": json({ detail: "Invalid email or password" }, 401),
    });
    renderGate();

    fillIn(await screen.findByLabelText(/email/i), "nobody@example.com");
    fillIn(screen.getByLabelText(/password/i), "whatever");
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toMatch(/not found|no such|unknown user|does not exist/i);
  });

  it("surfaces rate limiting as its own message", async () => {
    routeFetch({
      "/api/auth/status": json(STATUS_ANON),
      "/api/auth/login": json({ detail: "Too many" }, 429),
    });
    renderGate();

    fillIn(await screen.findByLabelText(/email/i), "trader@example.com");
    fillIn(screen.getByLabelText(/password/i), "wrong");
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
  });

  it("clears the password but keeps the email after a failure", async () => {
    routeFetch({
      "/api/auth/status": json(STATUS_ANON),
      "/api/auth/login": json({ detail: "Invalid email or password" }, 401),
    });
    renderGate();

    const email = await screen.findByLabelText(/email/i) as HTMLInputElement;
    const password = screen.getByLabelText(/password/i) as HTMLInputElement;
    fillIn(email, "trader@example.com");
    fillIn(password, "wrong");
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await screen.findByRole("alert");
    expect(email.value).toBe("trader@example.com");
    expect(password.value).toBe("");
  });

  it("never puts the password in the URL", async () => {
    // A GET form would put credentials in the query string, where they land in
    // access logs and browser history.
    const spy = routeFetch({
      "/api/auth/status": json(STATUS_ANON),
      "/api/auth/login": json({ user: USER }),
    });
    renderGate();

    fillIn(await screen.findByLabelText(/email/i), "trader@example.com");
    fillIn(screen.getByLabelText(/password/i), "hunter2-hunter2");
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await screen.findByTestId(TERMINAL);
    for (const [input] of spy.mock.calls) {
      const url = typeof input === "string" ? input : String(input);
      expect(url).not.toContain("hunter2");
    }
  });

  it("sends credentials so the session cookie comes back", async () => {
    const spy = routeFetch({
      "/api/auth/status": json(STATUS_ANON),
      "/api/auth/login": json({ user: USER }),
    });
    renderGate();

    fillIn(await screen.findByLabelText(/email/i), "trader@example.com");
    fillIn(screen.getByLabelText(/password/i), "correct horse battery staple");
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await screen.findByTestId(TERMINAL);
    const loginCall = spy.mock.calls.find(([i]) => String(i).includes("/api/auth/login"));
    expect(loginCall?.[1]).toMatchObject({ credentials: "same-origin" });
  });
});

describe("a session that ends mid-use", () => {
  it("returns to login and says why", async () => {
    routeFetch({
      "/api/auth/status": json(STATUS_SIGNED_IN),
      // Anything else 401s — standing in for a session expiring behind an
      // ordinary background poll.
    });
    renderGate();
    await screen.findByTestId(TERMINAL);

    await fetch("/api/portfolio/positions");   // a poll, from anywhere in the app

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/session ended/i);
    });
    expect(screen.queryByTestId(TERMINAL)).not.toBeInTheDocument();
  });
});

describe("server unreachable at boot", () => {
  it("offers a retry instead of guessing", async () => {
    // Neither "logged out" nor "auth is off" is knowable here, and picking
    // either is a lie. The one honest move is to say so.
    window.fetch = vi.fn(async () => { throw new TypeError("network down"); }) as never;
    renderGate();

    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByTestId(TERMINAL)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it("recovers when the server comes back", async () => {
    let up = false;
    window.fetch = vi.fn(async () => {
      if (!up) throw new TypeError("network down");
      return new Response(JSON.stringify(STATUS_DISABLED), { status: 200 });
    }) as never;
    renderGate();

    up = true;
    fireEvent.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByTestId(TERMINAL)).toBeInTheDocument();
  });
});
