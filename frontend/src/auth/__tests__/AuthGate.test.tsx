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
import { AuthProvider, useAuth } from "../AuthContext";
import { uninstallSessionExpiryInterceptor } from "../sessionExpiry";

const TERMINAL = "terminal-content";

function Terminal() {
  return <div data-testid={TERMINAL}>trading terminal</div>;
}

/** Stands in for UserMenu's sign-out, without pulling in its layout. */
function SignOutButton() {
  const { signOut, logoutWarning } = useAuth();
  return (
    <>
      <button onClick={() => { void signOut(); }}>sign out</button>
      {logoutWarning && <div role="status">{logoutWarning}</div>}
    </>
  );
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

describe("logout when the server cannot be reached", () => {
  /**
   * The dangerous case. If the request never lands, NOTHING happened: the
   * session row is live and the cookie is still in the browser. The cookie is
   * httpOnly, so script cannot remove it — this app cannot sign anyone out
   * without the server.
   *
   * Showing "signed out" here would be a lie with consequences. Someone on a
   * borrowed machine walks away believing they are signed out while a valid
   * session sits in the browser, and the next page load puts them back into a
   * trading terminal.
   */
  function renderSignedInWithFailingLogout() {
    window.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), window.location.origin).pathname;
      if (path === "/api/auth/status") {
        return new Response(JSON.stringify(STATUS_SIGNED_IN), { status: 200 });
      }
      if (path === "/api/auth/logout") throw new TypeError("network down");
      return new Response("{}", { status: 200 });
    }) as never;

    return render(
      <AuthProvider>
        <AuthGate><Terminal /></AuthGate>
        <SignOutButton />
      </AuthProvider>
    );
  }

  it("keeps the user signed in rather than claiming otherwise", async () => {
    renderSignedInWithFailingLogout();
    await screen.findByTestId(TERMINAL);

    fireEvent.click(screen.getByText("sign out"));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/still signed in/i);
    });
    // The terminal is still showing, because the session really is still live.
    expect(screen.getByTestId(TERMINAL)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument();
  });

  it("never suggests closing the browser as a way to be safe", async () => {
    /**
     * Raised in review, and worse than the bug this change fixes. The session
     * cookie is set with max_age = AUTH_SESSION_HOURS * 3600, so it is
     * PERSISTENT: closing and reopening the browser keeps it, and the next
     * person to open the app on that machine walks into the terminal.
     *
     * A false reassurance with a specific action attached is worse than no
     * advice, so this pins the wording rather than trusting it to stay right.
     */
    renderSignedInWithFailingLogout();
    await screen.findByTestId(TERMINAL);

    fireEvent.click(screen.getByText("sign out"));

    const notice = await screen.findByRole("status");
    expect(notice.textContent).toMatch(/will NOT sign you out/i);
    // Must not read as "close the browser and you're fine".
    expect(notice.textContent).not.toMatch(/close the browser if/i);
    expect(notice.textContent).not.toMatch(/or close the browser\b(?!.*NOT)/i);
  });

  it("says the server could not be reached, not that revocation failed", async () => {
    // Two different failures with two different consequences. Conflating them
    // tells someone their cookie is gone when it is not.
    renderSignedInWithFailingLogout();
    await screen.findByTestId(TERMINAL);

    fireEvent.click(screen.getByText("sign out"));

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(/could not reach the server/i);
    expect(notice.textContent).not.toMatch(/signed out here/i);
  });

  it.each([
    ["502 from the proxy", 502, "<html>Bad Gateway</html>"],
    ["504 from the proxy", 504, "<html>Gateway Timeout</html>"],
    ["500 raised before the route ran", 500, '{"detail":"Internal Server Error"}'],
    ["503 that is not ours", 503, "<html>Service Unavailable</html>"],
    ["an empty body", 200, ""],
  ])("keeps the user signed in on %s", async (_label, status, body) => {
    /**
     * Raised in review. The cookie is only gone if the logout ROUTE ran, since
     * delete_cookie lives there — and a status code does not prove that. nginx
     * answers 502/504 when the backend is down, and a 500 can be raised before
     * the route reaches its cookie clearing.
     *
     * Note the 503 case: that status is the route's own "could not revoke"
     * signal, but a proxy can produce it too. Only the route's JSON envelope
     * counts as proof it ran.
     */
    window.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), window.location.origin).pathname;
      if (path === "/api/auth/status") {
        return new Response(JSON.stringify(STATUS_SIGNED_IN), { status: 200 });
      }
      if (path === "/api/auth/logout") return new Response(body, { status });
      return new Response("{}", { status: 200 });
    }) as never;

    render(
      <AuthProvider>
        <AuthGate><Terminal /></AuthGate>
        <SignOutButton />
      </AuthProvider>
    );
    await screen.findByTestId(TERMINAL);

    fireEvent.click(screen.getByText("sign out"));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/still signed in/i);
    });
    expect(screen.getByTestId(TERMINAL)).toBeInTheDocument();
  });

  it("accepts the route's own 503 envelope as cookie-cleared", async () => {
    // The other half: fail-safe must not become fail-always. The route's real
    // 503 does clear the cookie, and that has to keep working.
    window.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), window.location.origin).pathname;
      if (path === "/api/auth/status") {
        return new Response(JSON.stringify(STATUS_SIGNED_IN), { status: 200 });
      }
      if (path === "/api/auth/logout") {
        return new Response(JSON.stringify({ ok: false, detail: "…" }), { status: 503 });
      }
      return new Response("{}", { status: 200 });
    }) as never;

    render(
      <AuthProvider>
        <AuthGate><Terminal /></AuthGate>
        <SignOutButton />
      </AuthProvider>
    );
    await screen.findByTestId(TERMINAL);

    fireEvent.click(screen.getByText("sign out"));

    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    // The login screen and the sign-out stand-in both render the warning here,
    // so assert across all of them rather than assuming one.
    const notices = screen.getAllByRole("status").map(n => n.textContent).join(" ");
    expect(notices).toMatch(/could not revoke/i);
    expect(notices).not.toMatch(/still signed in/i);

    // "Sign out again when it recovers" was not actionable: the phase is
    // anonymous by now, the login screen has no sign-out control, and a later
    // sign-out would revoke a NEW session. Raised in review. The message must
    // point at something that actually works — deactivating the account, which
    // require_session rechecks per request.
    expect(notices).not.toMatch(/sign out again/i);
    expect(notices).toMatch(/deactivate the account/i);
  });

  it("still signs out once the server comes back", async () => {
    let up = false;
    window.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), window.location.origin).pathname;
      if (path === "/api/auth/status") {
        return new Response(JSON.stringify(STATUS_SIGNED_IN), { status: 200 });
      }
      if (path === "/api/auth/logout") {
        if (!up) throw new TypeError("network down");
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response("{}", { status: 200 });
    }) as never;

    render(
      <AuthProvider>
        <AuthGate><Terminal /></AuthGate>
        <SignOutButton />
      </AuthProvider>
    );
    await screen.findByTestId(TERMINAL);

    fireEvent.click(screen.getByText("sign out"));
    await screen.findByRole("status");          // the failure notice

    up = true;
    fireEvent.click(screen.getByText("sign out"));
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });
});

