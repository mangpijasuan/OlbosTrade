/**
 * The global 401 interceptor.
 *
 * This exists because there are 66 fetch call sites across ~30 files, and
 * handling expiry at each of them is the bet the backend refused to make with
 * per-route auth. The tests below are mostly about what it must NOT do: fire
 * on another origin, fire on the auth calls themselves, or disturb the
 * response its caller is waiting for.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  installSessionExpiryInterceptor, onSessionExpired,
  uninstallSessionExpiryInterceptor,
} from "../sessionExpiry";

function stubFetch(status: number, body = "{}") {
  const spy = vi.fn(async () => new Response(body, { status }));
  window.fetch = spy as unknown as typeof window.fetch;
  return spy;
}

afterEach(() => {
  uninstallSessionExpiryInterceptor();
  vi.restoreAllMocks();
});

describe("session expiry interceptor", () => {
  it("fires on a 401 from this app's API", async () => {
    stubFetch(401);
    installSessionExpiryInterceptor();
    const seen = vi.fn();
    onSessionExpired(seen);

    await fetch("/api/portfolio/positions");
    expect(seen).toHaveBeenCalledTimes(1);
  });

  it("does not fire on a successful response", async () => {
    stubFetch(200);
    installSessionExpiryInterceptor();
    const seen = vi.fn();
    onSessionExpired(seen);

    await fetch("/api/portfolio/positions");
    expect(seen).not.toHaveBeenCalled();
  });

  it("does not fire on a 403", async () => {
    // 403 is the operator-key check refusing a specific action; the session is
    // fine. Treating it as expiry would sign the user out for clicking a
    // button they lack the key for.
    stubFetch(403);
    installSessionExpiryInterceptor();
    const seen = vi.fn();
    onSessionExpired(seen);

    await fetch("/api/trade-desk/execute");
    expect(seen).not.toHaveBeenCalled();
  });

  it.each(["/api/auth/login", "/api/auth/logout", "/api/auth/status"])(
    "ignores a 401 from %s",
    async (path) => {
      // A 401 from login IS the answer to the question asked. Treating it as
      // an expiry would make the login form fight itself for the screen.
      stubFetch(401);
      installSessionExpiryInterceptor();
      const seen = vi.fn();
      onSessionExpired(seen);

      await fetch(path, { method: "POST" });
      expect(seen).not.toHaveBeenCalled();
    }
  );

  it("ignores a 401 from another origin", async () => {
    // A third-party API refusing us must never sign the operator out.
    stubFetch(401);
    installSessionExpiryInterceptor();
    const seen = vi.fn();
    onSessionExpired(seen);

    await fetch("https://api.example.com/api/whatever");
    expect(seen).not.toHaveBeenCalled();
  });

  it("ignores a 401 from a non-API path on this origin", async () => {
    stubFetch(401);
    installSessionExpiryInterceptor();
    const seen = vi.fn();
    onSessionExpired(seen);

    await fetch("/static/thing.css");
    expect(seen).not.toHaveBeenCalled();
  });

  it("returns the original response untouched", async () => {
    // It observes; it does not intervene. The caller still gets its own 401
    // and its own body to render.
    stubFetch(401, JSON.stringify({ detail: "Authentication required" }));
    installSessionExpiryInterceptor();
    onSessionExpired(() => {});

    const res = await fetch("/api/equity/signals");
    expect(res.status).toBe(401);
    await expect(res.json()).resolves.toEqual({ detail: "Authentication required" });
  });

  it("survives a listener that throws", async () => {
    stubFetch(401);
    installSessionExpiryInterceptor();
    onSessionExpired(() => { throw new Error("bad listener"); });
    const good = vi.fn();
    onSessionExpired(good);

    await expect(fetch("/api/equity/signals")).resolves.toBeDefined();
    expect(good).toHaveBeenCalled();
  });

  it("accepts Request and URL inputs, not just strings", async () => {
    stubFetch(401);
    installSessionExpiryInterceptor();
    const seen = vi.fn();
    onSessionExpired(seen);

    // jsdom's Request will not resolve a relative URL, so these are absolute
    // against this origin — which is also the shape a Request built from
    // window.location would really have.
    const abs = `${window.location.origin}/api/risk/daily-pnl`;
    await fetch(new Request(abs));
    await fetch(new URL(abs));
    expect(seen).toHaveBeenCalledTimes(2);
  });

  it("restores the original fetch on uninstall", async () => {
    const original = stubFetch(401);
    installSessionExpiryInterceptor();
    expect(window.fetch).not.toBe(original);

    uninstallSessionExpiryInterceptor();
    expect(window.fetch).toBe(original);
  });

  it("stops notifying after unsubscribe", async () => {
    stubFetch(401);
    installSessionExpiryInterceptor();
    const seen = vi.fn();
    const off = onSessionExpired(seen);

    await fetch("/api/x");
    off();
    await fetch("/api/x");
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
