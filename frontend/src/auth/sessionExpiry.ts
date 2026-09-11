/**
 * One place that notices a session has expired, for every call in the app.
 *
 * There are 66 fetch call sites across ~30 files — api/client.ts plus raw
 * fetches in hooks, panels and trade-desk composers. Handling 401 at each of
 * them is the same bet the backend refused to make with per-route auth: it
 * only takes one missed site for an expired session to surface as an empty
 * panel or a thrown error instead of "please sign in again", and the missed
 * one is found by a confused operator.
 *
 * So this wraps window.fetch once. Every request to this app's API, current or
 * future, routes through it without the call site knowing.
 *
 * Scope is deliberately narrow — it only *observes*. It never retries, never
 * redirects, never touches the response body; it fires a callback and hands
 * the response back untouched. The security boundary is the server, which
 * 401s whatever the client believes.
 */

type Listener = () => void;

const listeners = new Set<Listener>();
let installed = false;
let originalFetch: typeof window.fetch | null = null;

/** Auth's own calls: a 401 from /login is an answer, not an expiry. */
const IGNORED = ["/api/auth/login", "/api/auth/logout", "/api/auth/status"];

function isApiRequest(url: string): boolean {
  try {
    // Relative URLs are this app's API; absolute ones only count when they
    // point back at this origin, so a third-party 401 cannot log anyone out.
    const parsed = new URL(url, window.location.origin);
    if (parsed.origin !== window.location.origin) return false;
    return parsed.pathname.startsWith("/api/");
  } catch {
    return false;
  }
}

function shouldSignal(url: string): boolean {
  if (!isApiRequest(url)) return false;
  try {
    const path = new URL(url, window.location.origin).pathname;
    return !IGNORED.includes(path);
  } catch {
    return false;
  }
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

export function onSessionExpired(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function installSessionExpiryInterceptor(): () => void {
  if (installed) return () => {};
  installed = true;
  // Stored raw, not bound: uninstall has to hand back the exact function it
  // replaced, or repeated install/uninstall cycles leave a stack of wrappers
  // behind. `this` is restored at the call site instead.
  originalFetch = window.fetch;

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const res = await originalFetch!.call(window, input as RequestInfo, init);
    if (res.status === 401 && shouldSignal(urlOf(input))) {
      // Notify, but hand the response back exactly as received — the caller
      // still sees its own 401 and can render whatever it was going to.
      listeners.forEach(fn => {
        try {
          fn();
        } catch {
          /* a broken listener must not break the request */
        }
      });
    }
    return res;
  };

  return uninstallSessionExpiryInterceptor;
}

export function uninstallSessionExpiryInterceptor(): void {
  if (!installed || !originalFetch) return;
  window.fetch = originalFetch;
  originalFetch = null;
  installed = false;
  listeners.clear();
}