describe("logout that could not revoke server-side", () => {
  it("warns on the login screen the operator lands on", async () => {
    // The warning used to be set on the context and rendered nowhere: only
    // UserMenu displayed it, and that unmounts the instant the phase leaves
    // "signed-in". The person who needs to know was the one person who could
    // not see it. Raised in review.
    routeFetch({
      "/api/auth/status": json(STATUS_SIGNED_IN),
      "/api/auth/logout": json({ ok: false }, 503),
    });
    render(
      <AuthProvider>
        <AuthGate><Terminal /></AuthGate>
        <SignOutButton />
      </AuthProvider>
    );

    fireEvent.click(await screen.findByText("sign out"));

    await waitFor(() => {
      const notices = screen.getAllByRole("status").map(n => n.textContent).join(" ");
      expect(notices).toMatch(/could not revoke/i);
    });
  });

  it("says nothing extra when revocation succeeded", async () => {
    routeFetch({
      "/api/auth/status": json(STATUS_SIGNED_IN),
      "/api/auth/logout": json({ ok: true }),
    });
    render(
      <AuthProvider>
        <AuthGate><Terminal /></AuthGate>
        <SignOutButton />
      </AuthProvider>
    );

    fireEvent.click(await screen.findByText("sign out"));

    await screen.findByRole("button", { name: /sign in/i });
    const notices = screen.queryAllByRole("status").map(n => n.textContent).join(" ");
    expect(notices).not.toMatch(/could not revoke/i);
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
